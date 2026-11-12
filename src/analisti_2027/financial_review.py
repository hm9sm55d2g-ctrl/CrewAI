"""Offline review plans. Attestations require trusted human provenance outside this module.
No filesystem writes, broker actions, or automatic financial certification.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from urllib.parse import urlparse


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("INVALID_DATE")
    return date.fromisoformat(value)


def _approval(value, expected, earliest, latest):
    if not isinstance(value, dict) or value.get("decision") != "approve" or value.get("human_reviewed") is not True:
        raise ValueError("HUMAN_REVIEW_REQUIRED")
    if value.get("subject_sha256") != expected:
        raise ValueError("STALE_REVIEW")
    if not isinstance(value.get("reviewer"), str) or not value["reviewer"].strip():
        raise ValueError("REVIEWER_REQUIRED")
    if not earliest <= _day(value.get("reviewed_on")) <= latest:
        raise ValueError("INVALID_REVIEW_DATE")


def promotion_plan(candidates, approvals, snapshots, existing, *, start, as_of):
    """Return mirrored file contents; caller must authorize and atomically commit the plan.
    approvals maps candidate IDs to externally obtained human attestations.
    Snapshot hashes cover supplied text, not authenticity of the publisher.
    """
    first, last = _day(start), _day(as_of)
    if first > last or last > date.today():
        raise ValueError("INVALID_WINDOW")
    if not isinstance(candidates, list) or not isinstance(existing, list):
        raise ValueError("INVALID_RECORD_LIST")
    records, files, seen = [], {}, set()
    for candidate, incoming in [(r, False) for r in existing] + [(r, True) for r in candidates]:
        record = deepcopy(candidate)
        eid = record["id"]
        if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", eid) or eid in seen:
            raise ValueError("DUPLICATE_OR_INVALID_ID")
        seen.add(eid)
        published = _day(record["publication_date"])
        kind = record.get("record_type", "document")
        if kind not in ("document", "price", "fx"):
            raise ValueError("INVALID_RECORD_TYPE")
        observed = _day(record["observation_date"]) if kind != "document" else published
        acquired = _day(record["acquisition_date"])
        if not first <= observed <= published <= acquired <= last:
            raise ValueError("OUTSIDE_WINDOW_OR_INVALID_CHRONOLOGY")
        for key in ("company", "metric", "period", "unit", "currency"):
            if not isinstance(record.get(key), str) or not record[key].strip():
                raise ValueError("MISSING_METADATA")
        if isinstance(record["value"], bool) or not Decimal(str(record["value"])).is_finite():
            raise ValueError("INVALID_VALUE")
        url = urlparse(record["source_url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("INVALID_SOURCE_URL")
        text = snapshots[record["snapshot_path"]]
        if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != record["sha256"]:
            raise ValueError("SNAPSHOT_HASH_MISMATCH")
        if not isinstance(record.get("excerpt"), str) or not record["excerpt"].strip() or record["excerpt"] not in text:
            raise ValueError("EXCERPT_MISMATCH")
        if incoming:
            approval = approvals.get(eid)
            _approval(approval, digest(candidate), acquired, last)
            record.update(human_verified=True, reviewer=approval["reviewer"], reviewed_on=approval["reviewed_on"], review_status="approved")
        elif record.get("human_verified") is not True or not isinstance(record.get("reviewer"), str) or not record["reviewer"].strip() or not acquired <= _day(record.get("reviewed_on")) <= last:
            raise ValueError("EXISTING_RECORD_NOT_REVIEWED")
        target = "knowledge/snapshots/" + record["sha256"] + ".txt"
        record["snapshot_path"] = target
        files[target] = text
        files["src/analisti_2027/" + target] = text
        records.append(record)
    registry = json.dumps(records, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    files["knowledge/evidence_registry.json"] = registry
    files["src/analisti_2027/knowledge/evidence_registry.json"] = registry
    return files


def review_subject(report, evidence, scenarios):
    """Bind review to exact report bytes and full evidence/scenario metadata."""
    if not isinstance(report, str) or not report:
        raise ValueError("REPORT_REQUIRED")
    if not isinstance(evidence, list) or not isinstance(scenarios, dict):
        raise ValueError("INVALID_REVIEW_INPUTS")
    if scenarios.get("data_kind") != "synthetic":
        raise ValueError("SCENARIOS_MUST_REMAIN_SYNTHETIC")
    for record in evidence:
        if record.get("record_type", "document") not in ("document", "price", "fx"):
            raise ValueError("OBSERVED_EVIDENCE_TYPE_REQUIRED")
        if record.get("human_verified") is not True:
            raise ValueError("UNREVIEWED_EVIDENCE")
    return {"report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
            "evidence_sha256": digest(evidence), "scenario_sha256": digest(scenarios),
            "observed_record_ids": [r["id"] for r in evidence],
            "scenario_data_kind": "synthetic", "financially_validated": False}


def review_status(report, evidence, scenarios, approval, *, as_of):
    subject = review_subject(report, evidence, scenarios)
    latest = _day(as_of)
    if latest > date.today():
        raise ValueError("FUTURE_REFERENCE_DATE")
    if approval is None:
        return dict(subject, financial_review_status="pending")
    earliest = max((_day(r["reviewed_on"]) for r in evidence), default=latest)
    _approval(approval, digest(subject), earliest, latest)
    return dict(subject, financial_review_status="attested", reviewer=approval["reviewer"], reviewed_on=approval["reviewed_on"])
