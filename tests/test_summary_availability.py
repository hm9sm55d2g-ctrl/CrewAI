"""Regression tests for scenario availability wording; no CrewAI or network."""
from copy import deepcopy
import unittest

from analisti_2027.integration import summary


class SummaryAvailabilityTests(unittest.TestCase):
    def test_no_bundle_is_unconfigured(self):
        context = {"scenario_bundle": None, "numeric_results": {}}
        before = deepcopy(context)
        text = summary(context)
        self.assertIn("ND: simulazione numerica non configurata.", text)
        self.assertNotIn("ND: risultati numerici non disponibili per gli scenari forniti.", text)
        for sid in ("H1", "H2", "H10"):
            self.assertIn(f"- {sid}: ND: scenario non fornito nel bundle; nessun risultato numerico disponibile.", text)
        self.assertNotIn("|Scenario|", text)
        self.assertEqual(context, before)

    def test_provided_scenario_without_results_is_not_unconfigured(self):
        context = {
            "scenario_bundle": {"scenarios": {"H1": {"assumptions": "Fixture sintetica H1."}}},
            "numeric_results": {},
        }
        before = deepcopy(context)
        text = summary(context)
        self.assertIn("- H1: ipotesi fornite: Fixture sintetica H1.", text)
        self.assertIn("Risultati H1: ND: risultati numerici non disponibili nel contesto.", text)
        self.assertIn("ND: risultati numerici non disponibili per gli scenari forniti.", text)
        self.assertNotIn("simulazione numerica non configurata", text)
        self.assertNotIn("- H1: ND: scenario non fornito", text)
        self.assertNotIn("|Scenario|", text)
        self.assertEqual(context, before)

    def test_numeric_rows_remain_exact_and_context_unchanged(self):
        context = {
            "scenario_bundle": {"scenarios": {"H1": {"assumptions": "Fixture sintetica H1."}}},
            "numeric_results": {"H1": {"cases": {"A_I1": {
                "final_value_eur": "2996", "return_fraction": "-0.0013333333",
                "max_drawdown_fraction": "0.0013333333", "fees_eur": "4",
            }}}},
        }
        before = deepcopy(context)
        text = summary(context)
        rows = [line for line in text.splitlines() if line.startswith("|H")]
        self.assertEqual(rows, ["|H1|A_I1|2996|-0.0013333333|0.0013333333|4|"])
        self.assertNotIn("ND: simulazione numerica non configurata.", text)
        self.assertNotIn("ND: risultati numerici non disponibili per gli scenari forniti.", text)
        self.assertEqual(context, before)


if __name__ == "__main__":
    unittest.main()
