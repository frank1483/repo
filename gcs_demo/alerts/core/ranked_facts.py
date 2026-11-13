"""Legacy v5 facts. No prediction, feasibility threshold or model invocation."""
from copy import deepcopy
import math
import json


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def ranked_ids(candidates):
    """Contract 5.3: filter, required targets, completion, then <1 pp ties.

    Compare every landing estimate with the maximum (never chain near-ties).
    Missing landing estimates are ranked below finite estimates, or tie when
    every remaining option is non-flight monitoring/estimation advice.
    Input order breaks a fresh tie; the caller retains the committed identity.
    """
    pool = [c for c in candidates if c.get("feasible") is True
            and c.get("id") != "C5" and c.get("action") != "A_LAND_NOW"]
    if not pool:
        return []
    # 5.6 non-flight advice has no mission/landing score. It is not a zero-
    # completion flight. Keep it available beside the ranked flight options;
    # the predictor's advisory choice and three-second confirmation still own
    # selection. Battery P1 options all carry comparable mission scores.
    order = [c["id"] for c in pool]
    advice = [c for c in pool if c.get("action") in
              ("A_CONTINUE_MONITOR", "A_USE_VOLTAGE_ESTIMATE")]
    pool = [c for c in pool if c not in advice]
    if not pool:
        return [c["id"] for c in advice]
    missed = min(c.get("missed_required", 0) for c in pool)
    pool = [c for c in pool if c.get("missed_required", 0) == missed]
    completion = max(c.get("completion_pct", 0) for c in pool)
    pool = [c for c in pool if c.get("completion_pct", 0) == completion]
    def landing(c):
        value = c.get("end_pct_raw", c.get("end_pct"))
        return value if finite(value) else None
    values = [landing(c) for c in pool if landing(c) is not None]
    if values:
        best = max(values)
        pool = [c for c in pool if landing(c) is not None and best - landing(c) < 1.0]
    survivors = {c["id"] for c in pool + advice}
    return [ident for ident in order if ident in survivors]


def fact(ident, text, metric, value, unit, segment, *, option_id=None, **extra):
    """Scalar source value; display metadata must not become another metric."""
    return {"id": ident, "text": text, "option_id": option_id, "metric": metric,
            "value": value, "unit": unit, "segment": segment, "relation": "=", **extra}


def _display_fact(row):
    """Round presentation only; prediction and ranking keep their raw scalars."""
    value, unit = row.get("value"), row.get("unit", "")
    raw = row.get("raw_value", value)
    if isinstance(raw, str):
        token = raw.strip()
        if unit and token.endswith(unit):
            token = token[:-len(unit)].strip()
        try:
            raw = float(token)
        except ValueError:
            return row
    if not finite(raw):
        return row
    row.setdefault("raw_value", raw)
    places = {"%": 1, "m/s": 1, "Wh": 0, "倍": 2, "s": 0, "°": 0}.get(unit)
    if places is not None:
        suffix = unit if isinstance(value, str) and value.strip().endswith(unit) else ""
        row["value"] = f"{raw:.{places}f}" + suffix
    return row


def option_evidence(evidence, candidates, key):
    """Merge exact measurements before rounding; retain first ID and all origins.

    Different segments/options/values remain distinct. Older incomplete fixture
    rows are retained individually. Sources are copied; no caller is mutated.
    """
    rows, seen = [], {}
    labels = {c["id"]: c.get("label", "") for c in candidates}
    for source in evidence:
        row = deepcopy(source)
        # Compare raw source values, never two values made equal by rounding.
        identity = json.dumps([row.get(k) for k in
                               ("metric", "segment", "option_id", "value", "unit")],
                              sort_keys=True, ensure_ascii=False)
        member = row.get("source_predictor")
        if member is not None:
            row["members"] = list(dict.fromkeys(row.get("members", []) + [member]))
            row["member_sources"] = [{k: deepcopy(row[k]) for k in
                                      ("source_predictor", "source_evidence_id", "sensed_t", "recv_t")
                                      if k in row}]
        if row.get("metric") is not None and identity in seen:
            first = seen[identity]
            for name in row.get("members", []):
                if name not in first.setdefault("members", []):
                    first["members"].append(name)
            for origin in row.get("member_sources", []):
                if origin not in first.setdefault("member_sources", []):
                    first["member_sources"].append(origin)
            continue
        if row.get("metric") is not None:
            seen[identity] = row
        rows.append(row)
    present = {(e.get("option_id"), e.get("metric")) for e in rows}
    next_id = max((int(e["id"][1:]) for e in rows
                   if isinstance(e.get("id"), str) and e["id"][1:].isdigit()), default=0)
    for c in candidates:
        segment = {"action": c.get("action"), "param": deepcopy(c.get("param"))}
        for field, label, unit in (("end_pct_raw", "預估落地電量", "%"),
                                   ("completion_pct", "任務完成度", "%"),
                                   ("missed_required", "漏掉必要目標數", "個")):
            metric = "end_pct" if field == "end_pct_raw" else field
            value = c.get(field)
            if not finite(value) or (c["id"], metric) in present:
                continue
            next_id += 1
            rows.append(fact(f"E{next_id}", label, metric, value, unit, segment,
                             option_id=c["id"], source_kind="candidate",
                             source_predictor="P1" if key == "battery" else key))
            present.add((c["id"], metric))
    for row in rows:
        ident = row.get("option_id")
        if ident is not None:
            label = row.get("text", row.get("metric", ""))
            row.setdefault("metric_label", label)
            row["text"] = f"{ident} {labels.get(ident, '')}：{label}"
        _display_fact(row)
    return rows
