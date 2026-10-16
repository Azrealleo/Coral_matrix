"""Git should ignore bytecode without hiding actual verification changes."""
from pathlib import Path
import subprocess
import unittest


class CacheIgnoreTests(unittest.TestCase):
    def test_only_python_cache_paths_are_ignored(self):
        root = Path(__file__).resolve().parents[2]
        prefix = "verification/google_tcm_capacity/"
        ignored = [prefix + "__pycache__/workset_spec.cpython-311.pyc", prefix + "generated.pyc",
                   prefix + "generated.pyo"]
        visible = [prefix + "workset_program.cc", prefix + "run_workset.sh", prefix + "local_notes.txt"]
        result = subprocess.run(["git", "-C", str(root), "check-ignore", "--no-index", "--stdin", "-z"],
                                input=b"\0".join(s.encode() for s in ignored + visible) + b"\0",
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({s.decode() for s in result.stdout.split(b"\0") if s}, set(ignored))


if __name__ == "__main__":
    unittest.main(verbosity=2)
