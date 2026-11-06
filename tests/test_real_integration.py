"""Real offline adapter/engine/binder/gate; synthetic report, no CrewAI kickoff."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.object(sys, "path", [str(ROOT / "src"), *sys.path]):
    from analisti_2027 import integration as i
    from analisti_2027 import quality as quality_module
    from analisti_2027.quality import SECTIONS, END, audit
    from analisti_2027.report_contract import bind_report, split_sections, contract_errors


class FixedUTC(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            raise AssertionError("UTC timezone required")
        return datetime(2026, 11, 4, 12, tzinfo=timezone.utc).astimezone(tz)


class RealIntegrationTests(unittest.TestCase):
    def setUp(self):
        for module in (i, quality_module):
            clock = patch.object(module, "datetime", FixedUTC)
            clock.start()
            self.addCleanup(clock.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()
        self.mandate = json.loads((ROOT / "knowledge/mandato.json").read_text(encoding="utf-8"))
        self.write_json("knowledge/mandato.json", self.mandate)
        (self.root / "knowledge/evidenze.txt").write_text("Nessuna evidenza finanziaria reale acquisita.", encoding="utf-8")
        self.bundle = json.loads((ROOT / "knowledge/scenario_bundle.example.json").read_text(encoding="utf-8"))
        raw = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + s + "\nND: fixture sintetica, revisione necessaria." for s in SECTIONS) + "\n\n" + END
        self.draft = SimpleNamespace(raw=raw, pydantic=None, json_dict=None,
            tasks_output=[SimpleNamespace(raw=raw, pydantic=None, json_dict=None)])

    def write_json(self, path, value):
        (self.root / path).write_text(json.dumps(value), encoding="utf-8")

    def execute(self, bundle):
        context = i.prepare(self.root, bundle)
        bound = bind_report(self.draft, self.root, self.root / "binding", as_of=context["as_of"])
        final = i.finish(bound, context, self.root, self.root / "integration")
        return context, bound, final

    def assert_finalization_stages(self, context, bound, final):
        binding_files = list((self.root / "binding").glob("*.json"))
        integration_files = list((self.root / "integration").glob("*.json"))
        self.assertEqual(len(binding_files), 1)
        self.assertEqual(len(integration_files), 1)
        binding = json.loads(binding_files[0].read_text(encoding="utf-8"))
        saved = json.loads(integration_files[0].read_text(encoding="utf-8"))
        self.assertEqual(binding["draft_raw"], self.draft.raw)
        self.assertEqual(binding["final_raw"], bound.raw)
        self.assertEqual(saved["bound_report_before_numeric_table"], bound.raw)
        self.assertEqual(saved["final_report"], final.raw)
        self.assertEqual(saved["context"], context)
        self.assertFalse(saved["financially_validated"])
        before, after = split_sections(bound.raw), split_sections(final.raw)
        self.assertEqual(len(before), 9)
        self.assertEqual(len(after), 9)
        for index in range(9):
            if index != 5:
                self.assertEqual(before[index], after[index])
        self.assertEqual(after[5], i.summary(context))
        self.assertEqual(final.tasks_output[-1].raw, final.raw)
        self.assertEqual(bound.tasks_output[-1].raw, bound.raw)
        self.assertEqual(self.draft.tasks_output[-1].raw, self.draft.raw)
        self.assertIsNot(final, bound)
        self.assertEqual(final.raw.splitlines()[-1], END)
        outcome = audit(final.raw, self.mandate, context["evidence_records"], self.root, as_of=context["as_of"])
        self.assertTrue(outcome["checks_passed"], outcome["errors"])

    def test_flat_path_thirteen_cases_and_final_table(self):
        original = copy.deepcopy(self.bundle)
        context, bound, final = self.execute(self.bundle)
        cases = context["numeric_results"]["H1"]["cases"]
        expected = {p + suffix + "_" + mode for p in "ABC" for suffix in ("", "_no_ShinEtsu") for mode in ("I1", "I2")} | {"cash_I3"}
        self.assertEqual(set(cases), expected)
        for name, case in cases.items():
            with self.subTest(case=name):
                self.assertEqual(Decimal(case["final_value_eur"]), Decimal(3000))
                self.assertEqual(Decimal(case["return_fraction"]), 0)
                self.assertEqual(Decimal(case["max_drawdown_fraction"]), 0)
                self.assertEqual(Decimal(case["fees_eur"]), 0)
        self.assertEqual(split_sections(final.raw)[5], i.summary(context))
        for sid, payload in context["numeric_results"].items():
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(payload["information_start"], "2026-10-27")
            self.assertEqual(payload["temporal_policy"], self.mandate["temporal_policy"])
            self.assertNotIn("information_cutoff", payload)
            for name, c in payload["cases"].items():
                row = "|" + "|".join([sid, name, c["final_value_eur"], c["return_fraction"], c["max_drawdown_fraction"], c["fees_eur"]]) + "|"
                self.assertIn(row, final.raw)
        self.assertEqual(context["as_of"], "2026-11-04")
        self.assertEqual(contract_errors(final.raw, self.mandate, as_of=context["as_of"]), [])
        self.assertTrue(audit(final.raw, self.mandate, [], self.root, as_of=context["as_of"])["checks_passed"])
        self.assertEqual(final.tasks_output[-1].raw, final.raw)
        self.assertNotEqual(bound.raw, final.raw)
        self.assertIn("fixture sintetica", self.draft.raw)
        self.assertEqual(self.bundle, original)
        files = list((self.root / "integration").glob("*.json"))
        self.assertEqual(len(files), 1)
        saved = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(saved["final_report"], final.raw)
        self.assertEqual(saved["context"]["numeric_results"], context["numeric_results"])
        self.assertFalse(saved["financially_validated"])

    def test_three_scenarios_real_engine(self):
        h1 = self.bundle["scenarios"]["H1"]
        for sid in ("H2", "H10"):
            self.bundle["scenarios"][sid] = copy.deepcopy(h1)
        for q in self.bundle["scenarios"]["H2"]["timeline"][-1]["quotes"].values():
            q["price"] = "200"
        for q in self.bundle["scenarios"]["H10"]["timeline"][-1]["quotes"].values():
            q["price"] = "50"
        context, _, final = self.execute(self.bundle)
        self.assertEqual(sum(len(p["cases"]) for p in context["numeric_results"].values()), 39)
        self.assertGreater(Decimal(context["numeric_results"]["H2"]["cases"]["A_I1"]["return_fraction"]), 0)
        shock = context["numeric_results"]["H10"]["cases"]["A_I1"]
        self.assertLess(Decimal(shock["return_fraction"]), 0)
        self.assertGreater(Decimal(shock["max_drawdown_fraction"]), 0)
        self.assertEqual(split_sections(final.raw)[5], i.summary(context))
        self.assertLessEqual(len(final.raw.split()), 800)

    def test_real_fees_reduce_flat_value(self):
        for r in self.bundle["scenarios"]["H1"]["rules"].values():
            r["fixed_fee_eur"] = "1"
        context, _, _ = self.execute(self.bundle)
        case = context["numeric_results"]["H1"]["cases"]["A_I1"]
        self.assertEqual(Decimal(case["fees_eur"]), 4)
        self.assertEqual(Decimal(case["final_value_eur"]), 2996)
        self.assertEqual(Decimal(context["numeric_results"]["H1"]["cases"]["cash_I3"]["final_value_eur"]), 3000)

    def test_real_engine_rejects_missing_quote(self):
        del self.bundle["scenarios"]["H1"]["timeline"][0]["quotes"]["NVDA"]
        with self.assertRaisesRegex(ValueError, "Missing or unsupported quote"):
            i.prepare(self.root, self.bundle)
        self.assertFalse((self.root / "integration").exists())

    def test_real_engine_rejects_wrong_i2_month(self):
        self.bundle["scenarios"]["H1"]["entries"]["I2"][-1] = "2027-12-31"
        with self.assertRaisesRegex(ValueError, "January, February, March"):
            i.prepare(self.root, self.bundle)

    def test_unconfigured_path_real_gates(self):
        original = copy.deepcopy(self.draft)
        context, bound, final = self.execute(None)
        self.assertEqual(context["status"], "not_configured")
        self.assertEqual(context["numeric_results"], {})
        self.assertNotEqual(bound.raw, final.raw)
        self.assertEqual(self.draft, original)
        self.assert_finalization_stages(context, bound, final)
        section = split_sections(final.raw)[5]
        for sid in ("H1", "H2", "H10"):
            self.assertIn(f"- {sid}: ND: scenario non fornito nel bundle; nessun risultato numerico disponibile.", section)
        self.assertIn("ND: simulazione numerica non configurata.", section)
        self.assertNotIn("|Scenario|", section)

    def test_single_scenario_discloses_assumptions_and_missing_ids(self):
        original_bundle = copy.deepcopy(self.bundle)
        original_draft = copy.deepcopy(self.draft)
        context, bound, final = self.execute(self.bundle)
        section = split_sections(final.raw)[5]
        assumptions = " ".join(self.bundle["scenarios"]["H1"]["assumptions"].split())
        self.assertIn(f"- H1: ipotesi fornite: {assumptions}", section)
        self.assertNotIn("- H1: ND:", section)
        for sid in ("H2", "H10"):
            self.assertIn(f"- {sid}: ND: scenario non fornito nel bundle; nessun risultato numerico disponibile.", section)
        self.assertIn("non dimostrano equivalenza economica, assenza di rischio o superiorita di una strategia.", section)
        self.assertEqual(self.bundle, original_bundle)
        self.assertEqual(self.draft, original_draft)
        self.assert_finalization_stages(context, bound, final)

    def test_three_scenarios_disclose_distinct_assumptions(self):
        base = copy.deepcopy(self.bundle["scenarios"]["H1"])
        for sid in ("H1", "H2", "H10"):
            spec = copy.deepcopy(base)
            spec["assumptions"] = f"Fixture sintetica {sid}: prezzi costanti, costi nulli; non una previsione."
            self.bundle["scenarios"][sid] = spec
        context, bound, final = self.execute(self.bundle)
        section = split_sections(final.raw)[5]
        for sid, spec in self.bundle["scenarios"].items():
            self.assertIn(f"- {sid}: ipotesi fornite: {spec['assumptions']}", section)
        self.assertNotIn("scenario non fornito", section)
        self.assertEqual(sum(len(p["cases"]) for p in context["numeric_results"].values()), 39)
        self.assert_finalization_stages(context, bound, final)

    def test_summary_preserves_numeric_rows_and_context(self):
        context = i.prepare(self.root, self.bundle)
        original = copy.deepcopy(context)
        first = i.summary(context)
        self.assertEqual(i.summary(context), first)
        self.assertEqual(context, original)
        actual_rows = [line for line in first.splitlines() if line.startswith("|H")]
        expected_rows = []
        for sid, payload in context["numeric_results"].items():
            for name, case in payload["cases"].items():
                fields = [case[key] for key in ("final_value_eur", "return_fraction", "max_drawdown_fraction", "fees_eur")]
                expected_rows.append("|" + "|".join([sid, name, *("ND" if value is None else str(value) for value in fields)]) + "|")
        self.assertEqual(actual_rows, expected_rows)
        self.assertEqual(len(actual_rows), 13)

    def test_configured_scenario_without_results_discloses_gap(self):
        context = i.prepare(self.root, self.bundle)
        context["numeric_results"] = {}
        original = copy.deepcopy(context)
        text = i.summary(context)
        self.assertIn("- H1: ipotesi fornite:", text)
        self.assertIn("Risultati H1: ND: risultati numerici non disponibili nel contesto.", text)
        self.assertNotIn("- H1: ND: scenario non fornito", text)
        self.assertNotIn("|Scenario|", text)
        self.assertEqual(context, original)

    def test_final_gate_rejects_oversize_report(self):
        context = i.prepare(self.root, self.bundle)
        bound = bind_report(self.draft, self.root, self.root / "binding", as_of=context["as_of"])
        bound.raw = bound.raw.replace("## Obiezioni e criticita della revisione", "## Obiezioni e criticita della revisione\n" + "parola " * 801)
        with self.assertRaisesRegex(ValueError, "WORD_LIMIT_EXCEEDED"):
            i.finish(bound, context, self.root, self.root / "integration")
        self.assertFalse((self.root / "integration").exists())

    def test_real_evidence_gate_rolling_window_and_snapshot(self):
        text = "SYNTHETIC TEST DOCUMENT: revenue 100 USD; not real evidence or human approval."
        (self.root / "knowledge/source.txt").write_text(text, encoding="utf-8")
        record = dict(id="TEST_ONLY", source_url="https://example.org/test-only", publication_date="2026-10-27",
            snapshot_path="knowledge/source.txt", sha256=hashlib.sha256(text.encode()).hexdigest(), excerpt=text,
            company="TEST_ONLY", metric="revenue", period="synthetic period", unit="units", currency="USD",
            reviewer="Synthetic test identity, not a real reviewer", reviewed_on="2026-11-01", value="100", human_verified=True)
        self.write_json("knowledge/evidence_registry.json", [record])
        context, _, final = self.execute(self.bundle)
        self.assertEqual(context["evidence_records"], [record])
        self.assertTrue(audit(final.raw, self.mandate, [record], self.root, as_of=context["as_of"])["checks_passed"])
        for publication in ("2026-10-28", context["as_of"]):
            with self.subTest(accepted_publication=publication):
                record["publication_date"] = publication
                record["reviewed_on"] = context["as_of"]
                self.write_json("knowledge/evidence_registry.json", [record])
                accepted = i.prepare(self.root, self.bundle)
                self.assertTrue(accepted["preflight"]["checks_passed"])
                self.assertEqual(accepted["evidence_records"], [record])
        future = (datetime.fromisoformat(context["as_of"]) + timedelta(days=1)).date().isoformat()
        for publication in ("2026-10-26", future):
            with self.subTest(rejected_publication=publication):
                record["publication_date"] = publication
                record["reviewed_on"] = publication
                self.write_json("knowledge/evidence_registry.json", [record])
                with self.assertRaisesRegex(ValueError, "INVALID_EVIDENCE_RECORD"):
                    i.prepare(self.root, self.bundle)
        record["publication_date"] = "2026-10-28"
        record["reviewed_on"] = context["as_of"]
        self.write_json("knowledge/evidence_registry.json", [record])
        self.assertTrue(i.prepare(self.root, self.bundle)["preflight"]["checks_passed"])
        (self.root / "knowledge/source.txt").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "INVALID_EVIDENCE_RECORD"):
            i.prepare(self.root, self.bundle)

if __name__ == "__main__":
    unittest.main()
