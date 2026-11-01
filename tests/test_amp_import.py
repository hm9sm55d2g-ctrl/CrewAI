"""Offline import regression; fake quality module, not a CrewAI runtime test."""
import ast
from pathlib import Path
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class AmpImportRegressionTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "src/analisti_2027/crew.py").read_text(encoding="utf-8"))
        self.nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and any(a.name == "check_output" for a in n.names)]

    def test_quality_import_is_absolute(self):
        self.assertEqual(len(self.nodes), 1)
        self.assertEqual(self.nodes[0].level, 0)
        self.assertEqual(self.nodes[0].module, "analisti_2027.quality")

    def test_actual_import_statement_without_parent(self):
        self.assertEqual(len(self.nodes), 1)
        package = types.ModuleType("analisti_2027")
        package.__path__ = []
        quality = types.ModuleType("analisti_2027.quality")
        sentinel = object()
        quality.check_output = sentinel
        statement = ast.fix_missing_locations(ast.Module(body=[self.nodes[0]], type_ignores=[]))
        namespace = {"__name__": "amp_loose_import_test", "__package__": ""}
        with patch.dict("sys.modules", {"analisti_2027": package, "analisti_2027.quality": quality}):
            exec(compile(statement, "crew_import", "exec"), namespace)
        self.assertIs(namespace["check_output"], sentinel)

    def test_old_relative_import_reproduces_failure(self):
        namespace = {"__name__": "amp_loose_import_test", "__package__": ""}
        with self.assertRaisesRegex(ImportError, "no known parent package"):
            exec("from .quality import check_output", namespace)

if __name__ == "__main__":
    unittest.main()
