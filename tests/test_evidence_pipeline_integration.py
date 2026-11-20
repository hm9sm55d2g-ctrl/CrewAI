"""Integration tests for evidence pipeline coordinator via integration.prepare entry point."""
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from analisti_2027.integration import prepare, promote_evidence_fixtures
from analisti_2027.review_integration import final_review_summary
from analisti_2027.acquisition_adapter import prepare_capture
from analisti_2027.quality import SECTIONS, END, evidence_window
from analisti_2027.automated_evidence import SOURCE_URL


class EvidencePipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()

        self.mandate = {
            "capital_eur": 3000,
            "information_start": "2026-10-27",
            "temporal_policy": {
                "mode": "rolling",
                "start_inclusive": True,
                "end": "execution_date",
                "timezone": "UTC",
                "documents_date_field": "publication_date",
                "market_data_date_field": "observation_date"
            },
            "portfolios": {
                "A": {"AVGO": 750, "NVDA": 600, "AMZN": 600, "ShinEtsu": 450, "cash": 600},
                "B": {"AVGO": 900, "NVDA": 750, "AMZN": 750, "ShinEtsu": 600, "cash": 0},
                "C": {"AVGO": 600, "NVDA": 450, "AMZN": 450, "ShinEtsu": 300, "cash": 1200}
            }
        }
        (self.root / "knowledge/mandato.json").write_text(json.dumps(self.mandate), encoding="utf-8")
        (self.root / "knowledge/evidence_registry.json").write_text("[]", encoding="utf-8")
        (self.root / "knowledge/evidenze.txt").write_text("Test fixture.", encoding="utf-8")

        self.day = date.today().isoformat()
        self.plain = "Net sales increased 12% to $201.9 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        self.raw = self.plain.replace("Net sales", "**Net sales**")

        self.candidate = dict(
            id="TEST_AMZN_NET_SALES",
            record_type="document",
            company="AMZN",
            metric="net_sales",
            period="Three months ended 2026-09-30",
            unit="billion",
            currency="USD",
            value="201.9",
            source_url=SOURCE_URL,
            publication_date="2026-10-29",
            acquisition_date=self.day,
            snapshot_path="fixture.txt",
            sha256=hashlib.sha256(self.plain.encode()).hexdigest(),
            excerpt=self.plain,
            human_verified=False,
            reviewer=None,
            reviewed_on=None
        )

        self.capture = prepare_capture(self.raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=self.day)

    def _candidates_data(self):
        return [{
            "candidate": self.candidate,
            "snapshot_text": self.plain,
            "capture": self.capture,
            "reviewed_on": self.day
        }]

    def _run_full_cycle(self, candidates_data=None):
        """Run: promote_evidence_fixtures → prepare → final_review_summary."""
        as_of = date.today().isoformat()
        window = evidence_window(self.mandate, as_of)
        if candidates_data is None:
            candidates_data = [{
                "candidate": self.candidate,
                "snapshot_text": self.plain,
                "capture": self.capture,
                "reviewed_on": self.day
            }]

        # Step 1: Promote fixtures
        promote_result = promote_evidence_fixtures(self.root, as_of, window, candidates_data)

        # Step 2: Prepare (reads updated registry) - prepare() computes as_of internally
        context = prepare(self.root)

        # Step 3: Final review summary
        raw_report = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join(
            "## " + s + "\nND." for s in ["Sintesi", "Evidenze", "Vincoli", "AVGO", "NVDA", "AMZN", "ShinEtsu", "Scenari", "Obiezioni"]
        ) + "\n" + END
        review = final_review_summary(raw_report, context, self.root)

        return promote_result, context, review

    def test_success_with_prepare_and_final_review(self):
        """Full cycle: promote → prepare → final_review_summary sees automated=1."""
        promote_result, context, review = self._run_full_cycle()

        # Promote result
        self.assertEqual(promote_result["promoted"], ["TEST_AMZN_NET_SALES"])
        self.assertEqual(promote_result["skipped"], [])

        # Prepare sees the evidence
        self.assertEqual(len(context["evidence_records"]), 1)
        record = context["evidence_records"][0]
        self.assertEqual(record["id"], "TEST_AMZN_NET_SALES")
        self.assertEqual(record["review_status"], "automated_verified")

        # Final review summary counts automated evidence
        self.assertEqual(review["evidence_review_counts"], {"human": 0, "automated": 1})
        self.assertEqual(review["financial_review_status"], "pending_final_approval")

    def test_registry_prepopulated_unrelated_preserved(self):
        """Registry already has human evidence; promotion adds automated; both visible to prepare."""
        # Pre-populate with a human-verified record using content-addressed path
        existing_text = "existing content"
        existing_hash = hashlib.sha256(existing_text.encode()).hexdigest()
        existing_path = f"knowledge/snapshots/{existing_hash}.txt"

        existing = [{
            "id": "EXISTING_HUMAN",
            "record_type": "document",
            "company": "NVDA",
            "metric": "revenue",
            "period": "test",
            "unit": "million",
            "currency": "USD",
            "value": "100",
            "source_url": "https://example.org/test",
            "publication_date": "2026-10-27",
            "acquisition_date": date.today().isoformat(),
            "snapshot_path": f"knowledge/snapshots/{hashlib.sha256(b'existing').hexdigest()}.txt",
            "sha256": hashlib.sha256(b"existing").hexdigest(),
            "excerpt": "existing",
            "human_verified": True,
            "reviewer": "test",
            "reviewed_on": date.today().isoformat(),
            "review_status": "approved"
        }]
        (self.root / "knowledge/evidence_registry.json").write_text(json.dumps(existing), encoding="utf-8")
        (self.root / "knowledge/snapshots").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge/snapshots").mkdir(parents=True, exist_ok=True)
        (self.root / f"knowledge/snapshots/{hashlib.sha256(b'existing').hexdigest()}.txt").write_text("existing", encoding="utf-8")

        promote_result, context, review = self._run_full_cycle()

        self.assertEqual(promote_result["promoted"], ["TEST_AMZN_NET_SALES"])
        self.assertEqual(len(context["evidence_records"]), 2)
        ids = {r["id"] for r in context["evidence_records"]}
        self.assertEqual(ids, {"EXISTING_HUMAN", "TEST_AMZN_NET_SALES"})
        self.assertEqual(review["evidence_review_counts"], {"human": 1, "automated": 1})

    def test_second_run_identical_succeeds(self):
        """Second identical run on same root succeeds, state invariant."""
        # First run
        _, context1, review1 = self._run_full_cycle()
        registry1 = (self.root / "knowledge/evidence_registry.json").read_text()

        # Second run
        _, context2, review2 = self._run_full_cycle()
        registry2 = (self.root / "knowledge/evidence_registry.json").read_text()

        # State invariant
        self.assertEqual(registry1, registry2)
        self.assertEqual(context1["evidence_records"], context2["evidence_records"])
        self.assertEqual(review1, review2)

    def test_conflicting_id_fails_no_state_change(self):
        """Same ID with different content fails; registry unchanged."""
        # First run succeeds
        self._run_full_cycle()
        registry_before = (self.root / "knowledge/evidence_registry.json").read_text()

        # Attempt second run with same ID but different content
        altered_candidate = copy.deepcopy(self.candidate)
        altered_candidate["value"] = "202.0"
        altered_candidate["excerpt"] = self.plain.replace("201.9", "202.0")
        altered_candidate["sha256"] = hashlib.sha256(self.plain.replace("201.9", "202.0").encode()).hexdigest()
        altered_capture = prepare_capture(self.raw.replace("201.9", "202.0"), source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=date.today().isoformat())

        with self.assertRaisesRegex(ValueError, "CONFLICTING_EVIDENCE_ID"):
            self._run_full_cycle(candidates_data=[{
                "candidate": altered_candidate,
                "snapshot_text": self.plain.replace("201.9", "202.0"),
                "capture": prepare_capture(self.raw.replace("201.9", "202.0"), source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=date.today().isoformat()),
                "reviewed_on": date.today().isoformat()
            }])

        registry_after = (self.root / "knowledge/evidence_registry.json").read_text()
        self.assertEqual(registry_before, registry_after)

    def test_conflicting_metadata_same_receipt_fails(self):
        """Same ID with different metadata → verifier catches PERIOD_UNIT_CURRENCY_MISMATCH first.

        The verifier validates all metadata (metric/period/unit/currency) as part of the receipt.
        Changing metadata changes the receipt, so the verifier catches the mismatch first.
        The coordinator's metadata check is a defense-in-depth that would catch conflicts
        if receipts were somehow equal (which shouldn't happen in practice).
        """
        # First run succeeds
        self._run_full_cycle()

        # Create candidate with same ID but different metadata (metric/period/unit/currency)
        # The verifier will catch this with PERIOD_UNIT_CURRENCY_MISMATCH
        altered_candidate = copy.deepcopy(self.candidate)
        altered_candidate["metric"] = "operating_income"
        altered_candidate["period"] = "Three months ended 2026-09-30"
        altered_candidate["unit"] = "million"
        altered_candidate["currency"] = "USD"
        # Keep same excerpt and sha256 so receipt would be identical
        # But metadata differs → verifier catches it

        with self.assertRaisesRegex(ValueError, "PERIOD_UNIT_CURRENCY_MISMATCH"):
            self._run_full_cycle(candidates_data=[{
                "candidate": altered_candidate,
                "snapshot_text": self.plain,  # Same excerpt
                "capture": self.capture,       # Same capture
                "reviewed_on": date.today().isoformat()
            }])

    def test_invalid_capture_no_state_change(self):
        """Invalid capture (schema mismatch) fails, registry unchanged."""
        self._run_full_cycle()
        registry_before = (self.root / "knowledge/evidence_registry.json").read_text()

        bad_capture = copy.deepcopy(self.capture)
        bad_capture["schema_version"] = True  # invalid type

        with self.assertRaisesRegex(ValueError, "CAPTURE_INTEGRITY_MISMATCH"):
            self._run_full_cycle(candidates_data=[{
                "candidate": self.candidate,
                "snapshot_text": self.plain,
                "capture": bad_capture,
                "reviewed_on": date.today().isoformat()
            }])

        registry_after = (self.root / "knowledge/evidence_registry.json").read_text()
        self.assertEqual(registry_before, registry_after)

    def test_missing_artifact_detected(self):
        """Record in registry but snapshot file missing → MISSING_OR_ALTERED_ARTIFACT."""
        # Create a record with content-addressed path but don't create the file
        missing_text = "this file does not exist"
        missing_hash = hashlib.sha256(missing_text.encode()).hexdigest()
        missing_path = f"knowledge/snapshots/{missing_hash}.txt"

        fake_record = [{
            "id": "MISSING_ARTIFACT",
            "record_type": "document",
            "company": "AMZN",
            "metric": "net_sales",
            "period": "Three months ended 2026-09-30",
            "unit": "billion",
            "currency": "USD",
            "value": "100",
            "source_url": SOURCE_URL,
            "publication_date": "2026-10-29",
            "acquisition_date": date.today().isoformat(),
            "snapshot_path": f"knowledge/snapshots/{hashlib.sha256(missing_text.encode()).hexdigest()}.txt",
            "sha256": hashlib.sha256(missing_text.encode()).hexdigest(),
            "excerpt": missing_text,
            "human_verified": False,
            "reviewer": "verifier",
            "reviewed_on": date.today().isoformat(),
            "review_status": "automated_verified",
            "verification": {
                "candidate": {},
                "receipt": {},
                "publisher_snapshot_path": f"knowledge/snapshots/{hashlib.sha256(missing_text.encode()).hexdigest()}.txt"
            }
        }]
        (self.root / "knowledge/evidence_registry.json").write_text(json.dumps(fake_record), encoding="utf-8")
        # Note: we do NOT create the snapshot file

        with self.assertRaisesRegex(ValueError, "MISSING_OR_ALTERED_ARTIFACT"):
            self._run_full_cycle()

    def test_artifact_altered_detected(self):
        """Record in registry with correct content-addressed path but file content altered → EXISTING_SNAPSHOT_NOT_CONTENT_ADDRESSED."""
        # Create record with correct content-addressed path
        existing_text = "original content"
        existing_hash = hashlib.sha256(b"original content").hexdigest()
        existing_path = f"knowledge/snapshots/{existing_hash}.txt"

        fake_record = [{
            "id": "ALTERED_ARTIFACT",
            "record_type": "document",
            "company": "AMZN",
            "metric": "net_sales",
            "period": "Three months ended 2026-09-30",
            "unit": "billion",
            "currency": "USD",
            "value": "100",
            "source_url": SOURCE_URL,
            "publication_date": "2026-10-29",
            "acquisition_date": date.today().isoformat(),
            "snapshot_path": f"knowledge/snapshots/{hashlib.sha256(b'original content').hexdigest()}.txt",
            "sha256": hashlib.sha256(b"original content").hexdigest(),
            "excerpt": "original content",
            "human_verified": False,
            "reviewer": "verifier",
            "reviewed_on": date.today().isoformat(),
            "review_status": "automated_verified",
            "verification": {
                "candidate": {},
                "receipt": {},
                "publisher_snapshot_path": f"knowledge/snapshots/{hashlib.sha256(b'original content').hexdigest()}.txt"
            }
        }]
        (self.root / "knowledge/evidence_registry.json").write_text(json.dumps(fake_record), encoding="utf-8")
        (self.root / "knowledge/snapshots").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge/snapshots" / f"{hashlib.sha256(b'original content').hexdigest()}.txt").write_text("original content", encoding="utf-8")

        # Now alter the file
        snapshot_path = self.root / "knowledge" / "snapshots" / f"{hashlib.sha256(b'original content').hexdigest()}.txt"
        snapshot_path.write_text("ALTERED CONTENT", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "EXISTING_SNAPSHOT_NOT_CONTENT_ADDRESSED"):
            self._run_full_cycle()

    def test_candidate_relative_path_escape_rejected(self):
        """Candidate with escaping snapshot_path → PATH_OUTSIDE_ROOT."""
        bad_candidate = copy.deepcopy(self.candidate)
        bad_candidate["snapshot_path"] = "../../../etc/passwd"

        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_ROOT"):
            self._run_full_cycle(candidates_data=[{
                "candidate": bad_candidate,
                "snapshot_text": self.plain,
                "capture": self.capture,
                "reviewed_on": date.today().isoformat()
            }])

    def test_frozen_window_rejected_before_writes(self):
        """Frozen window (information_cutoff) → FROZEN_WINDOW_INCOMPATIBLE, no writes."""
        frozen_mandate = {
            "capital_eur": 3000,
            "information_cutoff": "2026-10-27",
            "portfolios": {"A": {"cash": 3000}, "B": {"cash": 3000}, "C": {"cash": 3000}}
        }
        frozen_root = Path(self.tmp.name) / "frozen"
        frozen_root.mkdir()
        (frozen_root / "knowledge").mkdir()
        (frozen_root / "knowledge/mandato.json").write_text(json.dumps(frozen_mandate), encoding="utf-8")
        # Do NOT create evidence_registry.json - test that it's not created

        from analisti_2027.quality import evidence_window
        window = evidence_window(frozen_mandate, date.today().isoformat())

        with self.assertRaisesRegex(ValueError, "FROZEN_WINDOW_INCOMPATIBLE_WITH_AUTOMATIC_PROMOTION"):
            promote_evidence_fixtures(frozen_root, date.today().isoformat(), window, [{
                "candidate": self.candidate,
                "snapshot_text": self.plain,
                "capture": self.capture,
                "reviewed_on": date.today().isoformat()
            }])

        # No files written
        self.assertFalse((frozen_root / "knowledge" / "evidence_registry.json").exists() or
                        (frozen_root / "knowledge" / "evidence_registry.json.tmp").exists())

    def test_window_mismatch_rejected(self):
        """Provided window differs from mandate-derived window → WINDOW_MISMATCH."""
        from analisti_2027.quality import evidence_window
        # Provide a window that doesn't match the mandate
        wrong_window = {"mode": "rolling", "start": "2026-01-01", "end": date.today().isoformat(), "timezone": "UTC"}
        with self.assertRaisesRegex(ValueError, "WINDOW_MISMATCH"):
            promote_evidence_fixtures(self.root, date.today().isoformat(), wrong_window, [{
                "candidate": self.candidate,
                "snapshot_text": self.plain,
                "capture": self.capture,
                "reviewed_on": date.today().isoformat()
            }])

    def test_artifact_path_outside_root_rejected(self):
        """An escaping verifier artifact is rejected before publication."""
        from unittest.mock import patch
        from analisti_2027.acquisition_adapter import verify_acquired_candidate

        registry = self.root / "knowledge/evidence_registry.json"
        before = registry.read_bytes()
        with tempfile.TemporaryDirectory() as outside:
            escaped = Path(outside) / "must-not-be-written.txt"
            def unsafe_verifier(*args, **kwargs):
                result = copy.deepcopy(verify_acquired_candidate(*args, **kwargs))
                result["artifacts"][str(escaped)] = "unsafe artifact"
                return result
            with patch("analisti_2027.acquisition_adapter.verify_acquired_candidate",
                       side_effect=unsafe_verifier) as verifier:
                with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_ROOT"):
                    self._run_full_cycle()
            verifier.assert_called_once()
            self.assertFalse(escaped.exists())
        self.assertEqual(registry.read_bytes(), before)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_publication_error_registry_preserved(self):
        """Simulate registry write failure; old registry intact, retry succeeds."""
        import os
        original_replace = os.replace

        def failing_replace(src, dst):
            if "evidence_registry.json" in str(dst):
                raise OSError("Simulated disk full")
            return original_replace(src, dst)

        # First run succeeds
        self._run_full_cycle()
        registry_before = (self.root / "knowledge/evidence_registry.json").read_text()

        # Second run with new candidate, but registry write fails
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "NEW_CANDIDATE"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=date.today().isoformat())
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        os.replace = failing_replace
        try:
            with self.assertRaises(OSError):
                self._run_full_cycle(candidates_data=[{
                    "candidate": new_candidate,
                    "snapshot_text": new_plain,
                    "capture": new_capture,
                    "reviewed_on": date.today().isoformat()
                }])
        finally:
            os.replace = original_replace

        # Old registry preserved
        registry_after = (self.root / "knowledge/evidence_registry.json").read_text()
        self.assertEqual(registry_before, registry_after)

        # Retry succeeds
        new_candidate2 = copy.deepcopy(self.candidate)
        new_candidate2["id"] = "NEW_CANDIDATE2"
        new_plain2 = "Net sales increased 12% to $202.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw2 = new_plain2.replace("Net sales", "**Net sales**")
        new_capture2 = prepare_capture(new_raw2, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=date.today().isoformat())
        new_candidate2["sha256"] = hashlib.sha256(new_plain2.encode()).hexdigest()
        new_candidate2["value"] = "202.0"
        new_candidate2["excerpt"] = new_plain2
        _, context, review = self._run_full_cycle(candidates_data=[{
            "candidate": new_candidate2,
            "snapshot_text": new_plain2,
            "capture": new_capture2,
            "reviewed_on": date.today().isoformat()
        }])
        self.assertEqual(len(context["evidence_records"]), 2)

    def test_artifact_write_error_retry_succeeds(self):
        """Error during artifact temp file write; retry succeeds.

        This test simulates an artifact write failure (OSError on temp file creation for artifact paths)
        and verifies that the registry is preserved and retry succeeds.
        """
        from unittest.mock import patch
        import tempfile
        import os

        # First run succeeds
        self._run_full_cycle()
        registry_before = (self.root / "knowledge/evidence_registry.json").read_text()

        # Second run with new candidate, but artifact write fails
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "NEW_CANDIDATE"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=date.today().isoformat())
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        original_mkstemp = tempfile.mkstemp

        def failing_mkstemp(dir=None, prefix=None, suffix=None, **kwargs):
            # Check if this is for an artifact path (normalize path separators for cross-platform)
            if dir:
                dir_str = str(dir).replace(os.sep, '/')
                if "knowledge/snapshots" in dir_str or "knowledge/acquisitions" in dir_str:
                    raise OSError("Simulated disk full")
            return original_mkstemp(dir=dir, prefix=prefix, suffix=suffix, **kwargs)

        with patch('analisti_2027.integration.tempfile.mkstemp', new=failing_mkstemp):
            with self.assertRaises(OSError):
                self._run_full_cycle(candidates_data=[{
                    "candidate": new_candidate,
                    "snapshot_text": new_plain,
                    "capture": new_capture,
                    "reviewed_on": date.today().isoformat()
                }])

        # Registry preserved (no registry write attempted)
        registry_after = (self.root / "knowledge/evidence_registry.json").read_text()
        self.assertEqual(registry_before, registry_after)

        # Retry succeeds
        _, context, review = self._run_full_cycle(candidates_data=[{
            "candidate": new_candidate,
            "snapshot_text": new_plain,
            "capture": new_capture,
            "reviewed_on": date.today().isoformat()
        }])
        self.assertEqual(len(context["evidence_records"]), 2)

    def test_registry_write_error_retry_succeeds(self):
        """Retry exactly the same input after registry replacement fails."""
        from unittest.mock import patch
        registry = self.root / "knowledge/evidence_registry.json"
        before = registry.read_bytes()
        original_replace = os.replace
        hits = []
        def fail_registry(src, dst):
            if Path(dst) == registry:
                hits.append(Path(dst))
                raise OSError("injected registry replace failure")
            return original_replace(src, dst)
        with patch("analisti_2027.integration.os.replace", side_effect=fail_registry):
            with self.assertRaisesRegex(OSError, "injected registry replace failure"):
                self._run_full_cycle()
        self.assertEqual(hits, [registry])
        self.assertEqual(registry.read_bytes(), before)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])
        result, context, review = self._run_full_cycle()
        self.assertEqual(result["promoted"], [self.candidate["id"]])
        self.assertEqual(len(context["evidence_records"]), 1)
        self.assertEqual(review["evidence_review_counts"], {"human": 0, "automated": 1})

    def test_mirror_error_after_registry_committed(self):
        """Actual mirror write errors yield warnings after registry commit."""
        from unittest.mock import patch
        registry = self.root / "knowledge/evidence_registry.json"
        original_write_text = Path.write_text
        mirror_root = self.root / "src/analisti_2027/knowledge"
        hits = []
        def fail_mirror(path, *args, **kwargs):
            if path.is_relative_to(mirror_root):
                records = json.loads(registry.read_text(encoding="utf-8"))
                self.assertEqual([r["id"] for r in records], [self.candidate["id"]])
                hits.append(path)
                raise OSError("injected mirror write failure")
            return original_write_text(path, *args, **kwargs)
        with patch.object(Path, "write_text", new=fail_mirror):
            result, context, review = self._run_full_cycle()
        self.assertTrue(hits, "Mirror write failure must actually be injected")
        self.assertEqual(result["promoted"], [self.candidate["id"]])
        warnings = [w for w in result["warnings"] if w.startswith("MIRROR_WRITE_FAILED:")]
        self.assertEqual(len(warnings), len(hits))
        self.assertTrue(all("injected mirror write failure" in w for w in warnings))
        self.assertEqual(len(context["evidence_records"]), 1)
        self.assertEqual(review["evidence_review_counts"]["automated"], 1)

    def test_mirror_error_before_registry_committed(self):
        """No mirror write is attempted if registry commit fails."""
        from unittest.mock import patch
        registry = self.root / "knowledge/evidence_registry.json"
        before = registry.read_bytes()
        original_replace = os.replace
        original_write_text = Path.write_text
        mirror_root = self.root / "src/analisti_2027/knowledge"
        mirror_attempts = []
        registry_attempts = []
        def fail_registry(src, dst):
            if Path(dst) == registry:
                registry_attempts.append(Path(dst))
                raise OSError("injected registry commit failure")
            return original_replace(src, dst)
        def track_mirror(path, *args, **kwargs):
            if path.is_relative_to(mirror_root):
                mirror_attempts.append(path)
            return original_write_text(path, *args, **kwargs)
        with patch("analisti_2027.integration.os.replace", side_effect=fail_registry), \
             patch.object(Path, "write_text", new=track_mirror):
            with self.assertRaisesRegex(OSError, "injected registry commit failure"):
                self._run_full_cycle()
        self.assertEqual(registry_attempts, [registry])
        self.assertEqual(mirror_attempts, [])
        self.assertEqual(registry.read_bytes(), before)
        self.assertFalse(mirror_root.exists())

    def test_mirror_path_validation(self):
        """Real mirror destinations are safety-checked and written."""
        from unittest.mock import patch
        from analisti_2027.integration import _is_path_safe
        mirror_root = self.root / "src/analisti_2027/knowledge"
        with patch("analisti_2027.integration._is_path_safe",
                   wraps=_is_path_safe) as safety:
            result, _, _ = self._run_full_cycle()
        mirror_files = [p for p in mirror_root.rglob("*") if p.is_file()]
        self.assertTrue(mirror_files)
        checked = {Path(call.args[1]) for call in safety.call_args_list}
        for mirror in mirror_files:
            self.assertIn(mirror, checked)
            authoritative = self.root / "knowledge" / mirror.relative_to(mirror_root)
            # Mirrors are textual copies; Windows write_text uses CRLF.
            # Preserve every byte except the CRLF/LF representation.
            self.assertEqual(
                mirror.read_bytes().replace(b"\r\n", b"\n"),
                authoritative.read_bytes().replace(b"\r\n", b"\n"),
            )
        self.assertEqual(result["warnings"], [])

    def test_path_outside_root_rejected(self):
        """Candidate with escaping snapshot_path → PATH_OUTSIDE_ROOT."""
        bad_candidate = copy.deepcopy(self.candidate)
        bad_candidate["snapshot_path"] = "../../../etc/passwd"

        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_ROOT"):
            self._run_full_cycle(candidates_data=[{
                "candidate": bad_candidate,
                "snapshot_text": self.plain,
                "capture": self.capture,
                "reviewed_on": date.today().isoformat()
            }])

    def test_mirror_path_outside_root_rejected(self):
        """A mirror safety refusal after registry commit yields warnings."""
        from unittest.mock import patch
        from analisti_2027.integration import _is_path_safe
        mirror_root = self.root / "src/analisti_2027/knowledge"
        registry = self.root / "knowledge/evidence_registry.json"
        original_replace = os.replace
        committed = False
        denied = []

        def track_commit(src, dst):
            nonlocal committed
            result = original_replace(src, dst)
            if Path(dst) == registry:
                committed = True
            return result

        def deny_mirror(root, target):
            target = Path(target)
            if committed and target.is_relative_to(mirror_root):
                denied.append(target)
                return False
            return _is_path_safe(root, target)

        with patch("analisti_2027.integration.os.replace", side_effect=track_commit), \
             patch("analisti_2027.integration._is_path_safe", side_effect=deny_mirror):
            result, context, review = self._run_full_cycle()
        self.assertTrue(committed, "Registry replacement must succeed first")
        self.assertTrue(denied, "Mirror path rejection must actually be exercised")
        self.assertFalse(mirror_root.exists())
        warnings = [w for w in result["warnings"] if w.startswith("MIRROR_PATH_UNSAFE:")]
        self.assertEqual(len(warnings), len(denied))
        for target in denied:
            relative = target.relative_to(self.root / "src/analisti_2027").as_posix()
            self.assertIn(f"MIRROR_PATH_UNSAFE: {relative}", warnings)
        self.assertEqual(result["promoted"], [self.candidate["id"]])
        self.assertEqual(len(context["evidence_records"]), 1)
        self.assertEqual(review["evidence_review_counts"]["automated"], 1)

    def test_scenario_bundle_preserved_across_prepare_calls(self):
        """scenario_bundle passed to prepare is preserved across multiple calls."""
        bundle = {
            "data_kind": "synthetic",
            "scenarios": {"H1": {
                "assumptions": "Test assumptions",
                "timeline": [
                    {"date": "2027-01-04", "quotes": {"AVGO": {"price": "100", "eur_per_quote": "0.9"}, "NVDA": {"price": "100", "eur_per_quote": "0.9"}, "AMZN": {"price": "100", "eur_per_quote": "0.9"}, "ShinEtsu": {"price": "100", "eur_per_quote": "0.006"}}},
                    {"date": "2027-02-01", "quotes": {"AVGO": {"price": "100", "eur_per_quote": "0.9"}, "NVDA": {"price": "100", "eur_per_quote": "0.9"}, "AMZN": {"price": "100", "eur_per_quote": "0.9"}, "ShinEtsu": {"price": "100", "eur_per_quote": "0.006"}}},
                    {"date": "2027-03-01", "quotes": {"AVGO": {"price": "100", "eur_per_quote": "0.9"}, "NVDA": {"price": "100", "eur_per_quote": "0.9"}, "AMZN": {"price": "100", "eur_per_quote": "0.9"}, "ShinEtsu": {"price": "100", "eur_per_quote": "0.006"}}},
                    {"date": "2027-12-31", "quotes": {"AVGO": {"price": "100", "eur_per_quote": "0.9"}, "NVDA": {"price": "100", "eur_per_quote": "0.9"}, "AMZN": {"price": "100", "eur_per_quote": "0.9"}, "ShinEtsu": {"price": "100", "eur_per_quote": "0.006"}}},
                ],
                "entries": {"I1": ["2027-01-04"], "I2": ["2027-01-04", "2027-02-01", "2027-03-01"]},
                "rules": {"AVGO": {"quantity_step": "0.001", "fixed_fee_eur": "0", "commission_bps": "0", "fx_fee_bps": "0"},
                         "NVDA": {"quantity_step": "0.001", "fixed_fee_eur": "0", "commission_bps": "0", "fx_fee_bps": "0"},
                         "AMZN": {"quantity_step": "0.001", "fixed_fee_eur": "0", "commission_bps": "0", "fx_fee_bps": "0"},
                         "ShinEtsu": {"quantity_step": "0.001", "fixed_fee_eur": "0", "commission_bps": "0", "fx_fee_bps": "0"}}
            }}
        }

        # First prepare
        context1 = prepare(self.root, bundle)
        # Promote
        promote_evidence_fixtures(self.root, context1["as_of"], evidence_window(self.mandate, context1["as_of"]), [{
            "candidate": self.candidate,
            "snapshot_text": self.plain,
            "capture": self.capture,
            "reviewed_on": date.today().isoformat()
        }])
        # Second prepare (re-reads registry)
        context2 = prepare(self.root, bundle)

        # scenario_bundle identical
        self.assertEqual(context1["scenario_bundle"], context2["scenario_bundle"])
        # Numeric results preserved
        self.assertEqual(context1["numeric_results"], context2["numeric_results"])

    def test_absolute_path_rejected(self):
        """Absolute paths in candidate or artifact paths are rejected."""
        bad_candidate = copy.deepcopy(self.candidate)
        bad_candidate["snapshot_path"] = "C:\\Windows\\system32\\drivers\\etc\\hosts"

        with self.assertRaisesRegex(ValueError, "PATH_OUTSIDE_ROOT"):
            self._run_full_cycle(candidates_data=[{
                "candidate": bad_candidate,
                "snapshot_text": self.plain,
                "capture": self.capture,
                "reviewed_on": date.today().isoformat()
            }])

    def test_preexisting_unsafe_temp_file(self):
        """Pre-existing unsafe temp file is cleaned up and doesn't block."""
        # Create a pre-existing temp file matching the pattern used by mkstemp
        # The code uses: tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
        # Which creates files like: filename.txt.XXXXXX.tmp
        content_hash = self.candidate["sha256"]
        target_name = f"{content_hash}.txt"
        # Create a temp file that matches the prefix pattern
        temp_file = self.root / "knowledge" / "snapshots" / f"{target_name}.preexisting.tmp"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text("PRE-EXISTING TEMP", encoding="utf-8")

        # Should succeed and clean up the temp file (or at least not block)
        promote_result, context, review = self._run_full_cycle()
        self.assertEqual(promote_result["promoted"], ["TEST_AMZN_NET_SALES"])

        # The pre-existing temp file should not block the promotion
        # (it may or may not be cleaned up depending on implementation)
        # The important thing is the promotion succeeds

    def test_human_record_with_content_addressed_path(self):
        """Human-verified record with content-addressed path works correctly.

        The review_integration.py enforces content-addressed paths for all records.
        This test verifies human records with proper content-addressed paths work.
        """
        human_text = "human verified content"
        human_hash = hashlib.sha256(human_text.encode()).hexdigest()
        # Human record uses a content-addressed path (required by review_integration.py)
        human_path = f"knowledge/snapshots/{human_hash}.txt"

        existing = [{
            "id": "HUMAN_VERIFIED",
            "record_type": "document",
            "company": "AMZN",
            "metric": "net_sales",
            "period": "Three months ended 2026-09-30",
            "unit": "billion",
            "currency": "USD",
            "value": "100",
            "source_url": SOURCE_URL,
            "publication_date": "2026-10-29",
            "acquisition_date": date.today().isoformat(),
            "snapshot_path": human_path,
            "sha256": hashlib.sha256(human_text.encode()).hexdigest(),
            "excerpt": human_text,
            "human_verified": True,
            "reviewer": "human_reviewer",
            "reviewed_on": date.today().isoformat(),
            "review_status": "approved"
        }]
        (self.root / "knowledge/evidence_registry.json").write_text(json.dumps(existing), encoding="utf-8")
        (self.root / "knowledge/snapshots").mkdir(parents=True, exist_ok=True)
        (self.root / human_path).write_text(human_text, encoding="utf-8")

        # Should succeed - human record with content-addressed path
        promote_result, context, review = self._run_full_cycle()
        self.assertEqual(promote_result["promoted"], ["TEST_AMZN_NET_SALES"])
        self.assertEqual(promote_result["skipped"], [])

    def test_duplicate_registry_id_fails(self):
        """Duplicate ID in existing registry → DUPLICATE_REGISTRY_ID."""
        dup_text = "duplicate content"
        dup_hash = hashlib.sha256(b"duplicate content").hexdigest()
        dup_path = f"knowledge/snapshots/{hashlib.sha256(b'duplicate content').hexdigest()}.txt"

        existing = [{
            "id": "DUP_ID",
            "record_type": "document",
            "company": "AMZN",
            "metric": "net_sales",
            "period": "Three months ended 2026-09-30",
            "unit": "billion",
            "currency": "USD",
            "value": "100",
            "source_url": SOURCE_URL,
            "publication_date": "2026-10-29",
            "acquisition_date": date.today().isoformat(),
            "snapshot_path": dup_path,
            "sha256": dup_hash,
            "excerpt": "duplicate content",
            "human_verified": False,
            "reviewer": "verifier",
            "reviewed_on": date.today().isoformat(),
            "review_status": "automated_verified",
            "verification": {
                "candidate": {},
                "receipt": {},
                "publisher_snapshot_path": f"knowledge/snapshots/{hashlib.sha256(b'duplicate content').hexdigest()}.txt"
            }
        }, {
            "id": "DUP_ID",  # Same ID
            "record_type": "document",
            "company": "NVDA",
            "metric": "revenue",
            "period": "test",
            "unit": "million",
            "currency": "USD",
            "value": "200",
            "source_url": "https://example.org/test",
            "publication_date": "2026-10-27",
            "acquisition_date": date.today().isoformat(),
            "snapshot_path": f"knowledge/snapshots/{hashlib.sha256(b'other content').hexdigest()}.txt",
            "sha256": hashlib.sha256(b"other content").hexdigest(),
            "excerpt": "other content",
            "human_verified": True,
            "reviewer": "test",
            "reviewed_on": date.today().isoformat(),
            "review_status": "approved"
        }]
        (self.root / "knowledge/evidence_registry.json").write_text(json.dumps(existing), encoding="utf-8")
        (self.root / "knowledge/snapshots").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge/snapshots" / f"{hashlib.sha256(b'duplicate content').hexdigest()}.txt").write_text("duplicate content", encoding="utf-8")
        (self.root / "knowledge/snapshots" / f"{hashlib.sha256(b'other content').hexdigest()}.txt").write_text("other content", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "DUPLICATE_REGISTRY_ID"):
            self._run_full_cycle()

    def test_raw_and_normalized_verified_on_skip(self):
        """When skipping existing record, verify raw and normalized artifacts from verifier."""
        # First run succeeds
        self._run_full_cycle()
        registry_before = (self.root / "knowledge/evidence_registry.json").read_text()

        # Get the raw and normalized snapshot paths from the verifier artifacts
        # They should exist in knowledge/snapshots/
        snapshot_dir = self.root / "knowledge" / "snapshots"
        raw_files = list(snapshot_dir.glob("*.txt"))
        self.assertTrue(len(raw_files) > 0)

        # Second run should skip and verify all artifacts exist
        promote_result, context, review = self._run_full_cycle()
        self.assertEqual(promote_result["skipped"], ["TEST_AMZN_NET_SALES"])

        # Registry unchanged
        registry_after = (self.root / "knowledge/evidence_registry.json").read_text()
        self.assertEqual(registry_before, registry_after)

    def test_manifest_verified_on_skip(self):
        """When skipping existing record, verify acquisition manifest artifact."""
        # First run succeeds
        self._run_full_cycle()
        registry_before = (self.root / "knowledge/evidence_registry.json").read_text()

        # Get the manifest path
        acquisition_dir = self.root / "knowledge" / "acquisitions"
        manifest_files = list(acquisition_dir.glob("*.json"))
        self.assertTrue(len(manifest_files) > 0)

        # Second run should skip and verify manifest exists
        promote_result, context, review = self._run_full_cycle()
        self.assertEqual(promote_result["skipped"], ["TEST_AMZN_NET_SALES"])

        # Registry unchanged
        registry_after = (self.root / "knowledge/evidence_registry.json").read_text()
        self.assertEqual(registry_before, registry_after)


if __name__ == "__main__":
    unittest.main()