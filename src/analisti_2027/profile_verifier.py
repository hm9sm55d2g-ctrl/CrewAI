"""Strict parser for the registered NVIDIA Q2 FY27 GAAP Markdown table.
Does not fetch, admit evidence, or change the mandate publication window.
Other table layouts fail closed. Amazon remains on its legacy verifier.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import re
from .automated_evidence import _day, digest
from .evidence_profiles import resolve_profile


def _plain(cell):
    cell = cell.strip()
    for marker in ("**", "*"):
        if cell.startswith(marker) and cell.endswith(marker) and len(cell) > 2 * len(marker):
            return cell[len(marker):-len(marker)].strip()
    return cell


def _tables(text):
    tables, current = [], []
    for number, line in enumerate(text.splitlines(), 1):
        raw = line.strip()
        if raw.startswith("|") and raw.endswith("|"):
            current.append((number, raw, [_plain(c) for c in raw[1:-1].split("|")]))
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def _table_value(text, profile, spec):
    matches = [(i, t) for i, t in enumerate(_tables(text))
        if len(t[0][2]) >= 2 and all(c == "GAAP" for c in t[0][2])]
    if len(matches) != 1:
        raise ValueError("GAAP_TABLE_MISSING_OR_AMBIGUOUS")
    table_index, table = matches[0]
    width = len(table[0][2])
    if any(len(row[2]) != width for row in table):
        raise ValueError("INVALID_FINANCIAL_TABLE")
    rows = [row for row in table if not all(re.fullmatch(r":?-{2,}:?", c) for c in row[2])]
    if len(rows) < 3 or rows[1][2][0] != "($ in millions, except earnings per share)":
        raise ValueError("GAAP_TABLE_UNITS_MISMATCH")
    header = rows[1][2]
    if header.count(profile["column_label"]) != 1 or header.index(profile["column_label"]) == 0:
        raise ValueError("CURRENT_COLUMN_MISSING_OR_AMBIGUOUS")
    column = header.index(profile["column_label"])
    selected = [row for row in rows[2:] if row[2][0] == spec["row_label"]]
    if len(selected) != 1:
        raise ValueError("METRIC_ROW_MISSING_OR_AMBIGUOUS")
    line, raw, cells = selected[0]
    token = cells[column]
    if not re.fullmatch(r"\$?-?(?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d+)?", token):
        raise ValueError("INVALID_TABLE_VALUE")
    value = Decimal(token.replace("$", "").replace(",", ""))
    selector = {"basis": "GAAP", "table_index": table_index, "row_line": line,
        "row_label": spec["row_label"], "column_index": column,
        "column_label": profile["column_label"], "unit": "million", "currency": "USD"}
    return value, raw, selector


def verify_profile_candidate(candidate, snapshot_text, publisher_text, *, publication_date, reviewed_on, as_of):
    c = deepcopy(candidate)
    if c.get("human_verified") is not False or c.get("reviewer") is not None or c.get("reviewed_on") is not None:
        raise ValueError("CANDIDATE_REVIEW_STATE_REQUIRED")
    if c.get("company") != "NVDA" or c.get("record_type") != "document":
        raise ValueError("UNSUPPORTED_SOURCE_OR_TYPE")
    if not isinstance(c.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", c["id"]):
        raise ValueError("INVALID_ID")
    if not isinstance(c.get("metric"), str):
        raise ValueError("UNSUPPORTED_PROFILE_METRIC")
    profile = resolve_profile(c["company"], c["source_url"], metric=c["metric"])
    if profile["profile_id"] != "nvda-2027q2-gaap-v1":
        raise ValueError("UNIMPLEMENTED_DOCUMENT_PROFILE")
    if publication_date != profile["publication_date"] or c["publication_date"] != publication_date:
        raise ValueError("PUBLICATION_MISMATCH")
    if not _day(publication_date) <= _day(c["acquisition_date"]) <= _day(reviewed_on) <= _day(as_of) <= date.today():
        raise ValueError("INVALID_CHRONOLOGY")
    if not isinstance(snapshot_text, str) or hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest() != c.get("sha256"):
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    if not isinstance(publisher_text, str) or not publisher_text.strip() or len(publisher_text.encode("utf-8")) > 2000000:
        raise ValueError("PUBLISHER_TEXT_REQUIRED")
    excerpt = c.get("excerpt")
    if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in snapshot_text or excerpt not in publisher_text:
        raise ValueError("EXCERPT_MISMATCH")
    spec = profile["metrics"][c["metric"]]
    if any(c.get(k) != spec[k] for k in ("period", "unit", "currency", "basis")):
        raise ValueError("PERIOD_UNIT_CURRENCY_BASIS_MISMATCH")
    title = "NVIDIA Announces Financial Results for Second Quarter Fiscal 2027"
    if title not in publisher_text or "August 26, 2026" not in publisher_text or not re.search(r"second quarter ended July 26, 2026\b", publisher_text, re.I):
        raise ValueError("DOCUMENT_PERIOD_OR_IDENTITY_MISMATCH")
    value, row, selector = _table_value(publisher_text, profile, spec)
    if excerpt.strip() != row:
        raise ValueError("EXCERPT_SELECTOR_MISMATCH")
    try:
        supplied = Decimal(str(c["value"]))
    except (InvalidOperation, ValueError):
        raise ValueError("INVALID_VALUE") from None
    if isinstance(c["value"], bool) or not supplied.is_finite() or supplied != value:
        raise ValueError("VALUE_MISMATCH")
    return {"schema_version": 1, "review_kind": "automated", "status": "checks_passed",
        "policy_version": "profile-table-v1", "verifier": "profile_table_verifier",
        "profile_id": profile["profile_id"], "profile_sha256": digest(profile),
        "reviewed_on": reviewed_on, "candidate_id": c["id"], "candidate_sha256": digest(c),
        "snapshot_sha256": c["sha256"],
        "publisher_text_sha256": hashlib.sha256(publisher_text.encode("utf-8")).hexdigest(),
        "source_url": c["source_url"], "publication_date": publication_date, "selector": selector,
        "human_verified": False, "financially_validated": False,
        "checks": ["source_scope", "chronology", "snapshot_integrity", "excerpt_match", "document_identity", "value", "unit", "currency", "period", "basis", "table_selector"]}
