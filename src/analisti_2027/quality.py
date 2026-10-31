"""Offline consistency checks, NOT certification of financial truth."""
import hashlib
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

SECTIONS = ("Sintesi e stato della validazione", "Evidenze acquisite e riferimenti da consultare", "Vincoli e lacune", "Schede AVGO, NVDA e AMZN", "Scheda Shin-Etsu", "Scenari H1, H2 e H10", "Confronto A/B/C, controlli e I1/I2/I3", "Obiezioni e criticita della revisione", "Prossime verifiche")
END = "FINE REPORT PRELIMINARE"

def norm(s):
    s = unicodedata.normalize("NFKD", s)
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split()).casefold()

def audit(report, mandate, records, resource_root):
    errors, warnings = [], []
    root = Path(resource_root).resolve()
    try:
        cutoff = date.fromisoformat(mandate["information_cutoff"])
        capital = Decimal(str(mandate["capital_eur"]))
        if not capital.is_finite() or capital != Decimal(3000):
            raise ValueError("capital")
        if set(mandate["portfolios"]) != {"A", "B", "C"}:
            raise ValueError("portfolios")
        for p in mandate["portfolios"].values():
            amounts = [Decimal(str(v)) for v in p.values()]
            if not amounts or any(not v.is_finite() or v < 0 for v in amounts) or sum(amounts) != capital:
                raise ValueError("budget")
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        errors.append("INVALID_MANDATE_OR_BUDGET")
        cutoff = None
    if not isinstance(records, list):
        errors.append("INVALID_EVIDENCE_REGISTER")
        records = []
    ids = set()
    for record in records:
        try:
            eid = record["id"]
            if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", eid) or eid in ids:
                raise ValueError("id")
            ids.add(eid)
            from urllib.parse import urlparse
            url = urlparse(record["source_url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("url")
            published = date.fromisoformat(record["publication_date"])
            if cutoff is None or published > cutoff:
                raise ValueError("cutoff")
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
            value = Decimal(str(record["value"]))
            if not value.is_finite():
                raise ValueError("value")
            date.fromisoformat(record["reviewed_on"])
            if record.get("human_verified") is not True:
                raise ValueError("human_review")
        except (KeyError, TypeError, ValueError, OSError, InvalidOperation, UnicodeError):
            errors.append("INVALID_EVIDENCE_RECORD")
    if not records:
        warnings.append("NO_VERIFIED_EVIDENCE: preliminary analysis only")
    text = report if isinstance(report, str) else ""
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != "# ANALISI PRELIMINARE NON VALIDATA":
        errors.append("INVALID_REPORT_TITLE")
    if not lines or lines[-1].strip() != END:
        errors.append("MISSING_END_MARKER")
    words = len(text.split())
    if words > 800:
        errors.append("WORD_LIMIT_EXCEEDED")
    heads = list(re.finditer(r"^##[ \t]+(.+)$", text, re.M))
    names = [norm(re.sub(r"^\d+[.)]\s*", "", m.group(1))) for m in heads]
    if names != [norm(s) for s in SECTIONS]:
        errors.append("SECTION_SET_OR_ORDER_INVALID")
    for i, h in enumerate(heads):
        body = text[h.end():heads[i+1].start() if i+1 < len(heads) else len(text)].replace(END, "").strip()
        plain = re.sub(r"[\s#*_`>~|\-]+", "", body)
        if not plain or re.fullmatch(r"ND[.!]?", plain, re.I):
            errors.append("EMPTY_SECTION_OR_ND_WITHOUT_REASON")
        if re.search(r"\b(?:TODO|TBD|PLACEHOLDER)\b", body, re.I):
            errors.append("PLACEHOLDER_CONTENT")
    for eid in re.findall(r"\[E:([A-Za-z0-9_-]+)\]", text):
        if eid not in ids:
            errors.append("UNKNOWN_EVIDENCE_CITATION:" + eid)
    warnings.append("SEMANTIC_REVIEW_REQUIRED: budgets and source consistency do not establish truth, suitability or forecast quality")
    return {"checks_passed": not errors, "financially_validated": False,
            "word_count": words, "evidence_count": len(records),
            "errors": sorted(set(errors)), "warnings": warnings}

def check_output(result, resource_root):
    root = Path(resource_root)
    mandate = json.loads((root / "knowledge/mandato.json").read_text(encoding="utf-8"))
    register = root / "knowledge/evidence_registry.json"
    records = json.loads(register.read_text(encoding="utf-8")) if register.exists() else []
    outcome = audit(result.raw, mandate, records, root)
    print("QUALITY_AUDIT " + json.dumps(outcome, ensure_ascii=False))
    if not outcome["checks_passed"]:
        raise ValueError("QUALITY_GATE_FAILED: " + "; ".join(outcome["errors"]))
    return result
