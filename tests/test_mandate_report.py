"""Mandate renderer tests use synthetic drafts, not an LLM kickoff."""
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(ROOT / "src"), *sys.path]):
    c = importlib.import_module("analisti_2027.report_contract")

class MandateReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()
        self.m = {"capital_eur":3000, "information_cutoff":"2026-10-27", "portfolios":{
            "A":{"AVGO":750,"NVDA":600,"AMZN":600,"ShinEtsu":450,"cash":600},
            "B":{"AVGO":900,"NVDA":750,"AMZN":750,"ShinEtsu":600,"cash":0},
            "C":{"AVGO":600,"NVDA":450,"AMZN":450,"ShinEtsu":300,"cash":1200}}}
        self.persist()
        (self.root / "knowledge/evidenze.txt").write_text("Nessuna evidenza verificata.\nhttps://investor.nvidia.com/\n")
        self.sections = ["ND: dati non acquisiti; revisione necessaria." for _ in range(9)]
        self.sections[2] = "Budget azionario massimo di 3000 EUR."
        self.sections[3] = "### NVDA\nTesi H1: dominanza delle GPU. Ricercare dati nel 2023."
        self.sections[4] = "Attivita industriale attribuita senza fonte."
        self.sections[6] = "### A (AVGO)\nCrescita.\n### B (NVDA)\nDominanza.\n### C (AMZN)\nEspansione."
        self.draft = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + s + "\n" + p for s,p in zip(c.SECTIONS,self.sections)) + "\n\n" + c.END
        self.obj = SimpleNamespace(raw=self.draft, tasks_output=[SimpleNamespace(raw=self.draft)], pydantic=None, json_dict=None)

    def persist(self):
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.m))

    def bind(self, obj=None):
        return c.bind_report(self.obj if obj is None else obj, self.root, self.root / "artifacts")

    def test_exact_portfolios_and_controls(self):
        _, block = c.render_blocks(self.m)
        self.assertIn("|A|750|600|600|450|600|3000|", block)
        self.assertIn("|B|900|750|750|600|0|3000|", block)
        self.assertIn("|C|600|450|450|300|1200|3000|", block)
        for value in ("1050", "600", "1500"):
            self.assertIn("cassa " + value + " EUR", block)

    def test_observed_company_portfolio_confusion_rejected(self):
        self.assertIn("PORTFOLIO_COMPANY_CONFUSION", c.contract_errors(self.draft,self.m))
        self.assertIn("SCENARIO_IDS_USED_AS_COMPANY_THESES", c.contract_errors(self.draft,self.m))

    def test_binding_fixes_authoritative_sections(self):
        final = self.bind()
        self.assertEqual(c.contract_errors(final.raw,self.m), [])
        self.assertNotIn("### A (AVGO)", final.raw)
        self.assertNotIn("budget azionario massimo", final.raw.lower())
        self.assertIn("Capitale complessivo: 3000 EUR", final.raw)
        self.assertIn("2026-10-27", final.raw)

    def test_no_evidence_no_unsupported_company_assertions(self):
        final = self.bind().raw
        self.assertNotIn("dominanza", final.lower())
        self.assertNotIn("2023", final)
        self.assertIn("non coincide con la liquidita aziendale", final)
        self.assertIn("Tesi e controtesi: ND", final)

    def test_original_object_and_last_task_unmodified(self):
        final = self.bind()
        self.assertIsNot(final,self.obj)
        self.assertEqual(self.obj.raw,self.draft)
        self.assertEqual(self.obj.tasks_output[-1].raw,self.draft)
        self.assertEqual(final.tasks_output[-1].raw,final.raw)

    def test_audit_artifact_contains_both_versions(self):
        final = self.bind()
        artifacts=list((self.root / "artifacts").glob("*.json"))
        self.assertEqual(len(artifacts),1)
        record=json.loads(artifacts[0].read_text())
        self.assertEqual(record["draft_raw"],self.draft)
        self.assertEqual(record["final_raw"],final.raw)
        self.assertEqual(record["replaced_sections"],[1,2,3,4,5,7,9])
        self.assertFalse(record["financially_validated"])
        self.assertTrue(record["semantic_review_required"])

    def test_scenarios_and_review_preserved(self):
        parts=c.split_sections(self.bind().raw)
        self.assertEqual(parts[5],self.sections[5])
        self.assertEqual(parts[7],self.sections[7])

    def test_reference_is_not_acquired_evidence(self):
        final=self.bind().raw
        self.assertIn("https://investor.nvidia.com/",final)
        self.assertIn("NON documenti letti o verificati",final)

    def test_no_url_invented(self):
        (self.root / "knowledge/evidenze.txt").write_text("Nessuna evidenza.")
        final=self.bind().raw
        self.assertNotIn("https://",final)
        self.assertIn("nessun indirizzo fornito",final)

    def test_invalid_mandate_rejected(self):
        for value in (-1, "NaN", True, 300.0, "100.001"):
            m=copy.deepcopy(self.m);m["portfolios"]["A"]["AVGO"]=value
            with self.subTest(value=value):
                with self.assertRaises(ValueError):c.render_blocks(m)

    def test_missing_asset_rejected(self):
        del self.m["portfolios"]["A"]["ShinEtsu"]
        with self.assertRaises(ValueError):c.render_blocks(self.m)

    def test_missing_end_marker_not_repaired(self):
        bad=SimpleNamespace(raw=self.draft.replace(c.END,""))
        with self.assertRaisesRegex(ValueError,"DRAFT_STRUCTURE_FAILED"):
            self.bind(bad)

    def test_placeholder_link_not_repaired(self):
        bad=SimpleNamespace(raw=self.draft.replace(self.sections[0],"[fonte](#)",1))
        with self.assertRaisesRegex(ValueError,"PLACEHOLDER_LINK"):
            self.bind(bad)

    def test_final_word_limit_remains_enforced(self):
        self.assertLessEqual(len(self.bind().raw.split()),800)

    def test_structured_output_explicitly_rejected(self):
        self.obj.json_dict={"report":"not supported"}
        with self.assertRaisesRegex(ValueError,"STRUCTURED_CREW_OUTPUT"):
            self.bind()

    def test_tampered_bound_table_rejected(self):
        text=self.bind().raw.replace("|A|750|", "|A|900|")
        self.assertIn("MANDATE_BLOCK_MISMATCH",c.contract_errors(text,self.m))

if __name__ == "__main__":
    unittest.main()
