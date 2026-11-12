"""Targeted offline integration checks for dual-channel audits; no CrewAI/AMP kickoff."""
import contextlib
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from analisti_2027 import quality as q, report_contract as c, integration as i

class FixedUTC(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 10, 12, tzinfo=timezone.utc).astimezone(tz)

class AuditModuleIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "knowledge").mkdir()
        self.mandate = {
            "capital_eur": 3000, "information_start": "2026-10-27",
            "temporal_policy": {"mode": "rolling", "start_inclusive": True,
                "end": "execution_date", "timezone": "UTC",
                "documents_date_field": "publication_date", "market_data_date_field": "observation_date"},
            "portfolios": {
                "A": dict(AVGO=750, NVDA=600, AMZN=600, ShinEtsu=450, cash=600),
                "B": dict(AVGO=900, NVDA=750, AMZN=750, ShinEtsu=600, cash=0),
                "C": dict(AVGO=600, NVDA=450, AMZN=450, ShinEtsu=300, cash=1200)}}
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.mandate), encoding="utf-8")
        (self.root / "knowledge/evidence_registry.json").write_text("[]", encoding="utf-8")
        (self.root / "knowledge/evidenze.txt").write_text("Riferimento non acquisito: https://example.org/reference", encoding="utf-8")
        raw = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join(
            "## " + title + "\nND: fixture sintetica senza evidenze verificate." for title in q.SECTIONS
        ) + "\n\n" + q.END
        self.draft = SimpleNamespace(raw=raw, pydantic=None, json_dict=None,
            tasks_output=[SimpleNamespace(raw=raw, pydantic=None, json_dict=None)])
        for module in (q, i):
            clock = patch.object(module, "datetime", FixedUTC)
            clock.start()
            self.addCleanup(clock.stop)

    def pipeline(self, bundle=None, compare_fn=None):
        context = i.prepare(self.root, bundle, compare_fn=compare_fn)
        bound = c.bind_report(self.draft, self.root, self.root / "binding", as_of=context["as_of"])
        final = i.finish(bound, context, self.root, self.root / "integration")
        return context, bound, final

    def assert_channels(self, stdout, captured, expected):
        lines = stdout.getvalue().splitlines()
        self.assertEqual([line.split(" ", 1)[0] for line in lines], expected)
        self.assertEqual(lines, [record.getMessage() for record in captured.records])
        self.assertTrue(all(record.levelname == "WARNING" for record in captured.records))
        return [json.loads(line.split(" ", 1)[1]) for line in lines]

    def test_success_channels_hash_and_artifacts(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                context, bound, final = self.pipeline()
        payloads = self.assert_channels(out, captured, ["REPORT_BINDING_AUDIT", "QUALITY_AUDIT", "INTEGRATION_AUDIT"])
        audit = payloads[1]
        self.assertTrue(audit["checks_passed"])
        self.assertFalse(audit["financially_validated"])
        self.assertEqual(audit["report_sha256"], hashlib.sha256(final.raw.encode("utf-8")).hexdigest())
        self.assertEqual(audit["temporal_window"]["end"], "2026-11-10")
        saved = json.loads(Path(payloads[2]["artifact"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["final_report"], final.raw)
        self.assertEqual(saved["bound_report_before_numeric_table"], bound.raw)
        self.assertEqual(saved["context"], context)
        binding = json.loads(Path(payloads[0]["artifact"]).read_text(encoding="utf-8"))
        self.assertEqual(binding["draft_raw"], self.draft.raw)
        self.assertEqual(binding["final_raw"], bound.raw)

    def test_original_objects_and_other_eight_sections_unchanged(self):
        original = copy.deepcopy(self.draft)
        with contextlib.redirect_stdout(io.StringIO()), self.assertLogs("analisti_2027.audit", level="WARNING"):
            context, bound, final = self.pipeline()
        self.assertEqual(self.draft, original)
        self.assertIsNot(final, bound)
        self.assertEqual(final.tasks_output[-1].raw, final.raw)
        self.assertEqual(bound.tasks_output[-1].raw, bound.raw)
        before, after = c.split_sections(bound.raw), c.split_sections(final.raw)
        self.assertEqual([j for j in range(9) if before[j] != after[j]], [5])
        self.assertEqual(after[5], i.summary(context))
        self.assertEqual(c.contract_errors(final.raw, self.mandate, as_of=context["as_of"]), [])

    def test_invalid_draft_logged_before_rejection(self):
        self.draft.raw = self.draft.raw.replace("# ANALISI PRELIMINARE NON VALIDATA", "# INVALID", 1)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                with self.assertRaisesRegex(ValueError, "DRAFT_STRUCTURE_FAILED: INVALID_REPORT_TITLE"):
                    self.pipeline()
        payloads = self.assert_channels(out, captured, ["REPORT_BINDING_AUDIT"])
        self.assertEqual(payloads[0]["status"], "draft_rejected")
        self.assertIn("INVALID_REPORT_TITLE", payloads[0]["errors"])
        self.assertFalse((self.root / "integration").exists())
        diagnostic = json.loads(Path(payloads[0]["artifact"]).read_text())
        self.assertIsNone(diagnostic["final_raw"])

    def test_final_gate_rejection_logs_failed_quality_and_no_final_artifact(self):
        context = i.prepare(self.root)
        with contextlib.redirect_stdout(io.StringIO()), self.assertLogs("analisti_2027.audit", level="WARNING"):
            bound = c.bind_report(self.draft, self.root, self.root / "binding", as_of=context["as_of"])
        bound.raw = bound.raw.replace("## Obiezioni e criticita della revisione", "## Obiezioni e criticita della revisione\n" + "parola " * 801)
        original = copy.deepcopy(bound)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                with self.assertRaisesRegex(ValueError, "QUALITY_GATE_FAILED: WORD_LIMIT_EXCEEDED"):
                    i.finish(bound, context, self.root, self.root / "integration")
        payloads = self.assert_channels(out, captured, ["QUALITY_AUDIT"])
        self.assertFalse(payloads[0]["checks_passed"])
        self.assertFalse((self.root / "integration").exists())
        self.assertEqual(bound, original)

    def test_direct_quality_returns_same_object_without_modification(self):
        original = copy.deepcopy(self.draft)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                returned = q.check_output(self.draft, self.root, as_of="2026-11-10")
        payloads = self.assert_channels(out, captured, ["QUALITY_AUDIT"])
        self.assertIs(returned, self.draft)
        self.assertEqual(returned, original)
        self.assertEqual(payloads[0]["report_sha256"], hashlib.sha256(original.raw.encode()).hexdigest())

    def test_injected_numeric_payload_preserved_thirteen_rows(self):
        names = [p + suffix + "_" + mode for p in "ABC" for suffix in ("", "_no_ShinEtsu") for mode in ("I1", "I2")] + ["cash_I3"]
        cases = {name: dict(final_value_eur="3000", return_fraction="0", max_drawdown_fraction="0", fees_eur="0") for name in names}
        payload = {"cases": cases}
        bundle = {"data_kind": "synthetic", "scenarios": {"H1": {
            "assumptions": "Test-only injected engine output, not financial validation.",
            "timeline": [{"date": "2027-01-04"}], "entries": {}, "rules": {}}}}
        original = copy.deepcopy(bundle)
        def engine(*args, **kwargs):
            return copy.deepcopy(payload)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                context, bound, final = self.pipeline(bundle, compare_fn=engine)
        records = self.assert_channels(out, captured, ["REPORT_BINDING_AUDIT", "QUALITY_AUDIT", "INTEGRATION_AUDIT"])
        section = c.split_sections(final.raw)[5]
        self.assertEqual(len([line for line in section.splitlines() if line.startswith("|H1|")]), 13)
        self.assertEqual(context["numeric_results"]["H1"], payload)
        self.assertEqual(bundle, original)
        self.assertIn("- H2: ND: scenario non fornito", section)
        self.assertIn("- H10: ND: scenario non fornito", section)
        self.assertEqual(records[1]["report_sha256"], hashlib.sha256(final.raw.encode()).hexdigest())

    def test_silencing_emitter_does_not_change_final_report(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertLogs("analisti_2027.audit", level="WARNING"):
            _, _, logged = self.pipeline()
        with patch.object(q, "emit_audit"), patch.object(c, "emit_audit"), patch.object(i, "emit_audit"):
            _, _, silent = self.pipeline()
        self.assertEqual(logged.raw, silent.raw)
        self.assertEqual(logged.tasks_output, silent.tasks_output)

    def test_invalid_mandate_preflight_stops_before_audits(self):
        self.mandate["capital_eur"] = 999
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.mandate))
        with patch("analisti_2027.audit_logging.LOGGER.warning") as warning:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertRaisesRegex(ValueError, "INTEGRATION_PREFLIGHT_FAILED"):
                    self.pipeline()
        warning.assert_not_called()
        self.assertEqual(out.getvalue(), "")
        self.assertFalse((self.root / "binding").exists())

    def test_repeated_runs_have_distinct_artifacts_and_correct_hashes(self):
        artifacts = []
        for number in range(2):
            self.draft.raw = self.draft.raw.replace("revisione aggiuntiva", "revisione") if number == 0 else self.draft.raw.replace("fixture sintetica", "fixture sintetica revisione aggiuntiva")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                    _, _, final = self.pipeline()
            records = self.assert_channels(out, captured, ["REPORT_BINDING_AUDIT", "QUALITY_AUDIT", "INTEGRATION_AUDIT"])
            self.assertEqual(records[1]["report_sha256"], hashlib.sha256(final.raw.encode()).hexdigest())
            artifacts.append(records[2]["artifact"])
        self.assertNotEqual(artifacts[0], artifacts[1])
        self.assertEqual(len(list((self.root / "integration").glob("*.json"))), 2)

    def test_structured_output_still_rejected(self):
        self.draft.json_dict = {"unexpected": "structured"}
        with patch("analisti_2027.audit_logging.LOGGER.warning") as warning:
            with self.assertRaisesRegex(ValueError, "STRUCTURED_CREW_OUTPUT_NOT_SUPPORTED_BY_BINDER"):
                self.pipeline()
        warning.assert_not_called()

if __name__ == "__main__":
    unittest.main()
