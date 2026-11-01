"""Reduced report fixtures: punctuation tolerance is not financial validation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("report_quality", ROOT / "src/analisti_2027/quality.py")
q = importlib.util.module_from_spec(spec)
spec.loader.exec_module(q)

class ReportFormatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.m = {"capital_eur":3000, "information_cutoff":"2026-10-27", "portfolios":{k:{"cash":3000} for k in "ABC"}}
        self.reason = "ND: evidenze non acquisite; verifica entro il cutoff necessaria."
        self.body = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + s + "\n" + self.reason for s in q.SECTIONS)
        self.report = self.body + "\n\n" + q.END

    def audit(self, report=None):
        return q.audit(self.report if report is None else report, self.m, [], self.root)

    def test_canonical_marker(self):
        r = self.audit()
        self.assertTrue(r["checks_passed"])
        self.assertEqual(r["end_marker_variant"], "canonical")

    def test_period_marker_with_warning(self):
        r = self.audit(self.report + ".")
        self.assertTrue(r["checks_passed"])
        self.assertEqual(r["end_marker_variant"], "terminal_period")
        self.assertIn("END_MARKER_TERMINAL_PERIOD_ACCEPTED", " ".join(r["warnings"]))

    def test_blank_lines_allowed(self):
        self.assertTrue(self.audit(self.report + ".\n\n")["checks_passed"])

    def test_other_marker_variants_rejected(self):
        for marker in (q.END + "..", q.END + "!", "**" + q.END + "**", q.END.lower(), q.END + " extra"):
            with self.subTest(marker=marker):
                r = self.audit(self.body + "\n" + marker)
                self.assertIn("MISSING_END_MARKER", r["errors"])

    def test_missing_marker_rejected(self):
        self.assertIn("MISSING_END_MARKER", self.audit(self.body)["errors"])

    def test_text_after_marker_rejected(self):
        self.assertIn("MISSING_END_MARKER", self.audit(self.report + ".\nAltro testo")["errors"])

    def test_truncated_report_rejected_even_with_marker(self):
        short = self.body.split("## Scheda Shin-Etsu")[0] + "\n" + q.END + "."
        self.assertIn("SECTION_SET_OR_ORDER_INVALID", self.audit(short)["errors"])

    def test_empty_last_section_rejected_for_both_markers(self):
        empty = self.body[:self.body.rfind(self.reason)]
        for marker in (q.END, q.END + "."):
            with self.subTest(marker=marker):
                self.assertIn("EMPTY_SECTION_OR_ND_WITHOUT_REASON", self.audit(empty + "\n" + marker)["errors"])

    def test_nd_without_reason_still_rejected(self):
        r = self.audit(self.report.replace(self.reason, "ND", 1) + ".")
        self.assertIn("EMPTY_SECTION_OR_ND_WITHOUT_REASON", r["errors"])

    def test_inline_placeholder_links_rejected(self):
        for link in ("[fonte](#)", "[fonte]()", "[fonte](  #  )", '[fonte](# "titolo")', "[fonte](<>)", "[fonte](<#>)"):
            with self.subTest(link=link):
                self.assertIn("PLACEHOLDER_LINK", self.audit(self.report.replace(self.reason, link, 1))["errors"])

    def test_reference_placeholder_links_rejected(self):
        for definition in ("[fonte]: #", "[fonte]:", "[fonte]: <#>"):
            with self.subTest(definition=definition):
                r = self.audit(self.report.replace(self.reason, self.reason + "\n" + definition, 1))
                self.assertIn("PLACEHOLDER_LINK", r["errors"])

    def test_html_placeholder_links_rejected(self):
        for link in ('<a href="#">fonte</a>', "<a href=''>fonte</a>"):
            with self.subTest(link=link):
                self.assertIn("PLACEHOLDER_LINK", self.audit(self.report.replace(self.reason, link, 1))["errors"])

    def test_external_reference_is_not_certified(self):
        text = self.report.replace(self.reason, "Riferimento non acquisito: [IR](https://investor.nvidia.com/).", 1)
        r = self.audit(text)
        self.assertTrue(r["checks_passed"])
        self.assertFalse(r["financially_validated"])
        self.assertEqual(r["evidence_count"], 0)

    def test_internal_fragment_not_hash_only(self):
        self.assertFalse(q.has_placeholder_links("[sezione](#sezione)"))

    def test_reduced_observed_case_flags_link_not_marker(self):
        text = self.report.replace(self.reason, "URL da consultare: [Evidenze finanziarie AVGO](#).", 1) + "."
        r = self.audit(text)
        self.assertIn("PLACEHOLDER_LINK", r["errors"])
        self.assertNotIn("MISSING_END_MARKER", r["errors"])

    def test_report_hash_preserves_original_punctuation(self):
        canonical = self.audit()
        dotted = self.audit(self.report + ".")
        self.assertEqual(dotted["report_sha256"], hashlib.sha256((self.report + ".").encode()).hexdigest())
        self.assertNotEqual(canonical["report_sha256"], dotted["report_sha256"])

    def test_hook_returns_same_unmodified_object(self):
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.m))
        text = self.report + "."
        obj = SimpleNamespace(raw=text)
        self.assertIs(q.check_output(obj, self.root), obj)
        self.assertEqual(obj.raw, text)

    def test_word_limit_still_enforced(self):
        text = self.report.replace(self.reason, "parola " * 801, 1) + "."
        self.assertIn("WORD_LIMIT_EXCEEDED", self.audit(text)["errors"])

    def test_unknown_evidence_still_rejected(self):
        text = self.report.replace(self.reason, "[E:UNKNOWN] " + self.reason, 1) + "."
        self.assertIn("UNKNOWN_EVIDENCE_CITATION:UNKNOWN", self.audit(text)["errors"])

    def test_bad_budget_still_rejected(self):
        self.m["portfolios"]["A"]["cash"] = 2999
        self.assertIn("INVALID_MANDATE_OR_BUDGET", self.audit()["errors"])

    def test_task_copies_identical(self):
        self.assertEqual((ROOT / "config/tasks.yaml").read_bytes(), (ROOT / "src/analisti_2027/config/tasks.yaml").read_bytes())

    def test_prompt_marker_literal_and_cutoff(self):
        text = (ROOT / "config/tasks.yaml").read_text()
        self.assertIn("    FINE REPORT PRELIMINARE\n", text)
        self.assertIn("Vietati link segnaposto", text)
        self.assertIn("Le ricerche devono rispettare il cutoff", text)

if __name__ == "__main__":
    unittest.main()
