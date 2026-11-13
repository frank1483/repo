"""JSONL event retention and audit; sequence numbers always come from the engine."""
import json
from copy import deepcopy
from pathlib import Path
from . import RULE_VERSION
from .units import finite
from .state_machine import SEVERITY_ZH

CORE_FIELDS = ("alert_id", "sensed_t", "recv_t", "predictor", "severity", "rule_version", "status")
EXTENDED_FIELDS = ("route_version", "data_status", "landing", "evidence", "recommendation",
                   "reason_codes", "model_selection", "source", "operator_disposition", "engine_seq")


def _seq(row):
    n = row.get("engine_seq")
    return n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else None


def _core_ok(row):
    return (all(k in row for k in CORE_FIELDS)
            and all(isinstance(row[k], str) and bool(row[k].strip())
                    for k in ("alert_id", "predictor", "rule_version", "status"))
            and finite(row["sensed_t"]) and finite(row["recv_t"])
            and row["sensed_t"] <= row["recv_t"]
            and isinstance(row["severity"], int) and not isinstance(row["severity"], bool)
            and row["severity"] in SEVERITY_ZH
            and row["rule_version"] == RULE_VERSION
            and row["status"] in ("raise", "update", "resolve"))


def _extended_ok(row):
    return (all(k in row for k in EXTENDED_FIELDS)
            and isinstance(row["route_version"], (int, str))
            and not isinstance(row["route_version"], bool)
            and isinstance(row["data_status"], dict) and bool(row["data_status"])
            and all(v in ("valid", "invalid", "missing", "stale", "unknown")
                    for v in row["data_status"].values())
            and isinstance(row["landing"], dict)
            and all(finite(row["landing"].get(k)) for k in
                    ("median_pct", "conservative_pct", "optimistic_pct"))
            and isinstance(row["evidence"], list) and bool(row["evidence"])
            and all(isinstance(e, dict) and all(k in e for k in
                    ("id", "option_id", "metric", "value", "unit", "segment", "relation"))
                    for e in row["evidence"])
            and (row["recommendation"] is None or isinstance(row["recommendation"], str))
            and isinstance(row["reason_codes"], list)
            and all(isinstance(r, str) and bool(r) for r in row["reason_codes"])
            and (row["model_selection"] is None or isinstance(row["model_selection"], str))
            and row["source"] in ("rule", "llm")
            and (row["operator_disposition"] is None or isinstance(row["operator_disposition"], str))
            and _seq(row) is not None)


class AlertLog:
    def __init__(self, path=None):
        self.path = None if path is None else Path(path)
        self.rows = []
        self.last_snapshot_t = None

    def _write(self, row):
        encoded = json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if self.path is not None:
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded + "\n")
        self.rows.append(deepcopy(row))
        return deepcopy(row)

    def append(self, event):
        if not isinstance(event, dict) or _seq(event) is None or not _core_ok(event):
            raise ValueError("event needs an engine-owned sequence and valid core fields")
        return self._write(event)

    def snapshot(self, now, predictions):
        """First call writes immediately; later calls write at most once per 10 s.

        Caller must schedule this method. No background thread or wall clock IO.
        Snapshots have no engine_seq and are excluded from event denominators.
        """
        if not finite(now) or (self.last_snapshot_t is not None and now < self.last_snapshot_t):
            raise ValueError("monotonic snapshot time required")
        if self.last_snapshot_t is not None and now - self.last_snapshot_t < 10.0:
            return None
        row = self._write({"status": "snapshot", "snapshot_t": now,
                           "rule_version": RULE_VERSION, "predictions": predictions})
        self.last_snapshot_t = now
        return row


def audit(engine_events, log_rows):
    """Rates are fractions of actual engine outputs, not present log rows.

    No outputs => undefined rates (None), never a fabricated 100%. Duplicate
    retention cannot inflate completeness. This does not measure missed alerts.
    """
    expected = {}
    for event in engine_events:
        seq = _seq(event)
        if seq is None or seq in expected:
            raise ValueError("engine events require unique positive sequences")
        expected[seq] = event
    rows = {}
    invalid_sequence_rows = 0
    for row in log_rows:
        if row.get("status") == "snapshot":
            continue
        seq = _seq(row)
        if seq is None:
            invalid_sequence_rows += 1
        else:
            rows.setdefault(seq, []).append(row)
    core = extended = 0
    for seq, event in expected.items():
        matches = rows.get(seq, [])
        if len(matches) != 1:
            continue
        row = matches[0]
        identity = all(row.get(k) == event.get(k) for k in (*CORE_FIELDS, "alert_version"))
        if identity and _core_ok(row):
            core += 1
            if _extended_ok(row):
                extended += 1
    n = len(expected)
    ordered = sorted(expected)
    # Bound by actual input size rather than allocating range(max_seq) for bad data.
    gaps = [(a + 1, b - 1) for a, b in zip(ordered, ordered[1:]) if b > a + 1]
    return {"engine_event_count": n, "core_valid_count": core, "extended_valid_count": extended,
            "core_valid_rate": core / n if n else None,
            "extended_valid_rate": extended / n if n else None,
            "missing_sequences": sorted(set(expected) - set(rows)),
            "unexpected_sequences": sorted(set(rows) - set(expected)),
            "duplicate_sequences": sorted(k for k, v in rows.items() if len(v) > 1),
            "engine_sequence_gaps": gaps, "invalid_sequence_rows": invalid_sequence_rows}
