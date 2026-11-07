"""Hook-body isolation tests, not concurrent CrewAI kickoff or AMP tests.
Shared-instance isolation is a known defect, explicitly marked expectedFailure.
Dependencies are stubbed; hook bodies are extracted from production crew.py.
"""
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HookContextOverlapTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "src/analisti_2027/crew.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Analisti2027")
        names = {"prepare_inputs", "validate_final_output"}
        methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in methods}, names)
        for method in methods:
            method.decorator_list = []
        self.ns = {
            "RESOURCE_ROOT": ROOT,
            "prepare": lambda root, bundle: deepcopy(bundle),
            "project_inputs": lambda: {},
            "agent_context": lambda context: context["input_sha256"],
            "bind_report": lambda result, root, as_of: result,
            "finish": lambda result, context, root: (result.raw, context["input_sha256"], context["as_of"]),
        }
        exec(compile(ast.Module(body=methods, type_ignores=[]), "crew.py:hooks", "exec"), self.ns)

    def overlap(self, shared):
        first = SimpleNamespace()
        second = first if shared else SimpleNamespace()
        a_ready, b_ready = Event(), Event()
        def run_a():
            self.ns["prepare_inputs"](first, {"scenario_bundle": {"input_sha256": "A", "as_of": "2026-11-06"}})
            a_ready.set()
            if not b_ready.wait(5):
                raise TimeoutError("B did not prepare")
            return self.ns["validate_final_output"](first, SimpleNamespace(raw="report-A"))
        def run_b():
            if not a_ready.wait(5):
                raise TimeoutError("A did not prepare")
            try:
                self.ns["prepare_inputs"](second, {"scenario_bundle": {"input_sha256": "B", "as_of": "2026-11-07"}})
            finally:
                b_ready.set()
            return self.ns["validate_final_output"](second, SimpleNamespace(raw="report-B"))
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(run_a), pool.submit(run_b)
            return a.result(timeout=10), b.result(timeout=10)

    def test_separate_instances_keep_contexts_isolated(self):
        a, b = self.overlap(shared=False)
        self.assertEqual(a, ("report-A", "A", "2026-11-06"))
        self.assertEqual(b, ("report-B", "B", "2026-11-07"))

    @unittest.expectedFailure
    def test_shared_instance_should_keep_contexts_isolated(self):
        a, b = self.overlap(shared=True)
        self.assertEqual(a, ("report-A", "A", "2026-11-06"))
        self.assertEqual(b, ("report-B", "B", "2026-11-07"))

    def test_failed_prepare_clears_previous_context(self):
        instance = SimpleNamespace(_integration_context={"input_sha256": "old"})
        def rejected(*args):
            raise ValueError("TEST_PREPARE_REJECTED")
        self.ns["prepare"] = rejected
        with self.assertRaisesRegex(ValueError, "TEST_PREPARE_REJECTED"):
            self.ns["prepare_inputs"](instance, {})
        self.assertIsNone(instance._integration_context)
        with self.assertRaisesRegex(ValueError, "MISSING_INTEGRATION_CONTEXT"):
            self.ns["validate_final_output"](instance, SimpleNamespace(raw="report"))


if __name__ == "__main__":
    unittest.main()
