"""Synthetic configured-output regression tests; no Bazel/RTL execution."""
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from resolve_bazel_elf import resolve_elf


def firmware(root, config="k8-fastbuild-ST-123456"):
    relative = f"bazel-out/{config}/bin/tests/cocotb/tcm_control/control_program.elf"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(52)
    header[:6] = b"\x7fELF\x01\x01"
    header[18:20] = (243).to_bytes(2, "little")
    path.write_bytes(header)
    return relative, path


class BazelOutputTests(unittest.TestCase):
    def test_transition_output_without_bazel_bin_is_resolved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "execution root with spaces"
            root.mkdir()
            relative, path = firmware(root)
            self.assertFalse((root / "bazel-bin").exists())
            self.assertEqual(resolve_elf(root, relative + "\n"), path.resolve())

    def test_duplicate_same_output_is_not_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative, path = firmware(root)
            self.assertEqual(resolve_elf(root, relative + "\n" + relative), path.resolve())

    def test_multiple_configured_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            one, _ = firmware(root, "config-one")
            two, _ = firmware(root, "config-two")
            with self.assertRaises(ValueError):
                resolve_elf(root, one + "\n" + two)

    def test_empty_wrong_name_and_escaping_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for text in ("", "../control_program.elf", "/tmp/control_program.elf",
                         "bazel-out/a/../control_program.elf", "bazel-out/a/other.elf"):
                with self.assertRaises(ValueError, msg=text):
                    resolve_elf(root, text)

    def test_missing_and_wrong_architecture_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative, path = firmware(root)
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                resolve_elf(root, relative)
            for header in (b"not an ELF", b"\x7fELF\x02\x01" + bytes(46),
                           b"\x7fELF\x01\x01" + bytes(46)):
                path.write_bytes(header)
                with self.assertRaises(ValueError):
                    resolve_elf(root, relative)

    def test_runner_queries_exact_label_with_same_build_flags(self):
        script = (HERE / "run_control.sh").read_text()
        self.assertIn('cquery "${tcm_flags[@]}"', script)
        self.assertIn('config(//tests/cocotb/tcm_control:control_program.elf, target)', script)
        self.assertIn('--output=files', script)
        self.assertIn('info execution_root', script)
        self.assertIn('cp -L -- "$tcm_elf"', script)
        self.assertNotIn('cp -L bazel-bin/tests/cocotb/tcm_control/control_program.elf', script)
        self.assertNotIn('find ', script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
