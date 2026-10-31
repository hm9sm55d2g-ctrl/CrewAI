from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

def compare_resources(root):
    issues = []
    for folder in ("config", "knowledge"):
        a = root / folder
        b = root / "src/analisti_2027" / folder
        if not a.is_dir() or not b.is_dir():
            issues.append("MISSING_DIRECTORY:" + folder)
            continue
        left = {p.relative_to(a).as_posix(): p.read_bytes() for p in a.rglob("*") if p.is_file()}
        right = {p.relative_to(b).as_posix(): p.read_bytes() for p in b.rglob("*") if p.is_file()}
        for name in sorted(set(left) | set(right)):
            if name not in left or name not in right or left[name] != right[name]:
                issues.append(folder + "/" + name)
    return issues

class ConfigSyncTests(unittest.TestCase):
    def test_repository_resources_identical(self):
        self.assertEqual(compare_resources(ROOT), [], "Root and package resources diverge")
    def test_detector_accepts_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for folder in ("config", "knowledge"):
                for prefix in (root, root / "src/analisti_2027"):
                    (prefix / folder).mkdir(parents=True)
                    (prefix / folder / "fixture.txt").write_bytes(b"same")
            self.assertEqual(compare_resources(root), [])
            p = root / "config/fixture.txt"
            p.write_bytes(b"different")
            self.assertIn("config/fixture.txt", compare_resources(root))
            p.write_bytes(b"same")
            (root / "knowledge/extra.txt").write_bytes(b"extra")
            self.assertIn("knowledge/extra.txt", compare_resources(root))
            (root / "knowledge/extra.txt").unlink()
            p.unlink()
            self.assertIn("config/fixture.txt", compare_resources(root))

if __name__ == "__main__":
    unittest.main()
