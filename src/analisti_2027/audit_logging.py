"""Emit audit markers on stdout and Python logging."""
import json
import logging

LOGGER = logging.getLogger("analisti_2027.audit")
MARKERS = frozenset(("QUALITY_AUDIT", "REPORT_BINDING_AUDIT", "INTEGRATION_AUDIT"))


def emit_audit(marker, payload):
    if marker not in MARKERS:
        raise ValueError("INVALID_AUDIT_MARKER")
    line = marker + " " + json.dumps(payload, ensure_ascii=False, allow_nan=False)
    print(line, flush=True)
    LOGGER.warning("%s", line)
