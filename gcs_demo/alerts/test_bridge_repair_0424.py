"""0424 local fake controls. No model/backend/network/device or research runner."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from gcs_demo import server
from .core.log import audit
from .test_bridge_v5_0421 import QueueExplainer, arm, feed, finding, rec, result


def pending_feed():
    worker = QueueExplainer()
    item = feed(worker)
    emitted = arm(item.engine)
    with patch.object(item.engine, "update", return_value=emitted):
        item.tick(rec(0), 0)
    return item, worker


def resolve(item):
    inactive = finding()
    inactive.active = False
    for t in range(1, 12):
        emitted = item.engine._debounce(t, inactive)
    return emitted


class Closure0424(unittest.TestCase):
    def test_retired_request_closes_without_poll_result(self):
        item, worker = pending_feed()
        original = deepcopy(item.events[0])
        emitted = resolve(item)
        self.assertEqual(emitted[0]["type"], "resolve")
        with patch.object(item.engine, "update", return_value=emitted):
            item.tick(rec(11), 0)
        self.assertEqual(item.events[0], original)
        self.assertEqual(item.events[-1]["explain"]["fallback_reason"], "alert_retired")
        self.assertTrue(item.events[-1]["closure_only"])
        self.assertFalse(item.events[-1]["active"])
        self.assertEqual(item._pending_explanations, {})

    def test_retired_late_completion_is_ignored_after_one_closure(self):
        item, worker = pending_feed()
        resolve(item)
        item.poll_explanations()
        before = deepcopy(item.events)
        worker.ready = [{"key": "battery_route", "version": 1, "result": result()}]
        self.assertEqual(item.poll_explanations(), [])
        self.assertEqual(item.events, before)

    def test_unknown_closes_without_a_new_rule_event(self):
        item, worker = pending_feed()
        self.assertEqual(item.engine._unknown(1, "battery_route"), [])
        item.poll_explanations()
        self.assertEqual(item.events[-1]["explain"]["fallback_reason"], "prediction_expired")
        self.assertEqual(item.events[0]["explain"]["source"], "rule_pending")

    def test_route_change_closes_without_resurrecting_old_choice(self):
        item, worker = pending_feed()
        item.engine.set_route([(200, 0, 60)])
        item.poll_explanations()
        row = item.events[-1]
        self.assertIn(row["explain"]["fallback_reason"], ("route_superseded", "state_unavailable"))
        self.assertIsNone(row["rule_choice"])
        self.assertEqual(row["candidates"], [])
        self.assertIsNone(row["model_selection"])

    def test_newer_version_stays_pending_after_old_closure_appended(self):
        item, worker = pending_feed()
        newer = finding()
        # Recommendation change emits an update immediately, without a new threshold.
        newer.rule_choice = None
        newer.candidates[0]["feasible"] = False
        emitted = item.engine._debounce(1, newer)
        self.assertTrue(emitted)
        with patch.object(item.engine, "update", return_value=emitted):
            item.tick(rec(1), 0)
        projected = server._latest_alert_events(item.events)
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["alert_version"], emitted[0]["alert_version"])
        self.assertEqual(projected[0]["explain"]["source"], "rule_pending")
        self.assertEqual(item.events[-1]["explain"]["fallback_reason"], "version_superseded")

    def test_rejected_model_falls_back_to_current_rule_without_retiring_alert(self):
        item, worker = pending_feed()
        bad = result()
        bad["text"]["selected_id"] = "NOT_ALLOWED"
        worker.ready = [{"key": "battery_route", "version": 1, "result": bad}]
        self.assertEqual(item.poll_explanations(), [])
        row = item.events[-1]
        self.assertEqual(row["source"], "rule")
        self.assertTrue(row["active"])
        self.assertEqual(row["explain"]["fallback_reason"], "result_rejected")
        self.assertNotEqual(row["explain"]["text"].get("selected_id"), "NOT_ALLOWED")

    def test_legacy_internal_rejection_reference_produces_rule_update(self):
        item, worker = pending_feed()
        original = deepcopy(item.events[0])
        worker.pending.update(source="rule", fallback_reason="validation_rejected")
        item.poll_explanations()
        self.assertEqual(item.events[0], original)
        self.assertEqual(item.events[-1]["source"], "rule")
        self.assertTrue(item.events[-1]["active"])
        self.assertEqual(item.events[-1]["explain"]["fallback_reason"], "validation_rejected")

    def test_successful_completion_once_and_duplicate_cannot_change_state(self):
        item, worker = pending_feed()
        completion = {"key": "battery_route", "version": 1, "result": result(source="rule")}
        worker.ready = [deepcopy(completion)]
        self.assertEqual(len(item.poll_explanations()), 1)
        state = deepcopy(item.engine._states.snapshot())
        events = deepcopy(item.events)
        worker.ready = [completion]
        self.assertEqual(item.poll_explanations(), [])
        self.assertEqual(item.engine._states.snapshot(), state)
        self.assertEqual(item.events, events)

    def test_closure_has_engine_owned_sequence_and_retains_log_denominator(self):
        item, worker = pending_feed()
        old_version = item.engine._states.states["battery_route"].version
        item.engine._unknown(1, "battery_route")
        item.poll_explanations()
        self.assertEqual([r["engine_seq"] for r in item.engine_events], [1, 2])
        self.assertEqual(item.engine._states.states["battery_route"].version, old_version)
        self.assertEqual(item.events[-1]["explanation_for_version"], old_version)
        self.assertEqual(audit(item.engine_events, item.alert_log.rows)["core_valid_rate"], 1)

    def test_poll_does_not_repeat_terminal_journal_row(self):
        item, worker = pending_feed()
        item.engine._unknown(1, "battery_route")
        item.poll_explanations()
        history = deepcopy(item.events)
        item.poll_explanations()
        item.poll_explanations()
        self.assertEqual(item.events, history)


class Projection0424(unittest.TestCase):
    def test_latest_episode_row_removes_old_pending_for_ui_and_report(self):
        item, worker = pending_feed()
        worker.ready = [{"key": "battery_route", "version": 1, "result": result(source="rule")}]
        session = server.Session()
        session.feed, session.chosen = item, {"path": [{}, {}]}
        rows = session.refresh_alerts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "rule")
        self.assertEqual(len(item.events), 2)
        self.assertEqual(item.events[0]["explain"]["source"], "rule_pending")

    def test_distinct_episodes_keep_separate_rows(self):
        item, worker = pending_feed()
        a = deepcopy(item.events[0])
        b = dict(deepcopy(a), alert_id="battery_route:2", engine_seq=2)
        self.assertEqual(len(server._latest_alert_events([a, b])), 2)

    def test_terminal_row_is_reportable_without_pending_or_old_action(self):
        item, worker = pending_feed()
        resolve(item)
        session = server.Session()
        session.feed, session.chosen = item, {"path": [{}, {}]}
        rows = session.refresh_alerts()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["active"])
        self.assertEqual(rows[0]["source"], "rule")
        self.assertEqual(rows[0]["explanation_status"], "closed")
        self.assertIn("已結案", rows[0]["text_zh"])

    def test_projection_uses_version_then_sequence_without_mutating_history(self):
        item, worker = pending_feed()
        a = deepcopy(item.events[0])
        newer = dict(deepcopy(a), alert_version=2, engine_seq=2)
        late_old = dict(deepcopy(a), engine_seq=99, closure_only=True)
        events = [a, newer, late_old]
        old = deepcopy(events)
        self.assertEqual(server._latest_alert_events(events), [newer])
        self.assertEqual(events, old)


if __name__ == "__main__":
    unittest.main()
