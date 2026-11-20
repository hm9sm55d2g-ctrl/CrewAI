"""Deterministic tests for evidence pipeline coordinator: capture → verify → promote → registry."""
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from analisti_2027.integration import promote_evidence_fixtures
from analisti_2027.acquisition_adapter import prepare_capture
from analisti_2027.automated_evidence import SOURCE_URL, verify_candidate
from analisti_2027.quality import END, evidence_window


class EvidencePipelineDeterministicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()
        # Mandate with rolling window (required for automatic promotion)
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
            },
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

    def _make_candidates_data(self, override=None):
        cd = {
            "candidate": self.candidate,
            "snapshot_text": self.plain,  # for Amazon, snapshot_text == normalized_text
            "capture": self.capture,
            "reviewed_on": self.day
        }
        if override:
            cd = copy.deepcopy(cd)
            cd.update(override)
        return [cd]

    def _run_promote(self, candidates_data=None, as_of=None, window=None):
        if as_of is None:
            as_of = date.today().isoformat()
        if window is None:
            window = evidence_window(self.mandate, as_of)
        if candidates_data is None:
            candidates_data = self._make_candidates_data()
        return promote_evidence_fixtures(self.root, as_of, window, candidates_data)

    def _read_registry_bytes(self):
        path = self.root / "knowledge" / "evidence_registry.json"
        return path.read_bytes()

    def _read_registry(self):
        path = self.root / "knowledge" / "evidence_registry.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _read_file(self, rel_path):
        path = self.root / rel_path
        return path.read_text(encoding="utf-8") if path.exists() else None

    def _snapshot_files(self):
        """Return dict of {relative_path: content_bytes} for all files under self.root."""
        snap = {}
        for f in self.root.rglob("*"):
            if f.is_file():
                rel = f.relative_to(self.root).as_posix()
                snap[rel] = f.read_bytes()
        return snap

    def _run_full_cycle(self, candidates_data=None):
        """Run: promote_evidence_fixtures → prepare → final_review_summary."""
        from analisti_2027.integration import prepare
        from analisti_2027.review_integration import final_review_summary
        from analisti_2027.quality import SECTIONS, END
        as_of = date.today().isoformat()
        window = evidence_window(self.mandate, as_of)
        if candidates_data is None:
            candidates_data = self._make_candidates_data()
        promote_result = promote_evidence_fixtures(self.root, as_of, window, candidates_data)
        context = prepare(self.root)
        raw_report = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join(
            "## " + s + "\nND." for s in ["Sintesi", "Evidenze", "Vincoli", "AVGO", "NVDA", "AMZN", "ShinEtsu", "Scenari", "Obiezioni"]
        ) + "\n" + END
        review = final_review_summary(raw_report, context, self.root)
        return promote_result, context, review

    def test_success_full_pipeline(self):
        """Capture fixture → verify → promote → prepare sees record → final_review_summary counts automated=1."""
        result = self._run_promote()
        self.assertEqual(result["promoted"], ["TEST_AMZN_NET_SALES"])
        self.assertEqual(result["skipped"], [])

        # Verify registry updated
        registry = self._read_registry()
        self.assertEqual(len(registry), 1)
        record = registry[0]
        self.assertEqual(record["id"], "TEST_AMZN_NET_SALES")
        self.assertEqual(record["review_status"], "automated_verified")
        self.assertFalse(record["human_verified"])

        # Verify prepare sees the new record
        from analisti_2027.integration import prepare
        context = prepare(self.root)
        self.assertEqual(len(context["evidence_records"]), 1)
        self.assertEqual(context["evidence_records"][0]["id"], "TEST_AMZN_NET_SALES")
        self.assertEqual(context["evidence_records"][0]["review_status"], "automated_verified")

        # Verify final_review_summary counts automated evidence
        from analisti_2027.review_integration import final_review_summary
        raw_report = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join(
            "## " + s + "\nND." for s in ["Sintesi", "Evidenze", "Vincoli", "AVGO", "NVDA", "AMZN", "ShinEtsu", "Scenari", "Obiezioni"]
        ) + "\n" + END
        review = final_review_summary(raw_report, context, self.root)
        self.assertEqual(review["evidence_review_counts"], {"human": 0, "automated": 1})

    def test_partial_write_artifact_and_registry_succeeds(self):
        """Partial os.write calls (multiple calls) still produce complete files."""
        from unittest.mock import patch
        import os

        # First run succeeds
        self._run_promote()
        registry_before = self._read_registry_bytes()

        # Second run with new candidate
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "PARTIAL_WRITE_TEST"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=self.day)
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        candidates_data = [{
            "candidate": new_candidate,
            "snapshot_text": new_plain,
            "capture": new_capture,
            "reviewed_on": self.day
        }]

        # Before running, get expected artifact bytes from verifier with same params
        from analisti_2027.acquisition_adapter import verify_acquired_candidate
        verification = verify_acquired_candidate(
            copy.deepcopy(new_candidate), new_plain, new_capture,
            reviewed_on=self.day, as_of=date.today().isoformat()
        )
        expected_artifacts = verification["artifacts"]

        original_write = os.write
        original_mkstemp = tempfile.mkstemp
        fd_to_path = {}
        partial_write_events = []

        def tracking_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            fd_to_path[fd] = path
            return fd, path

        def partial_write(fd, data):
            path = fd_to_path.get(fd, "")
            norm_path = path.replace('\\', '/')
            is_artifact = "knowledge/snapshots/" in norm_path or "knowledge/acquisitions/" in norm_path
            is_registry = "evidence_registry.json" in norm_path
            # Delegate to original write with smaller chunk
            chunk_size = min(50, len(data))
            bytes_written = original_write(fd, data[:chunk_size])
            if is_artifact or is_registry:
                partial_write_events.append({
                    "fd": fd,
                    "path": path,
                    "is_artifact": is_artifact,
                    "is_registry": is_registry,
                    "requested": len(data),
                    "written": bytes_written,
                    "partial": bytes_written < len(data)
                })
            return bytes_written

        with patch('analisti_2027.integration.tempfile.mkstemp', new=tracking_mkstemp), \
             patch('analisti_2027.integration.os.write', new=partial_write):
            self._run_promote(candidates_data=candidates_data)

        # Verify registry has both records
        registry = self._read_registry()
        self.assertEqual(len(registry), 2)
        ids = {r["id"] for r in registry}
        self.assertEqual(ids, {"TEST_AMZN_NET_SALES", "PARTIAL_WRITE_TEST"})

        # Successful promotion must update the registry bytes.
        self.assertNotEqual(self._read_registry_bytes(), registry_before)

        # Verify at least one partial write on artifact AND one on registry
        artifact_partials = [e for e in partial_write_events if e["is_artifact"] and e["partial"]]
        registry_partials = [e for e in partial_write_events if e["is_registry"] and e["partial"]]
        self.assertTrue(len(artifact_partials) > 0, "Expected at least one partial write on artifact")
        self.assertTrue(len(registry_partials) > 0, "Expected at least one partial write on registry")

        # Verify ALL critical artifacts (knowledge/...) match expected bytes
        for path, expected_content in expected_artifacts.items():
            if path.startswith("knowledge/"):
                target = self.root / path
                self.assertTrue(target.exists(), f"Expected critical artifact not found: {path}")
                actual = target.read_bytes()
                self.assertEqual(actual, expected_content.encode("utf-8") if isinstance(expected_content, str) else expected_content,
                                f"Content mismatch for {path}")

        # Verify registry has both records with correct IDs
        registry = self._read_registry()
        self.assertEqual(len(registry), 2)
        ids = {r["id"] for r in registry}
        self.assertEqual(ids, {"TEST_AMZN_NET_SALES", "PARTIAL_WRITE_TEST"})

        # No temp files left
        for f in self.root.rglob("*.tmp"):
            self.fail(f"Temp file left behind: {f}")

    def test_os_write_returns_zero_on_artifact_raises_error(self):
        """os.write returning 0 on artifact raises OSError, no temp left, registry unchanged."""
        from unittest.mock import patch
        import os

        # First run succeeds
        self._run_promote()
        registry_before = self.root / "knowledge" / "evidence_registry.json"
        registry_before_bytes = registry_before.read_bytes()

        # Second run with new candidate, but os.write returns 0 on artifact
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "ZERO_WRITE_ARTIFACT"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=self.day)
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        candidates_data = [{
            "candidate": new_candidate,
            "snapshot_text": new_plain,
            "capture": new_capture,
            "reviewed_on": self.day
        }]

        original_write = os.write
        original_mkstemp = tempfile.mkstemp
        fd_to_path = {}
        artifact_temp_targets = {}
        artifact_targets_existed = {}
        artifact_targets = {}

        def tracking_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            fd_to_path[fd] = path
            norm_path = path.replace('\\', '/')
            if "knowledge/snapshots/" in norm_path or "knowledge/acquisitions/" in norm_path:
                artifact_temp_targets[fd] = path
                prefix = kwargs["prefix"]
                self.assertTrue(prefix.endswith("."))
                target = Path(kwargs["dir"]) / prefix[:-1]
                artifact_targets[path] = target
                artifact_targets_existed[path] = target.exists()
            return fd, path

        def zero_write_on_artifact(fd, data):
            path = fd_to_path.get(fd, "")
            norm_path = path.replace('\\', '/')
            if "knowledge/snapshots/" in norm_path or "knowledge/acquisitions/" in norm_path:
                # Record which artifact temp was hit
                artifact_temp_targets[fd] = fd_to_path[fd]
                return 0
            return original_write(fd, data)

        with patch('analisti_2027.integration.tempfile.mkstemp', new=tracking_mkstemp), \
             patch('analisti_2027.integration.os.write', new=zero_write_on_artifact):
            caught_error = None
            try:
                self._run_promote(candidates_data=candidates_data)
                self.fail("Expected OSError to be raised")
            except OSError as e:
                caught_error = e
                # Verify the error came from _write_all
                self.assertIn("returned 0 with data remaining", str(e))

        # Registry unchanged (bytes)
        registry_after_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()
        self.assertEqual(registry_after_bytes, registry_before_bytes)

        # Exactly one artifact temp was hit and was initially absent
        hit_artifacts = list(artifact_temp_targets.items())
        self.assertEqual(len(hit_artifacts), 1, "Expected exactly one artifact temp to be hit")
        fd, path = hit_artifacts[0]
        self.assertFalse(artifact_targets_existed.get(path, True), "Target artifact should have been initially absent")
        # That precise target remains absent
        target = artifact_targets[path]
        self.assertFalse(target.exists(), f"Target artifact should remain absent: {target}")

        # Error explicitly from _write_all
        self.assertIsNotNone(caught_error)
        self.assertIn("returned 0 with data remaining", str(caught_error))

        # No temp files left
        for f in self.root.rglob("*.tmp"):
            self.fail(f"Temp file left behind: {f}")

    def test_os_write_returns_zero_on_registry_raises_error(self):
        """os.write returning 0 on registry raises OSError, registry unchanged, no temp left."""
        from unittest.mock import patch
        import os

        # First run succeeds
        self._run_promote()
        registry_before = self.root / "knowledge" / "evidence_registry.json"
        registry_before_bytes = registry_before.read_bytes()

        # Second run with new candidate, but os.write returns 0 on registry
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "ZERO_WRITE_REGISTRY"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=self.day)
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        candidates_data = [{
            "candidate": new_candidate,
            "snapshot_text": new_plain,
            "capture": new_capture,
            "reviewed_on": self.day
        }]

        original_write = os.write
        original_mkstemp = tempfile.mkstemp
        fd_to_path = {}
        registry_temp_hit = False

        def tracking_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            fd_to_path[fd] = path
            return fd, path

        def zero_write_on_registry(fd, data):
            path = fd_to_path.get(fd, "")
            if "evidence_registry.json" in path:
                nonlocal registry_temp_hit
                registry_temp_hit = True
                return 0
            return original_write(fd, data)

        with patch('analisti_2027.integration.tempfile.mkstemp', new=tracking_mkstemp), \
             patch('analisti_2027.integration.os.write', new=zero_write_on_registry):
            with self.assertRaises(OSError) as cm:
                self._run_promote(candidates_data=candidates_data)
        # Verify the error came from _write_all
        self.assertIn("returned 0 with data remaining", str(cm.exception))

        # Registry unchanged (bytes)
        registry_after_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()
        self.assertEqual(registry_after_bytes, registry_before_bytes)

        # Verify registry phase was hit
        self.assertTrue(registry_temp_hit, "Registry phase should have been hit")

        # No temp files left
        for f in self.root.rglob("*.tmp"):
            self.fail(f"Temp file left behind: {f}")

        # Artifact files may exist (already published before registry error)
        # That's allowed per contract

    def test_os_replace_fails_on_artifact_cleans_temp(self):
        """os.replace failing on artifact cleans temp, target not published, registry unchanged."""
        from unittest.mock import patch
        import os

        # First run succeeds
        self._run_promote()
        registry_before_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()

        # Second run with new candidate, but os.replace fails on artifact
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "REPLACE_FAIL_ARTIFACT"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=self.day)
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        candidates_data = [{
            "candidate": new_candidate,
            "snapshot_text": new_plain,
            "capture": new_capture,
            "reviewed_on": self.day
        }]

        original_replace = os.replace
        replaced_dst = []
        artifact_targets = {}

        def failing_replace(src, dst):
            replaced_dst.append(str(dst))
            dst_path = Path(dst)
            dst_str = str(dst).replace('\\', '/')
            if "knowledge/snapshots/" in dst_str or "knowledge/acquisitions/" in dst_str:
                # Record the target and whether it existed
                artifact_targets[str(dst)] = dst_path.exists()
                raise OSError("Simulated replace failure on artifact")
            return original_replace(src, dst)

        with patch('analisti_2027.integration.os.replace', new=failing_replace):
            with self.assertRaises(OSError):
                self._run_promote(candidates_data=candidates_data)

        # Registry unchanged (bytes)
        registry_after_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()
        self.assertEqual(registry_after_bytes, registry_before_bytes)

        # Target artifact was attempted and was initially absent
        artifact_attempts = [dst for dst in replaced_dst if "knowledge/snapshots/" in dst.replace('\\', '/') or "knowledge/acquisitions/" in dst.replace('\\', '/')]
        self.assertTrue(len(artifact_attempts) > 0, "artifact replace should have been attempted")

        for dst in artifact_attempts:
            self.assertFalse(artifact_targets[dst], f"Target artifact should have been initially absent: {dst}")
            target = Path(dst)
            self.assertFalse(target.exists(), f"Artifact should not be published when replace fails: {dst}")

        # Registry unchanged (bytes)
        registry_after_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()
        self.assertEqual(registry_after_bytes, registry_before_bytes)

        # No temp files left
        for f in self.root.rglob("*.tmp"):
            self.fail(f"Temp file left behind: {f}")

    def test_os_replace_fails_on_registry_cleans_temp(self):
        """os.replace failing on registry cleans temp, previous registry unchanged, artifacts may remain."""
        from unittest.mock import patch
        import os

        # First run succeeds
        self._run_promote()
        registry_before_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()

        # Second run with new candidate, but os.replace fails on registry
        new_candidate = copy.deepcopy(self.candidate)
        new_candidate["id"] = "REPLACE_FAIL_REGISTRY"
        new_plain = "Net sales increased 10% to $200.0 billion in the third quarter, compared with $180.2 billion in third quarter 2025."
        new_raw = new_plain.replace("Net sales", "**Net sales**")
        new_capture = prepare_capture(new_raw, source_url=SOURCE_URL, publication_date="2026-10-29", acquired_on=self.day)
        new_candidate["sha256"] = hashlib.sha256(new_plain.encode()).hexdigest()
        new_candidate["value"] = "200.0"
        new_candidate["excerpt"] = new_plain

        candidates_data = [{
            "candidate": new_candidate,
            "snapshot_text": new_plain,
            "capture": new_capture,
            "reviewed_on": self.day
        }]

        original_replace = os.replace
        replaced_dst = []
        expected_registry = self.root / "knowledge" / "evidence_registry.json"

        def failing_replace(src, dst):
            replaced_dst.append(str(dst))
            if Path(dst) == expected_registry:
                raise OSError("Simulated replace failure on registry")
            return original_replace(src, dst)

        with patch('analisti_2027.integration.os.replace', new=failing_replace):
            with self.assertRaises(OSError):
                self._run_promote(candidates_data=candidates_data)

        # Registry unchanged byte-for-byte
        registry_after_bytes = (self.root / "knowledge" / "evidence_registry.json").read_bytes()
        self.assertEqual(registry_after_bytes, registry_before_bytes)

        # Verify mock hit the exact registry dst
        registry_dst = [d for d in replaced_dst if Path(d) == expected_registry]
        self.assertTrue(len(registry_dst) > 0, "registry replace should have been attempted")
        self.assertEqual(Path(registry_dst[0]), expected_registry)

        # No temp files left
        for f in self.root.rglob("*.tmp"):
            self.fail(f"Temp file left behind: {f}")

        # Artifacts may exist (already published before registry error)
        # That's allowed per contract

    # === Direct _atomic_write helper tests ===

    def test_atomic_write_write_error_close_error_unlink_error(self):
        """Preserve write error and report close/unlink failures."""
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from analisti_2027.integration import _atomic_write

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.txt"
            original_close = os.close
            original_unlink = os.unlink

            write_error = OSError("Simulated write error")
            close_error = OSError("Simulated close error")
            unlink_error = OSError("Simulated unlink error")

            def failing_close(fd):
                original_close(fd)
                raise close_error

            try:
                with (
                    patch(
                        "analisti_2027.integration.os.write",
                        side_effect=write_error,
                    ) as write_mock,
                    patch(
                        "analisti_2027.integration.os.close",
                        side_effect=failing_close,
                    ) as close_mock,
                    patch(
                        "analisti_2027.integration.os.unlink",
                        side_effect=unlink_error,
                    ) as unlink_mock,
                    patch(
                        "analisti_2027.integration.os.replace",
                    ) as replace_mock,
                ):
                    with self.assertRaises(OSError) as cm:
                        _atomic_write(target, "test content")

                    self.assertIs(cm.exception, write_error)
                    write_mock.assert_called_once()
                    close_mock.assert_called_once()
                    unlink_mock.assert_called_once()
                    replace_mock.assert_not_called()

                    notes = getattr(cm.exception, "__notes__", [])

                    self.assertTrue(
                        any(
                            "fd close failed" in note
                            and str(close_error) in note
                            for note in notes
                        )
                    )
                    self.assertTrue(
                        any(
                            "temp cleanup failed" in note
                            and str(unlink_error) in note
                            for note in notes
                        )
                    )

                    self.assertFalse(target.exists())

                    temp_path = Path(unlink_mock.call_args.args[0])
                    self.assertEqual(temp_path.parent, target.parent)
                    self.assertTrue(temp_path.is_file())

            finally:
                for temp_path in target.parent.glob(
                    f"{target.name}.*.tmp"
                ):
                    original_unlink(temp_path)

    def test_atomic_write_close_error_after_write(self):
        """Close error after successful write: primary is close error, unlink attempted, replace not called."""
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from analisti_2027.integration import _atomic_write, _write_all

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "test.txt"

            original_write = os.write
            original_close = os.close
            original_unlink = os.unlink
            original_replace = os.replace

            def failing_close(fd):
                original_close(fd)
                raise OSError("Simulated close error")

            def tracking_unlink(path):
                tracking_unlink.called = True
                return original_unlink(path)
            tracking_unlink.called = False

            def tracking_replace(src, dst):
                tracking_replace.called = True
                return original_replace(src, dst)
            tracking_replace.called = False

            with patch('analisti_2027.integration.os.close', new=failing_close), \
                 patch('analisti_2027.integration.os.unlink', new=tracking_unlink), \
                 patch('analisti_2027.integration.os.replace', new=tracking_replace):
                with self.assertRaises(OSError) as cm:
                    _atomic_write(target, "test content")

            # Primary error is the close error
            self.assertEqual(str(cm.exception), "Simulated close error")
            # Unlink was attempted
            self.assertTrue(tracking_unlink.called)
            # Replace was NOT called
            self.assertFalse(tracking_replace.called)

    def test_atomic_write_cleanup_error_without_primary(self):
        """Cleanup error without primary error: unlink fails, no primary error."""
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from analisti_2027.integration import _atomic_write

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.txt"
            original_unlink = os.unlink

            # Pre-populate target with known content
            target.write_text("same content", encoding="utf-8")

            unlink_error = OSError("Simulated unlink error")

            def failing_unlink(path):
                raise unlink_error

            try:
                with (
                    patch(
                        "analisti_2027.integration.os.unlink",
                        side_effect=failing_unlink,
                    ) as unlink_mock,
                    patch(
                        "analisti_2027.integration.os.replace",
                    ) as replace_mock,
                ):
                    with self.assertRaises(OSError) as cm:
                        _atomic_write(target, "same content")

                    # Verify the propagated error IS the unlink_error object
                    self.assertIs(cm.exception, unlink_error)

                    # Verify unlink was called exactly once
                    unlink_mock.assert_called_once()

                    # Verify replace was NOT called
                    replace_mock.assert_not_called()

                    # Verify target unchanged byte-for-byte
                    self.assertEqual(target.read_bytes(), b"same content")

            finally:
                # Clean up the intentionally left temp file using original unlink
                for temp_path in target.parent.glob(f"{target.name}.*.tmp"):
                    original_unlink(temp_path)


if __name__ == "__main__":
    unittest.main()