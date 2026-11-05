"""Run the final hook body with real binder/gates, not CrewAI/AMP dispatch or an LLM."""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from analisti_2027 import integration as integration
from analisti_2027 import quality as quality
from analisti_2027 import report_contract as contract

ROOT = Path(__file__).resolve().parents[1]


class FixedUTC(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            raise AssertionError("Explicit UTC timezone required")
        return datetime(2026, 11, 5, 12, tzinfo=timezone.utc).astimezone(tz)


class FinalOutputContractTests(unittest.TestCase):
    def setUp(self):
        for module in (quality, integration):
            clock = patch.object(module, "datetime", FixedUTC)
            clock.start()
            self.addCleanup(clock.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "knowledge").mkdir()
        self.mandate = {
            "capital_eur": 3000,
            "information_start": "2026-10-27",
            "temporal_policy": {
                "mode": "rolling", "start_inclusive": True,
                "end": "execution_date", "timezone": "UTC",
                "documents_date_field": "publication_date",
                "market_data_date_field": "observation_date",
            },
            "portfolios": {
                "A": {"AVGO": 750, "NVDA": 600, "AMZN": 600, "ShinEtsu": 450, "cash": 600},
                "B": {"AVGO": 900, "NVDA": 750, "AMZN": 750, "ShinEtsu": 600, "cash": 0},
                "C": {"AVGO": 600, "NVDA": 450, "AMZN": 450, "ShinEtsu": 300, "cash": 1200},
            },
        }
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.mandate), encoding="utf-8")
        (self.root / "knowledge/evidence_registry.json").write_text("[]", encoding="utf-8")
        (self.root / "knowledge/evidenze.txt").write_text(
            "Nessuna evidenza verificata. Riferimento da consultare, non acquisito:\nhttps://investor.nvidia.com/\n",
            encoding="utf-8",
        )
        sections = ["ND: fixture sintetica senza evidenze." for _ in quality.SECTIONS]
        sections[0] = "La raccolta di dati si e conclusa; nessuna evidenza valida."
        sections[1] = "Non ci sono evidenze, pertanto non ci sono riferimenti da consultare."
        sections[2] = "Mancano dati finanziari aggiornati."
        sections[3] = (
            "### AVGO\nDriver: Domanda crescente per semiconduttori.\n"
            "### NVDA\nTesi: Dominanza nel mercato delle GPU.\n"
            "### AMZN\nDriver: Espansione dell'e-commerce e servizi cloud."
        )
        sections[6] = "Le aziende A, B e C non mostrano differenze significative."
        sections[8] = "Acquisire dati aggiornati senza una finestra esplicita."
        self.raw = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join(
            "## " + title + "\n" + body for title, body in zip(quality.SECTIONS, sections)
        ) + "\n\n" + quality.END
        self.draft = SimpleNamespace(
            raw=self.raw, pydantic=None, json_dict=None,
            tasks_output=[SimpleNamespace(raw=self.raw, pydantic=None, json_dict=None)],
        )
        self.context = integration.prepare(self.root)
        tree = ast.parse((ROOT / "src/analisti_2027/crew.py").read_text(encoding="utf-8"))
        crew_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Analisti2027")
        hook = next(n for n in crew_class.body if isinstance(n, ast.FunctionDef) and n.name == "validate_final_output")
        self.assertTrue(any(isinstance(d, ast.Name) and d.id == "after_kickoff" for d in hook.decorator_list))
        hook.decorator_list = []
        def binder(result, resource_root, *, as_of):
            return contract.bind_report(result, resource_root, self.root / "binding", as_of=as_of)
        def finisher(result, context, resource_root):
            return integration.finish(result, context, resource_root, self.root / "integration")
        self.namespace = {"RESOURCE_ROOT": self.root, "bind_report": binder, "finish": finisher}
        exec(compile(ast.Module(body=[hook], type_ignores=[]), "crew.py:final-hook", "exec"), self.namespace)
        self.instance = SimpleNamespace(_integration_context=self.context)

    def run_hook(self):
        return self.namespace["validate_final_output"](self.instance, self.draft)

    def test_undocumented_company_drivers_removed(self):
        final = self.run_hook()
        for assertion in ("Domanda crescente per semiconduttori", "Dominanza nel mercato delle GPU",
                          "Espansione dell'e-commerce e servizi cloud"):
            self.assertNotIn(assertion, final.raw)
        self.assertIn("Tesi e controtesi: ND", final.raw)

    def test_exact_mandate_table_present(self):
        final = self.run_hook()
        for row in ("|A|750|600|600|450|600|3000|", "|B|900|750|750|600|0|3000|",
                    "|C|600|450|450|300|1200|3000|"):
            self.assertIn(row, final.raw)
        self.assertEqual(contract.contract_errors(final.raw, self.mandate, as_of=self.context["as_of"]), [])

    def test_portfolios_not_companies(self):
        final = self.run_hook()
        self.assertNotIn("le aziende a, b e c", final.raw.casefold())
        self.assertIn("A/B/C sono portafogli, non aziende", final.raw)

    def test_deterministic_utc_window_present(self):
        final = self.run_hook()
        parts = contract.split_sections(final.raw)
        expected = "Finestra informativa UTC: dal 2026-10-27 al 2026-11-05, estremi inclusi."
        self.assertIn(expected, parts[0])
        self.assertIn(expected, parts[2])
        self.assertNotIn("La raccolta di dati si e conclusa", final.raw)

    def test_references_preserved_without_claiming_acquisition(self):
        final = self.run_hook()
        self.assertIn("https://investor.nvidia.com/", final.raw)
        self.assertIn("NON documenti letti o verificati", final.raw)
        self.assertNotIn("pertanto non ci sono riferimenti", final.raw)

    def test_returned_final_and_audits_not_original_draft(self):
        final = self.run_hook()
        self.assertIsNot(final, self.draft)
        self.assertEqual(self.draft.raw, self.raw)
        self.assertEqual(self.draft.tasks_output[-1].raw, self.raw)
        self.assertEqual(final.tasks_output[-1].raw, final.raw)
        outcome = quality.audit(final.raw, self.mandate, [], self.root, as_of=self.context["as_of"])
        self.assertTrue(outcome["checks_passed"], outcome["errors"])
        binding = json.loads(next((self.root / "binding").glob("*.json")).read_text(encoding="utf-8"))
        saved = json.loads(next((self.root / "integration").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(binding["draft_raw"], self.raw)
        self.assertEqual(binding["final_raw"], final.raw)
        self.assertEqual(saved["final_report"], final.raw)
        self.assertEqual(saved["context"]["as_of"], "2026-11-05")
        self.assertFalse(saved["financially_validated"])

    def test_hook_fails_when_context_missing(self):
        self.instance._integration_context = None
        with self.assertRaisesRegex(ValueError, "MISSING_INTEGRATION_CONTEXT"):
            self.run_hook()

    def test_finalization_error_is_not_swallowed(self):
        def rejected(*args, **kwargs):
            raise ValueError("FINAL_CONTRACT_TEST_REJECTION")
        self.namespace["finish"] = rejected
        with self.assertRaisesRegex(ValueError, "FINAL_CONTRACT_TEST_REJECTION"):
            self.run_hook()


if __name__ == "__main__":
    unittest.main()
