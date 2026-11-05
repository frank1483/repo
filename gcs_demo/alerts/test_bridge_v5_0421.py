"""New local controls for 0421. No backend, model, device or old research runner."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gcs_demo.alert_bridge import AlertFeed
from .core.freshness import TRUE, FALSE, UNKNOWN
from .core.log import audit
from .core.state_machine import AlertEngine
from .energy_api import default_vehicle
from .predict import Finding, PredictiveAlertEngine


def finding(key="battery_route"):
    return Finding(key, True, severity=2, title="電量告警", value="請評估",
                   evidence=[{"id": "E1", "option_id": "C1", "metric": "landing_pct",
                              "value": "25.0%", "unit": "%", "segment": "route",
                              "relation": "estimate"}],
                   candidates=[{"id": "C1", "label": "返航", "action": "A_RTL_NOW",
                                "feasible": True}], rule_choice="C1")


def engine():
    return PredictiveAlertEngine([(100, 0, 60)], (0, 0, 0), default_vehicle())


def arm(eng, key="battery_route", t=0):
    rows = eng._debounce(t, finding(key))
    # Structured allowed IDs are a test input. Wiring production ranking/evidence
    # remains a separate batch; do not silently infer it in the explanation path.
    eng._states.states[key].facts["allowed_ids"] = ["C1"]
    return rows


def result(version=1, source="llm"):
    return {"source": source, "text": {"alert_version": version, "selected_id": "C1",
            "sentences": ["請評估 C1。", "請操作員確認。"], "evidence_ids": ["E1"]}}


def rec(t):
    return {"t_s": t, "battery_pct": 50, "power_w": 100,
            "lat": 25, "lon": 121, "alt": 60, "wind_mps": 1, "wind_from": 0}


def feed(explainer=None, log_path=None):
    home = {"lat": 25, "lon": 121}
    route = [home, {"lat": 25.001, "lon": 121, "alt": 60}, home]
    return AlertFeed(home, route, default_vehicle(), explain_fn=explainer, log_path=log_path)


class QueueExplainer:
    def __init__(self):
        self.ready = []
        self.pending = {"source": "rule_pending", "text": {}}

    def __call__(self, ev):
        return self.pending

    def poll(self):
        ready, self.ready = self.ready, []
        return ready


class EngineExplanation0421(unittest.TestCase):
    def test_core_allocates_global_sequence_and_version(self):
        eng = AlertEngine()
        first = eng.step("a", 0, TRUE, severity=2)[0]
        second = eng.explanation_update("a", 1, 0, result())
        third = eng.step("b", 0, TRUE, severity=2)[0]
        self.assertEqual([r["engine_seq"] for r in (first, second, third)], [1, 2, 3])
        self.assertEqual(second["alert_version"], 2)
        self.assertEqual(second["explanation_for_version"], 1)
        self.assertEqual(second["sensed_t"], first["sensed_t"])

    def test_explanation_does_not_reset_clear_continuity(self):
        eng = AlertEngine()
        eng.step("a", 0, TRUE, severity=2)
        eng.step("a", 1, FALSE)
        eng.explanation_update("a", 1, 1, result())
        for t in range(2, 11):
            self.assertEqual(eng.step("a", t, FALSE), [])
        self.assertEqual(eng.step("a", 11, FALSE)[0]["type"], "resolve")

    def test_core_rejects_invalid_result_without_allocating_sequence(self):
        eng = AlertEngine()
        eng.step("a", 0, TRUE, severity=2)
        for bad in ({"source": "llm", "text": "bad"}, result(source="rule_pending"), None):
            self.assertIsNone(eng.explanation_update("a", 1, 0, bad))
        self.assertEqual(eng.engine_seq, 1)

    def test_current_state_tracks_feasibility_without_an_event(self):
        eng = engine()
        arm(eng)
        f = finding()
        f.candidates.append({"id": "C4", "feasible": True})
        self.assertEqual(eng._debounce(1, f), [])
        self.assertEqual(eng.current_state("battery_route")["feasible_ids"], ["C1", "C4"])

    def test_unknown_prevents_delayed_explanation(self):
        eng = engine()
        arm(eng)
        eng._unknown(1, "battery_route")
        self.assertIsNone(eng.apply_explanation("battery_route", 1, result()))
        self.assertEqual(eng._states.engine_seq, 1)

    def test_route_change_prevents_delayed_explanation_before_next_tick(self):
        eng = engine()
        arm(eng)
        eng.set_route([(200, 0, 60)])
        self.assertIsNone(eng.apply_explanation("battery_route", 1, result()))

    def test_real_contract_rejects_wrong_selection(self):
        eng = engine()
        arm(eng)
        bad = result()
        bad["text"]["selected_id"] = "C4"
        self.assertIsNone(eng.apply_explanation("battery_route", 1, bad))
        self.assertEqual(eng._states.engine_seq, 1)

    def test_real_contract_accepts_one_current_explanation(self):
        eng = engine()
        arm(eng)
        reply = result()
        update = eng.apply_explanation("battery_route", 1, reply)
        self.assertIsNotNone(update)
        self.assertEqual((update["source"], update["status"], update["engine_seq"]), ("llm", "update", 2))
        reply["text"]["selected_id"] = "C4"
        self.assertEqual(update["model_selection"], "C1")
        self.assertIsNone(eng.apply_explanation("battery_route", 1, result()))

    def test_fallback_rebuilt_from_current_rules_and_logged_as_rule(self):
        eng = engine()
        arm(eng)
        fallback = result(source="rule")
        fallback["text"]["selected_id"] = "C4"
        update = eng.apply_explanation("battery_route", 1, fallback)
        self.assertEqual(update["source"], "rule")
        self.assertEqual(update["explain"]["text"]["selected_id"], "C1")
        self.assertIsNone(update["model_selection"])


class BridgeRetention0421(unittest.TestCase):
    def test_default_explainer_receives_live_callback(self):
        with patch("gcs_demo.alert_bridge.LegacyAlertExplainer") as ctor:
            home = {"lat": 25, "lon": 121}
            item = AlertFeed(home, [home, home], default_vehicle())
            self.assertEqual(ctor.call_args.kwargs["current_state"], item.engine.current_state)

    def test_hidden_capacity_event_is_retained_in_unfiltered_denominator(self):
        item = feed()
        emitted = arm(item.engine, "battery_capacity")
        with patch.object(item.engine, "update", return_value=emitted):
            self.assertEqual(item.tick(rec(0), 0), [])
        self.assertEqual(len(item.engine_events), 1)
        self.assertEqual(item.alert_log.rows[0]["key"], "battery_capacity")
        self.assertEqual(audit(item.engine_events, item.alert_log.rows)["core_valid_rate"], 1)

    def test_snapshots_at_zero_ten_twenty_without_rule_events(self):
        item = feed()
        with patch.object(item.engine, "update", return_value=[]):
            for t in (0, 1, 9.9, 10, 19.9, 20):
                item.tick(rec(t), 0)
        self.assertEqual([r["snapshot_t"] for r in item.alert_log.rows], [0, 10, 20])
        self.assertEqual(item.engine_events, [])

    def test_out_of_order_sample_does_not_break_log_scheduler(self):
        item = feed()
        with patch.object(item.engine, "update", return_value=[]):
            for t in (10, 9, 20):
                item.tick(rec(t), 0)
        self.assertEqual([r["snapshot_t"] for r in item.alert_log.rows], [10, 20])

    def test_pending_object_mutation_cannot_rewrite_event_history(self):
        explainer = QueueExplainer()
        item = feed(explainer)
        emitted = arm(item.engine)
        with patch.object(item.engine, "update", return_value=emitted):
            original = deepcopy(item.tick(rec(0), 0)[0])
        explainer.pending.update(source="llm", text={"selected_id": "C4"})
        self.assertEqual(item.events[0], original)
        self.assertNotIn("explain", item.alert_log.rows[0])

    def test_poll_appends_new_engine_event_without_mutating_original(self):
        explainer = QueueExplainer()
        item = feed(explainer)
        emitted = arm(item.engine)
        with patch.object(item.engine, "update", return_value=emitted):
            item.tick(rec(0), 0)
        original = deepcopy(item.events[0])
        explainer.ready = [{"key": "battery_route", "version": 1, "result": result()}]
        accepted = item.poll_explanations()
        self.assertEqual(len(accepted), 1)
        self.assertEqual(item.events[0], original)
        self.assertEqual([r["engine_seq"] for r in item.engine_events], [1, 2])
        self.assertEqual(item.events[-1]["source"], "llm")
        self.assertEqual(audit(item.engine_events, item.alert_log.rows)["core_valid_rate"], 1)
        self.assertEqual(item.poll_explanations(), [])

    def test_stale_poll_emits_no_update(self):
        explainer = QueueExplainer()
        item = feed(explainer)
        arm(item.engine)
        explainer.ready = [{"key": "battery_route", "version": 0, "result": result(0)}]
        self.assertEqual(item.poll_explanations(), [])
        self.assertEqual(item.alert_log.rows, [])

    def test_file_logging_and_audit_missing_row(self):
        with tempfile.TemporaryDirectory() as folder:
            logfile = Path(folder) / "events.jsonl"
            item = feed(log_path=logfile)
            emitted = arm(item.engine)
            with patch.object(item.engine, "update", return_value=emitted):
                item.tick(rec(0), 0)
            rows = [json.loads(line) for line in logfile.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows, item.alert_log.rows)
            self.assertEqual(audit(item.engine_events, rows)["core_valid_count"], 1)
            snapshots = [r for r in rows if r["status"] == "snapshot"]
            self.assertEqual(audit(item.engine_events, snapshots)["missing_sequences"], [1])

    def test_default_logging_has_no_disk_target(self):
        self.assertIsNone(feed().alert_log.path)

    def test_typed_log_path_rejected_instead_of_claiming_support(self):
        with self.assertRaises(ValueError):
            AlertFeed(None, None, default_vehicle(), typed_geographic=True, log_path="unused.jsonl")


if __name__ == "__main__":
    unittest.main()
