"""Offline automatic-admission helpers; captured source authenticity is external.
Never infer human review or financial certification from a machine receipt.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from .automated_evidence import validate_receipt


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def _read(root, name):
    base = Path(root).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError("INVALID_REVIEW_RESOURCE_PATH")
    return path.read_text(encoding="utf-8")


def automated_record(candidate, snapshot_text, publisher_text, receipt, *, as_of):
    checked = validate_receipt(candidate, snapshot_text, publisher_text, receipt, as_of=as_of)
    record = deepcopy(candidate)
    record.update(snapshot_path="knowledge/snapshots/" + candidate["sha256"] + ".txt",
                  human_verified=False, reviewer=checked["verifier"],
                  reviewed_on=checked["reviewed_on"], review_status="automated_verified",
                  verification={"candidate": deepcopy(candidate), "receipt": checked,
                    "publisher_snapshot_path": "knowledge/snapshots/" + checked["publisher_text_sha256"] + ".txt"})
    return record


def validate_automated_record(record, root, *, as_of):
    if record.get("human_verified") is not False or record.get("review_status") != "automated_verified":
        raise ValueError("AUTOMATED_PROVENANCE_REQUIRED")
    verification = record["verification"]
    candidate, receipt = verification["candidate"], verification["receipt"]
    snapshot = _read(root, record["snapshot_path"])
    publisher = _read(root, verification["publisher_snapshot_path"])
    expected = automated_record(candidate, snapshot, publisher, receipt, as_of=as_of)
    if record != expected:
        raise ValueError("AUTOMATED_RECORD_MISMATCH")
    return deepcopy(receipt)


def automatic_promotion_plan(candidates, receipts, snapshots, publisher_texts, existing, *, root, start, as_of):
    """Plan mirrored resources. Existing records must pass the current quality gate.
    No writes, network access, or human approval fabrication occur here.
    """
    from .financial_review import _day
    from .quality import SECTIONS, END, audit
    first, last = _day(start), _day(as_of)
    if first > last or last > date.today():
        raise ValueError("INVALID_WINDOW")
    if not isinstance(candidates, list) or not isinstance(existing, list):
        raise ValueError("INVALID_RECORD_LIST")
    mandate = json.loads(_read(root, "knowledge/mandato.json"))
    probe = "# ANALISI PRELIMINARE NON VALIDATA\n\n" + "\n\n".join("## " + s + "\nND: controllo preliminare." for s in SECTIONS) + "\n\n" + END
    outcome = audit(probe, mandate, existing, root, as_of=as_of)
    if not outcome["checks_passed"]:
        raise ValueError("EXISTING_RECORDS_OR_MANDATE_INVALID")
    seen, records, files = set(), deepcopy(existing), {}
    for record in records:
        eid = record["id"]
        if eid in seen:
            raise ValueError("DUPLICATE_OR_INVALID_ID")
        seen.add(eid)
        paths = [record["snapshot_path"]]
        if record.get("review_status") == "automated_verified":
            paths.append(record["verification"]["publisher_snapshot_path"])
        for name in paths:
            text = _read(root, name)
            target = "knowledge/snapshots/" + hashlib.sha256(text.encode("utf-8")).hexdigest() + ".txt"
            if name != target:
                raise ValueError("EXISTING_SNAPSHOT_NOT_CONTENT_ADDRESSED")
            files[target] = text
            files["src/analisti_2027/" + target] = text
    for candidate in candidates:
        eid = candidate["id"]
        if eid in seen:
            raise ValueError("DUPLICATE_OR_INVALID_ID")
        seen.add(eid)
        if not first <= _day(candidate["publication_date"]) <= last:
            raise ValueError("OUTSIDE_WINDOW")
        text = snapshots[candidate["snapshot_path"]]
        publisher = publisher_texts[eid]
        record = automated_record(candidate, text, publisher, receipts[eid], as_of=as_of)
        for name, value in ((record["snapshot_path"], text), (record["verification"]["publisher_snapshot_path"], publisher)):
            if name in files and files[name] != value:
                raise ValueError("RESOURCE_COLLISION")
            files[name] = value
            files["src/analisti_2027/" + name] = value
        records.append(record)
    registry = json.dumps(records, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    files["knowledge/evidence_registry.json"] = registry
    files["src/analisti_2027/knowledge/evidence_registry.json"] = registry
    with __import__("tempfile").TemporaryDirectory() as directory:
        target = Path(directory)
        (target / "knowledge").mkdir()
        (target / "knowledge/mandato.json").write_text(json.dumps(mandate), encoding="utf-8")
        for name, text in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        if not audit(probe, mandate, records, target, as_of=as_of)["checks_passed"]:
            raise ValueError("AUTOMATIC_PROMOTION_QUALITY_GATE_FAILED")
    return files


def final_review_summary(report, context, root):
    """Bind an approval subject to the exact final text and its admitted inputs."""
    records = context["evidence_records"]
    stored = Path(root) / "knowledge/evidence_registry.json"
    registered = json.loads(stored.read_text(encoding="utf-8")) if stored.exists() else []
    if digest(records) != digest(registered):
        raise ValueError("REVIEW_CONTEXT_REGISTER_MISMATCH")
    counts = {"human": 0, "automated": 0}
    for record in records:
        if record.get("human_verified") is True and record.get("review_status") != "automated_verified":
            counts["human"] += 1
        else:
            validate_automated_record(record, root, as_of=context["as_of"])
            counts["automated"] += 1
    subject = {"report_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest(),
        "evidence_sha256": digest(records), "scenario_sha256": digest(context.get("scenario_bundle")),
        "input_sha256": context["input_sha256"], "as_of": context["as_of"],
        "evidence_review_counts": counts, "financially_validated": False}
    return dict(subject, subject_sha256=digest(subject), financial_review_status="pending_final_approval")
