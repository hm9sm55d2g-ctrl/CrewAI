import contextlib
import io
import json
import unittest
from unittest.mock import patch

from analisti_2027.audit_logging import emit_audit


class AuditLoggingTests(unittest.TestCase):
    def test_all_markers_emit_identical_stdout_and_log(self):
        for marker in ("QUALITY_AUDIT", "REPORT_BINDING_AUDIT", "INTEGRATION_AUDIT"):
            with self.subTest(marker=marker):
                payload = {"report_sha256": "a" * 64, "checks_passed": True}
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    with self.assertLogs("analisti_2027.audit", level="WARNING") as captured:
                        emit_audit(marker, payload)
                line = out.getvalue().rstrip("\n")
                self.assertEqual(len(captured.records), 1)
                self.assertEqual(line, captured.records[0].getMessage())
                self.assertEqual(json.loads(line[len(marker) + 1:]), payload)

    def test_stdout_is_flushed(self):
        with patch("builtins.print") as printer:
            with self.assertLogs("analisti_2027.audit", level="WARNING"):
                emit_audit("QUALITY_AUDIT", {})
        printer.assert_called_once_with("QUALITY_AUDIT {}", flush=True)

    def test_invalid_marker_emits_nothing(self):
        with patch("builtins.print") as printer:
            with patch("analisti_2027.audit_logging.LOGGER.warning") as warning:
                with self.assertRaisesRegex(ValueError, "INVALID_AUDIT_MARKER"):
                    emit_audit("OTHER", {})
        printer.assert_not_called()
        warning.assert_not_called()

    def test_nonfinite_payload_emits_nothing(self):
        with patch("builtins.print") as printer:
            with patch("analisti_2027.audit_logging.LOGGER.warning") as warning:
                with self.assertRaises(ValueError):
                    emit_audit("QUALITY_AUDIT", {"value": float("nan")})
        printer.assert_not_called()
        warning.assert_not_called()

    def test_payload_is_not_mutated_and_unicode_roundtrips(self):
        payload = {"errors": [], "note": "criticità"}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertLogs("analisti_2027.audit", level="WARNING"):
                emit_audit("QUALITY_AUDIT", payload)
        self.assertEqual(payload, {"errors": [], "note": "criticità"})
        self.assertEqual(json.loads(out.getvalue().split(" ", 1)[1]), payload)


if __name__ == "__main__":
    unittest.main()
