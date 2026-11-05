"""Explicit synthetic fixtures for v5 explanation tests; never production adapters."""
from copy import deepcopy


def event(ev):
    ev = deepcopy(ev)
    ev.update(alert_version="fixture-v5", active=True,
              allowed_ids=[c["id"] for c in ev.get("candidates", []) if c.get("feasible") is True])
    for row in ev.get("evidence", []):
        row.update(option_id=None, metric="end_pct", unit="%", segment="fixture", relation="observed")
    return ev


def answer(ev, selected_id=None, sentences=None, evidence_ids=None):
    return {"alert_version": ev["alert_version"], "selected_id": selected_id,
            "sentences": sentences or ["請留意航線電量。", "請操作員評估。"],
            "evidence_ids": ["E1"] if evidence_ids is None else evidence_ids}
