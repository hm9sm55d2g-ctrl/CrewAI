"""Adapter unit tests; injected audit/engine, no LLM or live financial data."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "src/analisti_2027/integration.py"
spec = importlib.util.spec_from_file_location("analisti_2027._integration_unit", MODULE)
i = importlib.util.module_from_spec(spec)
spec.loader.exec_module(i)

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()
        (self.root / "knowledge/mandato.json").write_text(json.dumps({"capital_eur":3000}), encoding="utf-8")
        self.calls = []
        self.bundle = {"data_kind":"synthetic", "scenarios":{"H1":{
            "assumptions":"Test fixture only; no real prices or costs.",
            "timeline":[{"date":"2027-01-04"}], "entries":{}, "rules":{}}}}

    def checker(self, *args):
        return {"checks_passed":True, "errors":[]}

    def engine(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"cases":{"cash_I3":{"final_value_eur":"3000", "return_fraction":"0", "max_drawdown_fraction":"0", "fees_eur":"0"}}}

    def run_prepare(self, bundle=None, checker=None):
        return i.prepare(self.root, bundle, audit_fn=checker or self.checker, compare_fn=self.engine)

    def test_missing_bundle_no_engine(self):
        c = self.run_prepare()
        self.assertEqual(c["status"], "not_configured")
        self.assertEqual(self.calls, [])
        self.assertIn("non configurata", i.summary(c))

    def test_explicit_bundle_engine_called_once(self):
        c = self.run_prepare(self.bundle)
        self.assertEqual(c["status"], "computed_synthetic")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][1], {"data_kind":"synthetic"})

    def test_json_input(self):
        self.assertEqual(self.run_prepare(json.dumps(self.bundle))["status"], "computed_synthetic")

    def test_file_input(self):
        (self.root / "knowledge/scenario_bundle.json").write_text(json.dumps(self.bundle), encoding="utf-8")
        self.assertEqual(self.run_prepare()["status"], "computed_synthetic")

    def test_preflight_failure_stops_engine(self):
        with self.assertRaisesRegex(ValueError, "INTEGRATION_PREFLIGHT_FAILED"):
            self.run_prepare(self.bundle, lambda *a:{"checks_passed":False, "errors":["INVALID_EVIDENCE_RECORD"]})
        self.assertEqual(self.calls, [])

    def test_real_data_label_rejected(self):
        self.bundle["data_kind"] = "real"
        with self.assertRaises(ValueError): self.run_prepare(self.bundle)

    def test_unknown_scenario_rejected(self):
        self.bundle["scenarios"]["winner"] = self.bundle["scenarios"].pop("H1")
        with self.assertRaises(ValueError): self.run_prepare(self.bundle)

    def test_missing_assumptions_rejected(self):
        self.bundle["scenarios"]["H1"]["assumptions"] = " "
        with self.assertRaises(ValueError): self.run_prepare(self.bundle)

    def test_bounded_timeline(self):
        self.bundle["scenarios"]["H1"]["timeline"] *= 367
        with self.assertRaises(ValueError): self.run_prepare(self.bundle)

    def test_input_not_mutated_and_hash_changes(self):
        original = copy.deepcopy(self.bundle)
        c = self.run_prepare(self.bundle)
        self.assertEqual(original, self.bundle)
        self.bundle["scenarios"]["H1"]["assumptions"] += " changed"
        self.assertNotEqual(c["input_sha256"], self.run_prepare(self.bundle)["input_sha256"])

    def test_all_task_configs_get_direct_context(self):
        original = {"description":"Original description", "agent":"report"}
        for name in ("validazione", "tecnologia", "materiali", "scenari", "revisione", "report"):
            self.assertIn("{integration_context}", i.task_config(original, name)["description"])
        self.assertEqual(original["description"], "Original description")

    def test_numeric_summary_and_no_certification(self):
        c = self.run_prepare(self.bundle)
        self.assertIn("|H1|cash_I3|3000|0|0|0|", i.summary(c))
        dossier = json.loads(i.agent_context(c))
        self.assertFalse(dossier["financially_validated"])
        self.assertEqual(dossier["evidence_records"], [])

if __name__ == "__main__":
    unittest.main()
