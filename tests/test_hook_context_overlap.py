"""Hook-body overlap protection; dependencies stubbed, not CrewAI/AMP concurrency."""
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
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Analisti2027")
        names = {"prepare_inputs", "validate_final_output"}
        methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in methods}, names)
        for method in methods:
            method.decorator_list = []
        self.ns = {
            "RESOURCE_ROOT": ROOT,
            "prepare": lambda root, bundle: deepcopy(bundle),
            "project_inputs": lambda: {},
            "agent_context": lambda context: context["input_sha256"],
            "bind_report": lambda result, root, as_of: result,
            "finish": lambda result, context, root: (result.raw, context["input_sha256"]),
        }
        exec(compile(ast.Module(body=methods, type_ignores=[]), "crew.py:hooks", "exec"), self.ns)

    def prepare(self, instance, tag):
        return self.ns["prepare_inputs"](instance, {"scenario_bundle": {"input_sha256": tag, "as_of": "2026-11-07"}})

    def finish(self, instance, tag):
        return self.ns["validate_final_output"](instance, SimpleNamespace(raw="report-" + tag))

    def overlap(self, shared):
        first = SimpleNamespace()
        second = first if shared else SimpleNamespace()
        a_ready, b_ready = Event(), Event()
        def run_a():
            self.prepare(first, "A")
            a_ready.set()
            if not b_ready.wait(5):
                raise TimeoutError("B did not attempt prepare")
            return self.finish(first, "A")
        def run_b():
            if not a_ready.wait(5):
                raise TimeoutError("A did not prepare")
            try:
                self.prepare(second, "B")
            except ValueError as exc:
                return str(exc)
            finally:
                b_ready.set()
            return self.finish(second, "B")
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(run_a), pool.submit(run_b)
            return a.result(timeout=10), b.result(timeout=10)

    def test_separate_instances_keep_contexts_isolated(self):
        self.assertEqual(self.overlap(False), (("report-A", "A"), ("report-B", "B")))

    def test_shared_instance_rejects_overlap_without_contaminating_first(self):
        a, b = self.overlap(True)
        self.assertEqual(a, ("report-A", "A"))
        self.assertTrue(b.startswith("CONCURRENT_KICKOFF_NOT_SUPPORTED:"), b)

    def test_sequential_runs_reuse_instance(self):
        instance = SimpleNamespace()
        for tag in ("A", "B"):
            self.prepare(instance, tag)
            self.assertEqual(self.finish(instance, tag), ("report-" + tag, tag))
            self.assertFalse(instance._execution_guard.locked())

    def test_failed_prepare_clears_context_and_releases_guard(self):
        instance = SimpleNamespace(_integration_context={"input_sha256": "old"})
        original = self.ns["prepare"]
        def rejected(*args, **kwargs):
            raise ValueError("TEST_PREPARE_REJECTED")
        self.ns["prepare"] = rejected
        with self.assertRaisesRegex(ValueError, "TEST_PREPARE_REJECTED"):
            self.prepare(instance, "A")
        self.assertIsNone(instance._integration_context)
        self.assertFalse(instance._execution_guard.locked())
        self.ns["prepare"] = original
        self.prepare(instance, "B")
        self.assertEqual(self.finish(instance, "B"), ("report-B", "B"))

    def test_finalization_errors_release_guard(self):
        for stage in ("bind_report", "finish"):
            with self.subTest(stage=stage):
                instance = SimpleNamespace()
                self.prepare(instance, "A")
                original = self.ns[stage]
                def rejected(*args, **kwargs):
                    raise ValueError("TEST_FINALIZATION_REJECTED")
                self.ns[stage] = rejected
                try:
                    with self.assertRaisesRegex(ValueError, "TEST_FINALIZATION_REJECTED"):
                        self.finish(instance, "A")
                finally:
                    self.ns[stage] = original
                self.assertFalse(instance._execution_guard.locked())
                self.prepare(instance, "B")
                self.assertEqual(self.finish(instance, "B"), ("report-B", "B"))

    def test_missing_final_hook_leaves_instance_fail_closed(self):
        instance = SimpleNamespace()
        self.prepare(instance, "A")
        with self.assertRaisesRegex(ValueError, "CONCURRENT_KICKOFF_NOT_SUPPORTED"):
            self.prepare(instance, "B")
        self.assertEqual(instance._integration_context["input_sha256"], "A")
        fresh = SimpleNamespace()
        self.prepare(fresh, "B")
        self.assertEqual(self.finish(fresh, "B"), ("report-B", "B"))


if __name__ == "__main__":
    unittest.main()
