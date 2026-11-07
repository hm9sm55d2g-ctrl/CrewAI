"""Compare original AMP Status.result with hashes from same-run quality logs.
Artifact provenance must be checked separately; this tool never starts a run.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def compare(status, log):
    raw = status.get("result")
    if not isinstance(raw, str):
        raise ValueError("Status.result must be the original JSON string, not null or an object")
    hashes = set()
    for line in log.splitlines():
        marker = "QUALITY_AUDIT "
        if marker not in line:
            continue
        record, _ = json.JSONDecoder().raw_decode(line.split(marker, 1)[1].lstrip())
        value = record.get("report_sha256")
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("Invalid or missing QUALITY_AUDIT.report_sha256")
        hashes.add(value)
    if len(hashes) != 1:
        raise ValueError("Need exactly one distinct quality report hash; isolate logs for one run")
    expected = next(iter(hashes))
    actual = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return {
        "quality_report_sha256": expected,
        "status_result_sha256": actual,
        "exact_match": actual == expected,
        "normalization": "none; UTF-8 of decoded JSON result string",
        "same_run_proven": False,
        "provenance_note": "Check AMP execution ID and deployment separately; matching content alone does not prove provenance.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("status_json", type=Path)
    parser.add_argument("quality_log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.status_json.read_text(encoding="utf-8")),
                     args.quality_log.read_text(encoding="utf-8"))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["exact_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
