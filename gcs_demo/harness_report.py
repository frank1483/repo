"""Read gateway calls without modifying them; write a new JSON summary.

Usage: python -m gcs_demo.harness_report calls.jsonl new_report.json
Rates use all rows in each (feature, harness) group. Latency is upstream
latency_s, excluding queue_wait_s; p95 uses the nearest-rank method.
Old rows without harness are unversioned. Missing/invalid latency is excluded
from percentiles and counted separately. This does not validate client labels.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path


def summarize(records) -> dict:
    groups = {}
    for rec in records:
        if not isinstance(rec, dict):
            raise ValueError("call record must be an object")
        key = (rec.get("feature", "unknown"), rec.get("harness", "unversioned"))
        if not all(isinstance(value, str) for value in key):
            raise ValueError("feature and harness must be strings")
        group = groups.setdefault(key, {"count": 0, "ok_count": 0,
                                        "timeout_count": 0, "latencies": []})
        group["count"] += 1
        group["ok_count"] += rec.get("ok") is True
        error = str(rec.get("error") or "").lower()
        group["timeout_count"] += any(term in error for term in
                                         ("timeout", "timed out", "expired in queue"))
        latency = rec.get("latency_s")
        if (isinstance(latency, (int, float)) and not isinstance(latency, bool)
                and math.isfinite(latency) and latency >= 0):
            group["latencies"].append(latency)
    output = []
    for (feature, harness), group in sorted(groups.items()):
        latencies = sorted(group.pop("latencies"))
        output.append({"feature": feature, "harness": harness, **group,
                       "ok_rate": group["ok_count"] / group["count"],
                       "latency_count": len(latencies),
                       "latency_median_s": statistics.median(latencies) if latencies else None,
                       "latency_p95_s": latencies[math.ceil(.95 * len(latencies)) - 1]
                       if latencies else None})
    return {"latency_basis": "latency_s (excludes queue_wait_s)",
            "p95_method": "nearest_rank", "groups": output}


def report(source, output) -> dict:
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("output must be a new file distinct from input")
    def records():
        with source.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except ValueError as exc:
                        raise ValueError(f"invalid JSONL at line {line_number}") from exc
    result = summarize(records())
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    args = parser.parse_args(argv)
    report(args.source, args.output)


if __name__ == "__main__":
    main()
