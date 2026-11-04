"""Offline consistency checks, not certification of financial truth."""
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

SECTIONS = ("Sintesi e stato della validazione", "Evidenze acquisite e riferimenti da consultare", "Vincoli e lacune", "Schede AVGO, NVDA e AMZN", "Scheda Shin-Etsu", "Scenari H1, H2 e H10", "Confronto A/B/C, controlli e I1/I2/I3", "Obiezioni e criticita della revisione", "Prossime verifiche")
END = "FINE REPORT PRELIMINARE"

def iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("INVALID_DATE")
    return date.fromisoformat(value)

def evidence_window(mandate, as_of=None):
    today = datetime.now(timezone.utc).date()
    end = today if as_of is None else iso_day(as_of)
    if end > today:
        raise ValueError("FUTURE_REFERENCE_DATE")
    if "information_start" in mandate or "temporal_policy" in mandate:
        if "information_cutoff" in mandate:
            raise ValueError("AMBIGUOUS_TEMPORAL_POLICY")
        policy = mandate["temporal_policy"]
        expected = {"mode": "rolling", "start_inclusive": True, "end": "execution_date", "timezone": "UTC", "documents_date_field": "publication_date", "market_data_date_field": "observation_date"}
        if not isinstance(policy, dict) or policy != expected or policy.get("start_inclusive") is not True:
            raise ValueError("INVALID_TEMPORAL_POLICY")
        start = iso_day(mandate["information_start"])
        if start > end:
            raise ValueError("INVALID_TEMPORAL_WINDOW")
        return {"mode": "rolling", "start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC"}
    cutoff = iso_day(mandate["information_cutoff"])
    if cutoff > end:
        raise ValueError("FUTURE_CUTOFF")
    return {"mode": "frozen", "start": None, "end": cutoff.isoformat(), "timezone": "UTC"}

def validate_record_dates(record, window):
    published = iso_day(record["publication_date"])
    end = iso_day(window["end"])
    start = iso_day(window["start"]) if window["start"] else None
    kind = record.get("record_type", "document")
    if kind not in ("document", "price", "fx"):
        raise ValueError("INVALID_RECORD_TYPE")
    observed = iso_day(record["observation_date"]) if kind in ("price", "fx") else published
    if published > end or observed > end or (start is not None and observed < start):
        raise ValueError("OUTSIDE_TEMPORAL_WINDOW")
    if kind in ("price", "fx") and published < observed:
        raise ValueError("PUBLICATION_BEFORE_OBSERVATION")
    if "acquisition_date" in record:
        acquired = iso_day(record["acquisition_date"])
        if acquired < published or acquired > end:
            raise ValueError("INVALID_ACQUISITION_DATE")
    reviewed = iso_day(record["reviewed_on"])
    if reviewed < published or (window["mode"] == "rolling" and reviewed > end):
        raise ValueError("INVALID_REVIEW_DATE")

def norm(s):
    s = unicodedata.normalize("NFKD", s)
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split()).casefold()

def has_placeholder_links(text):
    targets = re.findall(r"\[[^\]\n]+\]\(([^)\n]*)\)", text)
    targets += re.findall(r"^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*(.*)$", text, re.M)
    targets += re.findall(r"href\s*=\s*[\"']([^\"']*)[\"']", text, re.I)
    return any((t.strip().split()[0] if t.strip() else "").strip("<>") in ("", "#") for t in targets)

