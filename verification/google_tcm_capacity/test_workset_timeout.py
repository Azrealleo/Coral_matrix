"""Timeout typo upgrade tests; temporary synthetic installs, not RTL execution."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import prepare_workset as installer
from prepare import digest
import upgrade_workset_timeout as migration


class TimeoutUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory())) / "source"
        self.root.mkdir()
        self.stack.enter_context(patch.object(installer, "verify_control"))
        self.stack.enter_context(patch.object(installer, "git", return_value=b"synthetic official header"))
        self.stack.enter_context(patch.object(installer, "control_evidence", return_value={}))
        for name in ("tcm_control_manifest.json", "tcm_capacity_manifest.json"):
            (self.root / name).write_bytes(b'{"synthetic_baseline": true}\n')

    def install_old(self):
        manifest = installer.prepare(self.root)
        old, _ = migration.benchmark_versions()
        for name in manifest["files"]:
            if name.endswith("/workset_bench.py"):
                (self.root / name).write_bytes(old)
                manifest["files"][name] = migration.OLD_SHA
        manifest["tools"]["workset_bench.py"] = migration.OLD_SHA
        self.manifest_path.write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
        return manifest

    @property
    def manifest_path(self):
        return self.root / installer.MANIFEST

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()}

    def assert_refused_without_writes(self):
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError)):
            migration.upgrade(self.root)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(list(self.root.parent.glob("workset_timeout_upgrade.*")), [])

    def test_known_typo_only_and_backed_up_upgrade(self):
        manifest = self.install_old()
        before = self.snapshot()
        backup = migration.upgrade(self.root)
        after = self.snapshot()
        changed = {n for n in before if before[n] != after[n]}
        benches = {n for n in before if n.endswith("/workset_bench.py")}
        self.assertEqual(len(benches), 6)
        self.assertEqual(changed, benches | {installer.MANIFEST})
        self.assertEqual((backup / installer.MANIFEST).read_bytes(), before[installer.MANIFEST])
        old, new = migration.benchmark_versions()
        self.assertEqual((backup / "workset_bench.old.py").read_bytes(), old)
        self.assertEqual(digest(old), migration.OLD_SHA)
        self.assertEqual(old.replace(migration.OLD_LINE, migration.NEW_LINE), new)
        updated = installer.verify(self.root)
        self.assertEqual(updated["control_pass_evidence"], manifest["control_pass_evidence"])
        self.assertEqual(updated["harness_migrations"][0]["migration"], migration.MIGRATION)
        stable = self.snapshot()
        self.assertIsNone(migration.upgrade(self.root))
        self.assertEqual(stable, self.snapshot())
        self.assertEqual(len(list(self.root.parent.glob("workset_timeout_upgrade.*"))), 1)

    def test_no_install_and_fresh_fixed_install_are_noops(self):
        before = self.snapshot()
        self.assertIsNone(migration.upgrade(self.root))
        self.assertEqual(before, self.snapshot())
        installer.prepare(self.root)
        before = self.snapshot()
        self.assertIsNone(migration.upgrade(self.root))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(list(self.root.parent.glob("workset_timeout_upgrade.*")), [])

    def test_reject_changed_benchmark(self):
        self.install_old()
        path = self.root / installer.PACKAGE / "d32/workset_bench.py"
        path.write_bytes(path.read_bytes() + b"# changed\n")
        self.assert_refused_without_writes()

    def test_reject_partial_upgrade(self):
        self.install_old()
        (self.root / installer.PACKAGE / "d32/workset_bench.py").write_bytes(migration.benchmark_versions()[1])
        self.assert_refused_without_writes()

    def test_reject_missing_generated_file(self):
        self.install_old()
        (self.root / installer.PACKAGE / "d32/workset_bench.py").unlink()
        self.assert_refused_without_writes()

    def test_reject_bundled_unrelated_benchmark_edit(self):
        self.install_old()
        other = self.root.parent / "changed_tools"
        other.mkdir()
        (other / "workset_bench.py").write_bytes(migration.benchmark_versions()[1] + b"# unrelated\n")
        with patch.object(installer, "HERE", other):
            self.assert_refused_without_writes()

    def test_reject_other_generated_file_change(self):
        self.install_old()
        (self.root / installer.PACKAGE / "workset_program.cc").write_bytes(b"not the known firmware")
        self.assert_refused_without_writes()

    def test_reject_unknown_tool_version(self):
        manifest = self.install_old()
        manifest["tools"]["prepare_workset.py"] = "0" * 64
        self.manifest_path.write_text(json.dumps(manifest))
        self.assert_refused_without_writes()

    def test_reject_wrong_base_identity(self):
        self.install_old()
        (self.root / "tcm_control_manifest.json").write_bytes(b"{}")
        self.assert_refused_without_writes()

    def test_reject_already_fixed_but_tampered(self):
        installer.prepare(self.root)
        (self.root / installer.PACKAGE / "d128/workset_bench.py").write_bytes(b"tampered")
        self.assert_refused_without_writes()

    def test_original_baseline_verifier_is_required(self):
        self.install_old()
        with patch.object(installer, "verify_control", side_effect=ValueError("baseline changed")):
            self.assert_refused_without_writes()

    def test_runner_upgrades_before_strict_prepare(self):
        script = (installer.HERE / "run_workset.sh").read_text()
        self.assertLess(script.index('"$tcm_here/upgrade_workset_timeout.py" --upstream'),
                        script.index('"$tcm_here/prepare_workset.py" prepare'))
        self.assertNotIn("clean --expunge", script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
