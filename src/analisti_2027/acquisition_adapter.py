"""Pure adapter for acquired extracted text, not a network downloader.
Preserves capture and derived text; authenticity and durable writes are external.
Existing direct verifier calls remain strict and unchanged.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from .automated_evidence import SOURCE_URL, verify_candidate, digest
from .evidence_profiles import COMPANIES, resolve_profile

NORMALIZATION_POLICY = "amazon-bold-labels-v1"
BOLD_LABEL = re.compile(r"(?<!\*)\*\*(Net sales|Operating income|Operating cash flow)\*\*(?!\*)")


def sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _day(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_CAPTURE_DATE")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("INVALID_CAPTURE_DATE")
    return parsed


def _capture_profile(source_url, publication_date):
    for company in COMPANIES:
        try:
            profile = resolve_profile(company, source_url)
        except ValueError:
            continue
        if publication_date != profile["publication_date"]:
            raise ValueError("PUBLICATION_MISMATCH")
        return profile
    raise ValueError("UNSUPPORTED_CAPTURE_SOURCE")


def prepare_capture(raw_text, *, source_url, publication_date, acquired_on):
    profile = _capture_profile(source_url, publication_date)
    if not isinstance(raw_text, str) or not raw_text.strip() or len(raw_text.encode("utf-8")) > 2000000:
        raise ValueError("INVALID_CAPTURE_TEXT")
    if not _day(publication_date) <= _day(acquired_on) <= date.today():
        raise ValueError("INVALID_CAPTURE_CHRONOLOGY")
    is_amazon = profile["company"] == "AMZN"
    normalized = BOLD_LABEL.sub(r"\1", raw_text) if is_amazon else raw_text
    policy = NORMALIZATION_POLICY if is_amazon else "preserve-markdown-tables-v1"
    return {"schema_version": 2, "normalization_policy": policy,
        "company": profile["company"], "profile_id": profile["profile_id"],
        "profile_sha256": digest(profile),
        "source_url": source_url, "publication_date": publication_date,
        "acquired_on": acquired_on, "raw_text": raw_text,
        "normalized_text": normalized, "raw_sha256": sha256(raw_text),
        "normalized_sha256": sha256(normalized)}


def verify_acquired_candidate(candidate, snapshot_text, capture, *, reviewed_on, as_of):
    """Return receipt plus mirrored capture artifacts; do not admit or write records.
    The receipt binds normalized extracted text, not original HTML/PDF bytes.
    Feed receipt and capture['normalized_text'] to automatic_promotion_plan;
    preserve returned artifacts alongside that plan. No kickoff is wired here.
    """
    if not isinstance(capture, dict):
        raise ValueError("CAPTURE_REQUIRED")
    expected = prepare_capture(capture["raw_text"], source_url=capture["source_url"],
        publication_date=capture["publication_date"], acquired_on=capture["acquired_on"])
    if type(capture.get("schema_version")) is not int:
        raise ValueError("CAPTURE_INTEGRITY_MISMATCH")
    company = expected["company"]
    if capture.get("schema_version") == 1:
        if company != "AMZN":
            raise ValueError("LEGACY_CAPTURE_COMPANY_UNSUPPORTED")
        expected = {k: v for k, v in expected.items() if k not in ("company", "profile_id", "profile_sha256")}
        expected["schema_version"] = 1
    if capture != expected:
        raise ValueError("CAPTURE_INTEGRITY_MISMATCH")
    if candidate["company"] != company:
        raise ValueError("CAPTURE_COMPANY_MISMATCH")
    if candidate["source_url"] != capture["source_url"]:
        raise ValueError("CAPTURE_SOURCE_MISMATCH")
    if not _day(candidate["acquisition_date"]) <= _day(capture["acquired_on"]) <= _day(reviewed_on) <= _day(as_of) <= date.today():
        raise ValueError("INVALID_CAPTURE_CHRONOLOGY")
    receipt = verify_candidate(candidate, snapshot_text, capture["normalized_text"],
        publication_date=capture["publication_date"], reviewed_on=reviewed_on, as_of=as_of)
    raw_path = "knowledge/snapshots/" + capture["raw_sha256"] + ".txt"
    normalized_path = "knowledge/snapshots/" + capture["normalized_sha256"] + ".txt"
    manifest = {k: v for k, v in capture.items() if k not in ("raw_text", "normalized_text")}
    manifest.update(raw_snapshot_path=raw_path, normalized_snapshot_path=normalized_path, receipt=receipt)
    content = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    manifest_path = "knowledge/acquisitions/" + sha256(content) + ".json"
    files = {raw_path: capture["raw_text"], normalized_path: capture["normalized_text"], manifest_path: content}
    files.update({"src/analisti_2027/" + path: text for path, text in list(files.items())})
    return {"capture": deepcopy(capture), "receipt": receipt, "artifacts": files}