def audit(report, mandate, records, resource_root, *, as_of=None):
    errors, warnings = [], []
    root = Path(resource_root).resolve()
    window = None
    try:
        window = evidence_window(mandate, as_of)
        capital = Decimal(str(mandate["capital_eur"]))
        if not capital.is_finite() or capital != Decimal(3000) or set(mandate["portfolios"]) != {"A", "B", "C"}:
            raise ValueError("capital or portfolios")
        for p in mandate["portfolios"].values():
            amounts = [Decimal(str(v)) for v in p.values()]
            if not amounts or any(not v.is_finite() or v < 0 for v in amounts) or sum(amounts) != capital:
                raise ValueError("budget")
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        errors.append("INVALID_MANDATE_OR_BUDGET")
        window = None
    if not isinstance(records, list):
        errors.append("INVALID_EVIDENCE_REGISTER")
        records = []
    ids, seen = set(), set()
    for record in records:
        try:
            eid = record["id"]
            if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", eid) or eid in seen:
                raise ValueError("id")
            seen.add(eid)
            from urllib.parse import urlparse
            url = urlparse(record["source_url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("url")
            if window is None:
                raise ValueError("window")
            validate_record_dates(record, window)
            snapshot = (root / record["snapshot_path"]).resolve()
            if not snapshot.is_relative_to(root) or not snapshot.is_file():
                raise ValueError("snapshot")
            data = snapshot.read_bytes()
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise ValueError("hash")
            excerpt = record["excerpt"]
            if not isinstance(excerpt, str) or not excerpt.strip() or excerpt not in data.decode("utf-8"):
                raise ValueError("excerpt")
            for field in ("company", "metric", "period", "unit", "currency", "reviewer", "reviewed_on"):
                if not isinstance(record[field], str) or not record[field].strip():
                    raise ValueError(field)
            if not Decimal(str(record["value"])).is_finite() or record.get("human_verified") is not True:
                raise ValueError("value or human review")
            ids.add(eid)
        except (KeyError, TypeError, ValueError, OSError, InvalidOperation, UnicodeError):
            errors.append("INVALID_EVIDENCE_RECORD")
    if not records:
        warnings.append("NO_VERIFIED_EVIDENCE: preliminary analysis only")
    text = report if isinstance(report, str) else ""
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != "# ANALISI PRELIMINARE NON VALIDATA":
        errors.append("INVALID_REPORT_TITLE")
    marker = lines[-1].strip() if lines else ""
    variant = "canonical" if marker == END else ("terminal_period" if marker == END + "." else "missing_or_invalid")
    body_text = text
    if variant == "missing_or_invalid":
        errors.append("MISSING_END_MARKER")
    else:
        body_text = text.rstrip().rsplit("\n", 1)[0] if "\n" in text.rstrip() else ""
        if variant == "terminal_period":
            warnings.append("END_MARKER_TERMINAL_PERIOD_ACCEPTED: original output unchanged")
    if has_placeholder_links(text):
        errors.append("PLACEHOLDER_LINK")
    words = len(text.split())
    if words > 800:
        errors.append("WORD_LIMIT_EXCEEDED")
    heads = list(re.finditer(r"^##[ \t]+(.+)$", body_text, re.M))
    names = [norm(re.sub(r"^\d+[.)]\s*", "", m.group(1))) for m in heads]
    if names != [norm(s) for s in SECTIONS]:
        errors.append("SECTION_SET_OR_ORDER_INVALID")
    for index, head in enumerate(heads):
        body = body_text[head.end():heads[index+1].start() if index+1 < len(heads) else len(body_text)].strip()
        plain = re.sub(r"[\s#*_`>~|\-]+", "", body)
        if not plain or re.fullmatch(r"ND[.!]?", plain, re.I):
            errors.append("EMPTY_SECTION_OR_ND_WITHOUT_REASON")
        if re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", body, re.I):
            errors.append("PLACEHOLDER_CONTENT")
    for eid in re.findall(r"\[E:([A-Za-z0-9_-]+)\]", text):
        if eid not in ids:
            errors.append("UNKNOWN_EVIDENCE_CITATION:" + eid)
    warnings.append("SEMANTIC_REVIEW_REQUIRED: budgets and source consistency do not establish truth, suitability or forecast quality")
    return {"checks_passed": not errors, "financially_validated": False, "word_count": words,
            "evidence_count": len(records), "temporal_window": window, "end_marker_variant": variant,
            "report_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "errors": sorted(set(errors)), "warnings": warnings}

def check_output(result, resource_root, *, as_of=None):
    root = Path(resource_root)
    mandate = json.loads((root / "knowledge/mandato.json").read_text(encoding="utf-8"))
    register = root / "knowledge/evidence_registry.json"
    records = json.loads(register.read_text(encoding="utf-8")) if register.exists() else []
    outcome = audit(result.raw, mandate, records, root, as_of=as_of)
    print("QUALITY_AUDIT " + json.dumps(outcome, ensure_ascii=False))
    if not outcome["checks_passed"]:
        raise ValueError("QUALITY_GATE_FAILED: " + "; ".join(outcome["errors"]))
    return result
