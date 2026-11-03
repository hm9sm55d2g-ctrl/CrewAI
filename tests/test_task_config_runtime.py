"""Offline regression tests for task configuration with resolved runtime objects."""
from threading import RLock
from types import SimpleNamespace
import unittest

from analisti_2027.integration import POLICY, task_config


class UncopyableAgent:
    def __deepcopy__(self, memo):
        raise AssertionError("Resolved agents must not be deep-copied")


class TaskConfigRuntimeTests(unittest.TestCase):
    def test_preserves_agent_and_context_identity(self):
        agent = UncopyableAgent()
        context = [SimpleNamespace(lock=RLock())]
        config = {"description": "Validate inputs.", "agent": agent, "context": context}
        result = task_config(config, "validazione")
        self.assertIsNot(result, config)
        self.assertIs(result["agent"], agent)
        self.assertIs(result["context"], context)
        self.assertEqual(config["description"], "Validate inputs.")
        self.assertIn(POLICY, result["description"])
        self.assertIn("{integration_context}", result["description"])

    def test_accepts_rlock_without_copying(self):
        lock = RLock()
        config = {"description": "Validate inputs.", "runtime_lock": lock}
        result = task_config(config, "validazione")
        self.assertIs(result["runtime_lock"], lock)
        self.assertEqual(config["description"], "Validate inputs.")

    def test_rewrites_only_description_without_mutating_input(self):
        cases = {
            "scenari": (
                "Nessun motore finanziario e collegato: non calcolare rendimenti o drawdown.",
                "Se ci sono risultati Q, commentali senza ricalcolarli; altrimenti rendimenti e drawdown ND.",
            ),
            "report": (
                "Non dichiarare rendimenti, probabilita, idoneita personale o raccomandazioni operative. Nessuna acquisizione web o calcolo finanziario.",
                "Non inventare rendimenti: usa solo risultati Q sintetici. Non dichiarare probabilita, idoneita personale o raccomandazioni operative. Nessuna acquisizione web; calcoli solo dal motore deterministico.",
            ),
        }
        for name, (description, expected) in cases.items():
            with self.subTest(name=name):
                agent = UncopyableAgent()
                config = {"description": description, "agent": agent, "expected_output": "Report"}
                result = task_config(config, name)
                self.assertEqual(config["description"], description)
                self.assertEqual(result["description"], expected + "\n" + POLICY + "\nDOSSIER JSON:\n{integration_context}")
                self.assertIs(result["agent"], agent)
                self.assertEqual(result["expected_output"], "Report")


if __name__ == "__main__":
    unittest.main()
