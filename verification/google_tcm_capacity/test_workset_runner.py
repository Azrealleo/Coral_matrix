"""Exercise real Bash timeout/exit handling with a fake Bazel; no RTL execution."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def bash_path():
    if os.name == "nt" and shutil.which("git"):
        candidate = Path(shutil.which("git")).resolve().parent.parent / "bin/bash.exe"
        if candidate.is_file():
            return str(candidate)
    return shutil.which("bash")


@unittest.skipUnless(bash_path(), "Bash unavailable")
class WorksetRunnerTests(unittest.TestCase):
    def test_timeout_validation(self):
        text = (HERE / "run_workset.sh").read_text()
        validation = text[text.index("tcm_timeout="):text.index('[[ $(uname -s)')]
        for value, expected in ((None, "21600"), ("21600", "21600"), ("1", "1"),
                                ("86400", "86400"), ("0", None), ("-1", None),
                                ("001", None), ("x", None), ("86401", None), ("999999999999", None)):
            env = dict(os.environ)
            env.pop("TCM_WORKSET_TEST_TIMEOUT_SECONDS", None)
            if value is not None:
                env["TCM_WORKSET_TEST_TIMEOUT_SECONDS"] = value
            result = subprocess.run([bash_path(), "-c", 'set -euo pipefail\n' + validation +
                                     '\nprintf "%s" "$tcm_timeout"'],
                                    env=env, capture_output=True, text=True)
            if expected is None:
                self.assertEqual(result.returncode, 2, (value, result.stderr))
            else:
                self.assertEqual((result.returncode, result.stdout), (0, expected), result.stderr)

    def run_fake_test(self, bazel_exit, emit_log=True, tee_exit=0):
        text = (HERE / "run_workset.sh").read_text()
        start = text.index("printf '[TCM_STAGE] Building/running")
        end = text.index('python3 -B "$tcm_here/prepare_workset.py" log')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = root / "run"
            run.mkdir()
            (root / "fake-bazel.sh").write_bytes(b'''#!/usr/bin/env bash
printf '%s\n' "$@" > arguments.txt
if [[ "$FAKE_EMIT_LOG" == 1 ]]; then
    mkdir -p bazel-testlogs/tests/fake/workset_tcm_workset_test
    printf 'synthetic partial or complete raw log\n' > bazel-testlogs/tests/fake/workset_tcm_workset_test/test.log
fi
printf 'synthetic Bazel output\n'
exit "$FAKE_BAZEL_EXIT"
''')
            (root / "invoke.sh").write_bytes(('''#!/usr/bin/env bash
set -euo pipefail
tcm_run=run
tcm_bazel=./fake-bazel.sh
tcm_startup=()
tcm_flags=(--noshow_progress --jobs=2)
tcm_timeout=21600
tcm_tiles=384
tcm_delay=0
tcm_package=tests/fake
if [[ "$FAKE_TEE_EXIT" != 0 ]]; then
    tee() { command tee "$@"; return "$FAKE_TEE_EXIT"; }
fi
''' + text[start:end] + '\nprintf "REACHED_STRICT_LOG_CHECK\\n"\n').encode())
            env = dict(os.environ, FAKE_BAZEL_EXIT=str(bazel_exit),
                       FAKE_EMIT_LOG=str(int(emit_log)), FAKE_TEE_EXIT=str(tee_exit))
            result = subprocess.run([bash_path(), "-c", "chmod u+x fake-bazel.sh; bash invoke.sh"],
                                    cwd=root, env=env, capture_output=True, text=True)
            artifacts = {p.name: p.read_text() for p in run.iterdir() if p.is_file()}
            arguments = (root / "arguments.txt").read_text().splitlines()
            return result, artifacts, arguments

    def test_timeout_preserves_log_and_rejects_partial_pass(self):
        result, artifacts, args = self.run_fake_test(3)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("test.log", artifacts)
        self.assertIn("bazel_exit=3", artifacts["test-exit-status.txt"])
        self.assertIn("timeout_seconds=21600", artifacts["test-exit-status.txt"])
        self.assertIn("[TCM_WORKSET_INCOMPLETE]", result.stderr)
        self.assertNotIn("REACHED_STRICT_LOG_CHECK", result.stdout)
        self.assertIn("--test_timeout=21600", args)
        self.assertIn("--test_timeout=21600", artifacts["test-command.txt"])
        self.assertIn("test-started-utc.txt", artifacts)
        self.assertIn("test-finished-utc.txt", artifacts)

    def test_success_still_requires_strict_log_check(self):
        result, artifacts, args = self.run_fake_test(0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REACHED_STRICT_LOG_CHECK", result.stdout)
        self.assertIn("test.log", artifacts)
        self.assertNotIn("[TCM_WORKSET_PASS]", result.stdout)
        self.assertIn("--cache_test_results=no", args)

    def test_zero_exit_without_log_cannot_pass(self):
        result, artifacts, _ = self.run_fake_test(0, emit_log=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("test.log", artifacts)
        self.assertNotIn("REACHED_STRICT_LOG_CHECK", result.stdout)
        self.assertIn("refusing PASS", result.stderr)

    def test_tee_failure_cannot_pass(self):
        result, artifacts, _ = self.run_fake_test(0, tee_exit=7)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("tee_exit=7", artifacts["test-exit-status.txt"])
        self.assertIn("test.log", artifacts)
        self.assertNotIn("REACHED_STRICT_LOG_CHECK", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
