"""Deterministic verification of selected Amazon release excerpts.
The caller must supply publisher text acquired by a trusted acquisition adapter.
This module neither fetches documents nor authenticates their publisher, and does
not admit records to the registry or certify financial truth.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
import re

POLICY_VERSION = "amazon-selected-excerpts-v1"
SOURCE_URL = "https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-Third-Quarter-Results/default.aspx"
SPECS = {
    "net_sales": ("Three months ended 2026-09-30", r"Net sales increased [0-9]+% to \$([0-9]+(?:\.[0-9]+)?) billion in the third quarter"),
    "operating_income": ("Three months ended 2026-09-30", r"Operating income increased to \$([0-9]+(?:\.[0-9]+)?) billion in the third quarter"),
    "operating_cash_flow": ("Trailing twelve months ended 2026-09-30", r"Operating cash flow increased [0-9]+% to \$([0-9]+(?:\.[0-9]+)?) billion for the trailing twelve months"),
}

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()

def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("INVALID_DATE")
    return date.fromisoformat(value)

def verify_candidate(candidate, snapshot_text, publisher_text, *, publication_date, reviewed_on, as_of):
    """Return an automated receipt, not a human approval or admitted record.

    publication_date must come from the acquisition adapter's parsed publisher
    metadata, not from a model or the candidate. Capture and receipt persistence
    remain the caller's responsibility. Only the explicit release/metrics below
    are supported. Ambiguous or changed wording fails closed.
    """
    c = deepcopy(candidate)
    if c.get("human_verified") is not False or c.get("reviewer") is not None or c.get("reviewed_on") is not None:
        raise ValueError("CANDIDATE_REVIEW_STATE_REQUIRED")
    if c.get("source_url") != SOURCE_URL or c.get("company") != "AMZN" or c.get("record_type") != "document":
        raise ValueError("UNSUPPORTED_SOURCE_OR_TYPE")
    if not isinstance(c.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", c["id"]):
        raise ValueError("INVALID_ID")
    published = _day(publication_date)
    acquired, reviewed, latest = (_day(x) for x in (c["acquisition_date"], reviewed_on, as_of))
    if published != _day("2026-10-29") or c["publication_date"] != publication_date:
        raise ValueError("PUBLICATION_MISMATCH")
    if not published <= acquired <= reviewed <= latest <= date.today():
        raise ValueError("INVALID_CHRONOLOGY")
    if not isinstance(snapshot_text, str) or hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest() != c.get("sha256"):
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    if not isinstance(publisher_text, str) or not publisher_text.strip():
        raise ValueError("PUBLISHER_TEXT_REQUIRED")
    excerpt = c.get("excerpt")
    if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in snapshot_text or excerpt not in publisher_text:
        raise ValueError("EXCERPT_MISMATCH")
    if c.get("metric") not in SPECS:
        raise ValueError("UNSUPPORTED_METRIC")
    period, pattern = SPECS[c["metric"]]
    if c.get("period") != period or c.get("unit") != "billion" or c.get("currency") != "USD":
        raise ValueError("PERIOD_UNIT_CURRENCY_MISMATCH")
    values = re.findall(pattern, publisher_text)
    extracted = re.findall(pattern, excerpt)
    if len(values) != 1 or len(extracted) != 1 or values != extracted:
        raise ValueError("AMBIGUOUS_OR_MISSING_VALUE")
    if isinstance(c.get("value"), bool):
        raise ValueError("INVALID_VALUE")
    value = Decimal(str(c["value"]))
    if not value.is_finite() or value != Decimal(values[0]):
        raise ValueError("VALUE_MISMATCH")
    return {
        "schema_version": 1, "review_kind": "automated", "status": "checks_passed",
        "policy_version": POLICY_VERSION, "verifier": "amazon_excerpt_verifier",
        "reviewed_on": reviewed_on, "candidate_id": c["id"],
        "candidate_sha256": digest(c), "snapshot_sha256": c["sha256"],
        "publisher_text_sha256": hashlib.sha256(publisher_text.encode("utf-8")).hexdigest(),
        "source_url": SOURCE_URL, "publication_date": publication_date,
        "human_verified": False, "financially_validated": False,
        "checks": ["source_scope", "chronology", "snapshot_integrity", "excerpt_match", "value", "unit", "currency", "period"],
    }

def validate_receipt(candidate, snapshot_text, publisher_text, receipt, *, as_of):
    if not isinstance(receipt, dict):
        raise ValueError("AUTOMATED_RECEIPT_REQUIRED")
    expected = verify_candidate(candidate, snapshot_text, publisher_text,
        publication_date=receipt.get("publication_date"), reviewed_on=receipt.get("reviewed_on"), as_of=as_of)
    if receipt != expected:
        raise ValueError("STALE_OR_INVALID_RECEIPT")
    return deepcopy(receipt)
