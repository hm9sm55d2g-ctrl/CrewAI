"""Deterministic offline temporal tests: no provider API, LLM or network."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from analisti_2027 import integration as i
from analisti_2027 import quality as q
from analisti_2027 import report_contract as r


class Clock(datetime):
    instant = datetime(2026, 11, 4, 23, 59, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            raise AssertionError("UTC timezone required")
        return cls.instant.astimezone(tz)


class RollingWindowTests(unittest.TestCase):
    def setUp(self):
        Clock.instant = datetime(2026, 11, 4, 23, 59, tzinfo=timezone.utc)
        for module in (q, i):
            clock = patch.object(module, "datetime", Clock)
            clock.start()
            self.addCleanup(clock.stop)
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / "knowledge").mkdir()
        self.day = "2026-11-04"
        self.m = {"capital_eur": 3000, "information_start": "2026-10-27",
                  "temporal_policy": {"mode": "rolling", "start_inclusive": True,
                      "end": "execution_date", "timezone": "UTC",
                      "documents_date_field": "publication_date",
                      "market_data_date_field": "observation_date"},
                  "portfolios": {k: dict(zip(r.ASSETS, [600]*5)) for k in "ABC"}}
        data = b"SYNTHETIC TEST ONLY: value 10 EUR."
        (self.root / "snapshot.txt").write_bytes(data)
        self.e = {"id": "TEST", "source_url": "https://example.invalid/test",
                  "publication_date": "2026-10-27", "snapshot_path": "snapshot.txt",
                  "sha256": hashlib.sha256(data).hexdigest(), "excerpt": "value 10 EUR",
                  "company": "TEST", "metric": "fixture", "period": "2025 annual",
                  "unit": "EUR", "currency": "EUR", "value": 10,
                  "reviewer": "test fixture only", "reviewed_on": self.day,
                  "human_verified": True}
        self.report = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join(
            "## " + s + "\nND: dati non acquisiti." for s in q.SECTIONS) + "\n" + q.END
        self.save_inputs([])

    def save_inputs(self, records):
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.m), encoding="utf-8")
        (self.root / "knowledge/evidence_registry.json").write_text(json.dumps(records), encoding="utf-8")
        (self.root / "knowledge/evidenze.txt").write_text("Nessuna evidenza acquisita.", encoding="utf-8")

    def audit(self, **changes):
        return q.audit(self.report, self.m, [dict(self.e, **changes)], self.root, as_of=self.day)

    def test_document_bounds_inclusive(self):
        for day in ("2026-10-27", self.day):
            with self.subTest(day=day):
                self.assertTrue(self.audit(publication_date=day)["checks_passed"])

    def test_document_outside_window_rejected(self):
        for day in ("2026-10-26", "2026-11-05"):
            self.assertIn("INVALID_EVIDENCE_RECORD", self.audit(publication_date=day)["errors"])

    def test_invalid_or_missing_dates_rejected(self):
        for day in ("2026-02-30", "20261027", "", None):
            self.assertFalse(self.audit(publication_date=day)["checks_passed"])
        record = dict(self.e)
        del record["publication_date"]
        self.assertFalse(q.audit(self.report, self.m, [record], self.root, as_of=self.day)["checks_passed"])

    def test_prior_economic_period_allowed(self):
        self.assertTrue(self.audit(period="2025 annual")["checks_passed"])

    def test_market_observation_bounds(self):
        for kind in ("price", "fx"):
            for day, expected in (("2026-10-26", False), ("2026-10-27", True),
                                  (self.day, True), ("2026-11-05", False)):
                with self.subTest(kind=kind, day=day):
                    result = self.audit(record_type=kind, observation_date=day, publication_date=self.day)
                    self.assertEqual(result["checks_passed"], expected)

    def test_market_requires_observation_and_available_source(self):
        for kind in ("price", "fx"):
            self.assertFalse(self.audit(record_type=kind)["checks_passed"])
            self.assertFalse(self.audit(record_type=kind, observation_date=self.day)["checks_passed"])
            self.assertFalse(self.audit(record_type=kind, observation_date=self.day,
                                        publication_date="2026-11-05")["checks_passed"])
        self.assertFalse(self.audit(record_type="other")["checks_passed"])

    def test_acquisition_and_review_dates(self):
        for field in ("acquisition_date", "reviewed_on"):
            for day in ("2026-10-26", "2026-11-05", "invalid"):
                self.assertFalse(self.audit(**{field: day})["checks_passed"])
        self.assertTrue(self.audit(acquisition_date=self.day)["checks_passed"])

    def test_invalid_policies_and_future_reference(self):
        for field, value in (("mode", "unknown"), ("start_inclusive", False),
                             ("timezone", "Europe/Rome"), ("end", "tomorrow")):
            original = self.m["temporal_policy"][field]
            self.m["temporal_policy"][field] = value
            self.assertFalse(self.audit()["checks_passed"])
            self.m["temporal_policy"][field] = original
        self.m["information_cutoff"] = self.day
        self.assertFalse(self.audit()["checks_passed"])
        del self.m["information_cutoff"]
        with self.assertRaisesRegex(ValueError, "FUTURE_REFERENCE_DATE"):
            q.evidence_window(self.m, "2026-11-05")
        self.m["information_start"] = "2026-11-05"
        self.assertFalse(self.audit()["checks_passed"])

    def test_legacy_frozen_mandate(self):
        self.m.pop("information_start")
        self.m.pop("temporal_policy")
        self.m["information_cutoff"] = "2026-10-27"
        self.assertTrue(self.audit()["checks_passed"])
        self.assertFalse(self.audit(publication_date="2026-10-28")["checks_passed"])

    def test_existing_evidence_safeguards(self):
        for change in ({"human_verified": False}, {"sha256": "bad"},
                       {"source_url": "http://example.invalid"}, {"snapshot_path": "../bad"},
                       {"excerpt": "not in snapshot"}):
            self.assertFalse(self.audit(**change)["checks_passed"])
        self.m["portfolios"]["A"]["cash"] = 601
        self.assertFalse(self.audit()["checks_passed"])

    def test_prepare_exposes_pinned_window_and_hash(self):
        context = i.prepare(self.root)
        self.assertEqual(context["as_of"], self.day)
        self.assertEqual(context["preflight"]["temporal_window"], context["temporal_window"])
        dossier = json.loads(i.agent_context(context))
        self.assertEqual(dossier["temporal_window"], context["temporal_window"])
        self.assertFalse(dossier["financially_validated"])
        Clock.instant = datetime(2026, 11, 5, tzinfo=timezone.utc)
        self.assertNotEqual(context["input_sha256"], i.prepare(self.root)["input_sha256"])

    def test_future_record_stops_prepare(self):
        self.save_inputs([dict(self.e, publication_date="2026-11-05")])
        with self.assertRaisesRegex(ValueError, "INTEGRATION_PREFLIGHT_FAILED"):
            i.prepare(self.root)

    def test_report_and_final_audit_keep_date_across_midnight(self):
        context = i.prepare(self.root)
        Clock.instant = datetime(2026, 11, 5, tzinfo=timezone.utc)
        original = SimpleNamespace(raw=self.report)
        bound = r.bind_report(original, self.root, self.root / "reports", as_of=context["as_of"])
        final = i.finish(bound, context, self.root, self.root / "audits")
        self.assertEqual(original.raw, self.report)
        self.assertIn("dal 2026-10-27 al 2026-11-04", final.raw)
        binding = json.loads(next((self.root / "reports").glob("*.json")).read_text())
        for key in ("draft_audit", "final_audit"):
            self.assertEqual(binding[key]["temporal_window"]["end"], self.day)
            self.assertTrue(binding[key]["checks_passed"])
        saved = json.loads(next((self.root / "audits").glob("*.json")).read_text())
        self.assertEqual(saved["context"]["as_of"], self.day)
        with patch.object(q, "audit", wraps=q.audit) as spy:
            i.finish(bound, context, self.root, self.root / "audits")
            self.assertEqual(spy.call_args.kwargs["as_of"], self.day)

    def test_new_day_evidence_not_admitted_to_old_run(self):
        context = i.prepare(self.root)
        Clock.instant = datetime(2026, 11, 5, tzinfo=timezone.utc)
        self.save_inputs([dict(self.e, publication_date="2026-11-05", reviewed_on="2026-11-05")])
        with self.assertRaisesRegex(ValueError, "DRAFT_STRUCTURE_FAILED"):
            r.bind_report(SimpleNamespace(raw=self.report), self.root, self.root / "reports", as_of=context["as_of"])

    def test_task_config_preserves_runtime_agent_identity(self):
        agent = object()
        config = {"description": "Test", "agent": agent}
        self.assertIs(i.task_config(config, "validazione")["agent"], agent)
        self.assertEqual(config["description"], "Test")


if __name__ == "__main__":
    unittest.main()
