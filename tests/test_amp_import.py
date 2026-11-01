"""Offline absolute-import regression; not a live CrewAI runtime test."""
import ast
from pathlib import Path
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class AmpImportRegressionTests(unittest.TestCase):
    def test_imports_used_by_final_hook_are_absolute(self):
        tree = ast.parse((ROOT / "src/analisti_2027/crew.py").read_text(encoding="utf-8"))
        for name, module in (("bind_report", "analisti_2027.report_contract"), ("finish", "analisti_2027.integration")):
            with self.subTest(name=name):
                nodes = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and any(a.name == name for a in n.names)]
                self.assertEqual(len(nodes), 1)
                self.assertEqual(nodes[0].level, 0)
                self.assertEqual(nodes[0].module, module)
                package = types.ModuleType("analisti_2027")
                package.__path__ = []
                target = types.ModuleType(module)
                for alias in nodes[0].names:
                    setattr(target, alias.name, object())
                statement = ast.fix_missing_locations(ast.Module(body=[nodes[0]], type_ignores=[]))
                namespace = {"__name__":"amp_loose_import_test", "__package__":""}
                with patch.dict("sys.modules", {"analisti_2027":package, module:target}):
                    exec(compile(statement, "crew_import", "exec"), namespace)
                self.assertIs(namespace[name], getattr(target, name))

    def test_old_relative_import_reproduces_failure(self):
        namespace = {"__name__":"amp_loose_import_test", "__package__":""}
        with self.assertRaisesRegex(ImportError, "no known parent package"):
            exec("from .quality import check_output", namespace)

if __name__ == "__main__":
    unittest.main()
