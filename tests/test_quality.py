import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("quality", Path(__file__).resolve().parents[1] / "src/analisti_2027/quality.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)

class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.m = {"capital_eur": 3000, "information_cutoff": "2026-10-27", "portfolios": {k: {"stock": 2000, "cash": 1000} for k in "ABC"}}
        self.report = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + s + "\nND: dati non acquisiti; verifica necessaria." for s in q.SECTIONS) + "\n" + q.END
        data = b"SYNTHETIC FIXTURE ONLY: revenue 10 EUR."
        (self.root / "snapshot.txt").write_bytes(data)
        self.e = {"id": "TEST1", "source_url": "https://example.invalid/synthetic", "publication_date": "2026-10-26", "snapshot_path": "snapshot.txt", "sha256": hashlib.sha256(data).hexdigest(), "excerpt": "revenue 10 EUR", "company": "SYNTHETIC", "metric": "revenue", "period": "fixture", "unit": "EUR", "currency": "EUR", "value": 10, "reviewer": "test fixture only", "reviewed_on": "2026-10-31", "human_verified": True}
    def run_audit(self, records=None, report=None):
        return q.audit(self.report if report is None else report, self.m, [self.e] if records is None else records, self.root)
    def test_valid_fixture_not_truth_certificate(self):
        a = self.run_audit()
        self.assertTrue(a["checks_passed"])
        self.assertFalse(a["financially_validated"])
    def test_missing_evidence_only_preliminary(self):
        a = self.run_audit([])
        self.assertTrue(a["checks_passed"])
        self.assertIn("NO_VERIFIED_EVIDENCE", " ".join(a["warnings"]))
    def test_invalid_records(self):
        for field, value in [("publication_date", "2026-10-28"), ("source_url", "http://example.invalid"), ("sha256", "bad"), ("excerpt", "absent quotation"), ("snapshot_path", "../outside.txt"), ("human_verified", False), ("reviewer", ""), ("value", "NaN"), ("currency", ""), ("reviewed_on", "bad date")]:
            with self.subTest(field=field):
                r = dict(self.e, **{field: value})
                self.assertFalse(self.run_audit([r])["checks_passed"])
    def test_duplicate_ids(self):
        self.assertFalse(self.run_audit([self.e, self.e])["checks_passed"])
    def test_unknown_citation(self):
        self.assertFalse(self.run_audit(report=self.report.replace(q.END, "[E:UNKNOWN]\n" + q.END))["checks_passed"])
    def test_known_citation(self):
        self.assertTrue(self.run_audit(report=self.report.replace(q.END, "[E:TEST1]\n" + q.END))["checks_passed"])
    def test_invalid_budgets(self):
        original = copy.deepcopy(self.m)
        for val in [-1, 999, "NaN", "Infinity"]:
            with self.subTest(value=val):
                self.m = copy.deepcopy(original)
                self.m["portfolios"]["A"]["cash"] = val
                self.assertFalse(self.run_audit()["checks_passed"])
    def test_bad_cutoff(self):
        self.m["information_cutoff"] = "bad"
        self.assertFalse(self.run_audit()["checks_passed"])
    def test_missing_portfolio(self):
        del self.m["portfolios"]["C"]
        self.assertFalse(self.run_audit()["checks_passed"])
    def test_truncation(self):
        self.assertFalse(self.run_audit(report=self.report.split("## Scheda Shin-Etsu")[0])["checks_passed"])
    def test_empty_section(self):
        self.assertFalse(self.run_audit(report=self.report.replace("ND: dati non acquisiti; verifica necessaria.", "", 1))["checks_passed"])
    def test_nd_reason(self):
        self.assertFalse(self.run_audit(report=self.report.replace("ND: dati non acquisiti; verifica necessaria.", "ND", 1))["checks_passed"])
    def test_word_limit(self):
        self.assertFalse(self.run_audit(report=self.report.replace(q.END, "word " * 801 + q.END))["checks_passed"])
    def test_placeholder(self):
        self.assertFalse(self.run_audit(report=self.report.replace("ND: dati non acquisiti; verifica necessaria.", "TODO", 1))["checks_passed"])
    def test_hook_pass_and_fail(self):
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.m))
        obj = SimpleNamespace(raw=self.report)
        self.assertIs(q.check_output(obj, self.root), obj)
        with self.assertRaisesRegex(ValueError, "QUALITY_GATE_FAILED"):
            q.check_output(SimpleNamespace(raw="truncated"), self.root)
    def test_integration_syntax(self):
        import ast
        p = Path(__file__).resolve().parents[1] / "src/analisti_2027/crew.py"
        if p.exists():
            tree = ast.parse(p.read_text())
            method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "validate_final_output")
            self.assertTrue(any(isinstance(d, ast.Name) and d.id == "after_kickoff" for d in method.decorator_list))

if __name__ == "__main__":
    unittest.main()
