"""New integration checks; fake backends only, no external model calls."""
import unittest
from copy import deepcopy
from unittest.mock import patch

from . import explain, typed_explain as tx
from .core import contract
from .test_v5_explain_fixtures import answer
from .slot_test_helpers import SlotBackend


def event():
    return {"key": "battery", "t": 1, "type": "raise", "active": True,
            "alert_version": "v1", "title": "電量", "value": "偏低", "severity": 4,
            "rule_choice": "C1", "allowed_ids": ["C1"],
            "candidates": [{"id": "C1", "label": "繼續", "feasible": True},
                           {"id": "C4", "label": "返航", "feasible": True}],
            "evidence": [
                {"id": "E1", "option_id": "C1", "metric": "end_pct", "value": "15.0",
                 "unit": "%", "segment": "landing", "relation": "predicted"},
                {"id": "E2", "option_id": "C4", "metric": "end_pct", "value": "40.0",
                 "unit": "%", "segment": "landing", "relation": "predicted"}]}


class Backend:
    name = "fake"

    def __init__(self, data):
        self.data = data

    def complete_json(self, *args, **kwargs):
        return {"ok": True, "data": self.data, "raw": "", "latency_s": 0.0, "error": None}


class V5ExplanationWiringTests(unittest.TestCase):
    def test_both_validate_entries_delegate_to_exact_core(self):
        ev = event()
        view = {"alert_version": "v1", "severity_zh": "警告", "title_zh": "電量",
                "allowed_ids": [], "evidence": []}
        with patch.object(contract, "validate", return_value="sentinel") as shared:
            self.assertEqual(explain.validate({}, ev), "sentinel")
            self.assertEqual(tx.validate({}, view), "sentinel")
            self.assertEqual(shared.call_count, 2)

    def test_option_value_cannot_be_borrowed_from_other_option(self):
        ev = event()
        d = answer(ev, "C1", ["C1 落地電量 40.0%。", "請操作員評估。"], ["E1", "E2"])
        self.assertIsNotNone(explain.validate(d, ev))
        d["sentences"][0] = "C1 落地電量 15.0%。"
        self.assertIsNone(explain.validate(d, ev))

    def test_feasible_but_not_allowed_is_rejected(self):
        ev = event()
        self.assertIsNotNone(explain.validate(answer(ev, "C4"), ev))

    def test_current_infeasibility_retirement_and_new_version_reject(self):
        ev = event()
        d = answer(ev, "C1")
        for state in ({"active": False, "alert_version": "v1", "feasible_ids": ["C1"]},
                      {"active": True, "alert_version": "v2", "feasible_ids": ["C1"]},
                      {"active": True, "alert_version": "v1", "feasible_ids": []}):
            self.assertIsNotNone(explain.validate(d, ev, lambda: state))

    def test_empty_allowed_set_requires_null(self):
        ev = event()
        ev["allowed_ids"] = []
        self.assertIsNotNone(explain.validate(answer(ev, "C1"), ev))
        self.assertIsNone(explain.validate(answer(ev), ev))

    def test_legacy_unstructured_facts_are_not_guessed(self):
        ev = event()
        ev["evidence"] = [{"id": "E1", "text": "落地", "value": "15.0%"}]
        self.assertEqual(explain.explain(ev, SlotBackend())["source"], "rule")

    def test_old_model_schema_cannot_pass(self):
        ev = event()
        old = {"decision": "SELECT", "choice_id": "C1", "summary_zh": "請留意。",
               "reason_zh": "請評估。", "evidence_ids": ["E1"]}
        self.assertIsNotNone(explain.validate(old, ev))

    def test_legacy_success_retains_locally_derived_display_aliases(self):
        ev = event()
        result = explain.explain(ev, SlotBackend())
        self.assertEqual(result["source"], "llm", result["fallback_reason"])
        self.assertEqual(result["text"]["choice_id"], "C1")

    def test_typed_facts_carry_binding_and_explicit_no_option(self):
        ev = {"key": "P1", "predictor": "P1", "type": "raise", "active": True,
              "sequence": 1, "mission_version": "m1", "severity": 4,
              "evidence": [{"value": {"nominal_end_pct": 15.0}}]}
        view = tx.typed_view(ev)
        row = tx._facts(view)["evidence"][0]
        self.assertTrue({"id", "option_id", "metric", "value", "unit", "segment", "relation"} <= row.keys())
        self.assertIsNone(row["option_id"])
        self.assertNotIn("_key", row)
        d = answer(view, sentences=["預估落地電量（中值）15.0%。", "請操作員評估。"])
        self.assertIsNone(tx.validate(d, view))

    def test_ready_then_retired_is_filtered_at_poll(self):
        worker = tx.AsyncExplainer(lambda: {"source": "llm"})
        worker.submit("battery", "v1", {})
        worker.close(wait=True)
        worker.retire("battery")
        self.assertEqual(worker.poll(), [])
        self.assertEqual(len(worker.discarded), 1)

    def test_ready_then_new_version_is_filtered_at_poll(self):
        worker = tx.AsyncExplainer(lambda value: value)
        worker.submit("battery", "v1", {}, {"value": 1})
        worker.submit("battery", "v2", {}, {"value": 2})
        worker.close(wait=True)
        self.assertEqual([x["version"] for x in worker.poll()], ["v2"])

    def test_worker_submission_takes_independent_snapshot(self):
        import threading
        gate = threading.Event()

        def run(payload):
            gate.wait(3)
            return payload

        worker = tx.AsyncExplainer(run)
        payload = {"value": [1]}
        worker.submit("battery", "v1", {}, payload)
        payload["value"].append(2)
        gate.set()
        worker.close(wait=True)
        self.assertEqual(worker.poll()[0]["result"], {"value": [1]})

    def test_legacy_application_rechecks_current_feasibility(self):
        ev = event()
        state = {"active": True, "alert_version": "v1", "feasible_ids": ["C1"]}
        worker = tx.LegacyAlertExplainer(SlotBackend(), current_state=lambda key: state)
        worker(ev)
        worker.close(wait=True)
        state["feasible_ids"] = []
        self.assertEqual(worker.poll(), [])
        self.assertEqual(len(worker.async_.discarded), 1)

    def test_application_missing_current_state_fails_closed(self):
        ev = event()
        worker = tx.LegacyAlertExplainer(SlotBackend(), current_state=lambda key: None)
        worker(ev)
        worker.close(wait=True)
        self.assertEqual(worker.poll(), [])

    def test_only_exactly_two_short_sentences_are_accepted(self):
        ev = event()
        for sentences in (["一。二。", "三。"], ["很" * 61, "二。"], [" ", "二。"]):
            self.assertIsNotNone(explain.validate(answer(ev, "C1", sentences), ev))


if __name__ == "__main__":
    unittest.main()
