"""0415 failure regressions. Local fixtures only; execution assigned to Claude."""
from copy import deepcopy
from dataclasses import replace
import threading
import unittest
from unittest.mock import patch

from . import explain, typed_explain as tx
from .core import contract
from .energy_api import Wind
from .predict import Telemetry
from .test_explain_v5_wiring import event, Backend
from .test_v5_explain_fixtures import answer
from .slot_test_helpers import SlotBackend
from .test_predict_v5_0411 import engine, finding


class Aliases0415(unittest.TestCase):
    def test_two_character_metrics_are_valid_and_disambiguate(self):
        for metric, label, unit in (("wind_speed", "風速", "m/s"),
                                    ("current_a", "電流", "A"),
                                    ("voltage_v", "電壓", "V")):
            ev = event()
            ev["evidence"][0].update(metric=metric, value="15.0", unit=unit)
            self.assertIsNone(explain.validate(answer(
                ev, "C1", [f"C1 {label}15.0{unit}。", "請操作員評估。"], ["E1"]), ev))
            ev["evidence"][0].update(metric="end_pct", value="15.0", unit="%")
            self.assertIsNotNone(explain.validate(answer(
                ev, "C1", [f"C1 落地電量與{label}15.0%。", "請操作員評估。"], ["E1"]), ev))

    def test_dynamic_ambiguous_aliases_cannot_restore_shortcuts(self):
        for label in ("落地", "保留", "完成度"):
            ev = event()
            ev["evidence"][0].update(metric_label=label, text=label, metric_labels=[label])
            self.assertIsNotNone(explain.validate(answer(
                ev, "C1", [f"C1 {label}15.0%。", "請操作員評估。"], ["E1"]), ev))

    def test_custom_two_character_label_is_not_length_filtered(self):
        ev = event()
        ev["evidence"][0].update(metric="local_margin", metric_label="裕量")
        self.assertIsNone(explain.validate(answer(
            ev, "C1", ["C1 裕量15.0%。", "請操作員評估。"], ["E1"]), ev))

    def test_old_short_landing_label_stays_rejected(self):
        ev = event()
        self.assertIsNotNone(explain.validate(answer(
            ev, "C1", ["C1 落地 15.0%。", "請操作員評估。"], ["E1"]), ev))

    def test_decimal_replacement_still_rejects_reformatting(self):
        ev = event()
        ev["evidence"][0]["value"] = ".5"
        for value, valid in ((".5", True), ("0.5", False), (".50", False)):
            result = explain.validate(answer(ev, "C1", [
                f"C1 落地電量 {value}%。", "請操作員評估。"], ["E1"]), ev)
            self.assertEqual(result is None, valid)


class Pending0415(unittest.TestCase):
    def worker(self):
        gate = threading.Event()
        worker = tx.LegacyAlertExplainer(Backend({}))
        worker.async_._fn = lambda ev: (gate.wait(3), {"source": "rule", "text": explain.rule_text(ev)})[1]
        self.addCleanup(worker.close, True)
        self.addCleanup(gate.set)
        return worker, gate

    def test_new_version_settles_old_returned_rule_object_immediately(self):
        worker, gate = self.worker()
        old = worker(event())
        ev = event()
        ev["alert_version"] = "v2"
        new = worker(ev)
        self.assertEqual(old["source"], "rule")
        self.assertEqual(old["fallback_reason"], "version_superseded")
        self.assertEqual(old["text"]["alert_version"], "v1")
        self.assertEqual(new["source"], "rule_pending")

    def test_retirement_settles_pending_without_stale_model_application(self):
        worker, gate = self.worker()
        old = worker(event())
        worker.retire("battery")
        self.assertEqual(old["source"], "rule")
        self.assertEqual(old["fallback_reason"], "alert_retired")
        gate.set()
        worker.close(True)
        self.assertEqual(worker.poll(), [])
        self.assertEqual(len(worker.async_.discarded), 1)

    def test_application_rejection_settles_rule_and_still_returns_no_model(self):
        ev = event()
        state = {"active": True, "alert_version": "v1", "feasible_ids": ["C1"]}
        worker = tx.LegacyAlertExplainer(SlotBackend(), current_state=lambda key: state)
        pending = worker(ev)
        worker.close(True)
        state["feasible_ids"] = []
        self.assertEqual(worker.poll(), [])
        self.assertEqual(pending["source"], "rule")
        self.assertEqual(pending["text"]["alert_version"], "v1")

    def test_successful_poll_settles_original_reference(self):
        worker, gate = self.worker()
        pending = worker(event())
        gate.set()
        worker.close(True)
        self.assertEqual(len(worker.poll()), 1)
        self.assertEqual(pending["source"], "rule")
        self.assertEqual(worker._pending_results, {})

    def test_bridge_resolve_notifies_retire(self):
        from gcs_demo.alert_bridge import AlertFeed
        from .test_bridge_v5_0421 import feed as make_feed, rec
        from .core.freshness import TRUE, FALSE
        worker, gate = self.worker()
        feed = make_feed(worker)
        pending = worker(event())
        feed.engine._states.step("battery", 0, TRUE, severity=2)
        for t in range(1, 12):
            resolved = feed.engine._states.step("battery", t, FALSE)
        self.assertEqual(resolved[0]["type"], "resolve")
        with patch.object(feed.engine, "update", return_value=resolved):
            feed.tick(rec(11), 0)
        self.assertEqual(pending["source"], "rule")
        self.assertEqual(pending["fallback_reason"], "alert_retired")


class OptionIdentity0415(unittest.TestCase):
    def test_waypoint_parameters_have_independent_qualification(self):
        eng = engine()
        a = eng._option_identity("C3", "A_RTL_AFTER_WP", 0)
        b = eng._option_identity("C3", "A_RTL_AFTER_WP", 1)
        self.assertNotEqual(a, b)
        self.assertFalse(eng._is_feasible(19.99, a))
        self.assertTrue(eng._is_feasible(20, b))
        self.assertFalse(eng._is_feasible(21.99, a))
        self.assertTrue(eng._is_feasible(22, a))

    def test_speed_and_waypoint_ids_never_alias(self):
        eng = engine()
        a = eng._option_identity("C2", "A_REDUCE_SPEED", 5.0)
        b = eng._option_identity("C2", "A_REDUCE_SPEED", 5.5)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, eng._option_identity("C2", "A_RTL_AFTER_WP", 5.0))

    def test_route_change_invalidates_qualification_identity(self):
        eng = engine()
        before = eng._option_identity("C3", "A_RTL_AFTER_WP", 0)
        eng._is_feasible(19, before)
        eng.set_route([(200, 0, 60)])
        after = eng._option_identity("C3", "A_RTL_AFTER_WP", 0)
        self.assertNotEqual(before, after)
        self.assertNotIn(before, eng._option_energy_ok)
        self.assertTrue(eng._is_feasible(20, after))

    def test_same_id_new_parameter_withdraws_then_waits_three_seconds(self):
        eng = engine()
        def f(param):
            x = finding(severity=2)
            x.candidates[0]["option_identity"] = eng._option_identity("C1", "A_CONTINUE", param)
            return x
        eng._debounce(0, f(1))
        row = eng._debounce(1, f(2))[0]
        self.assertIsNone(row["rule_choice"])
        self.assertEqual(row["rule_decision"], "HOLD")
        self.assertIsNone(explain.rule_text(row)["selected_id"])
        self.assertIn("穩定確認", explain.rule_text(row)["summary_zh"])
        self.assertIsNone(eng.active()["battery_route"].rule_choice)
        self.assertEqual(eng._debounce(2, f(2)), [])
        self.assertEqual(eng._debounce(3, f(2)), [])
        row = eng._debounce(4, f(2))[0]
        self.assertEqual(row["rule_choice"], "C1")
        self.assertEqual(row["rule_decision"], "SELECT")
        self.assertEqual(row["recommendation"], "C1")
        self.assertEqual(row["recommendation_identity"], f(2).candidates[0]["option_identity"])

    def test_parameter_churn_cannot_accumulate_confirmation(self):
        eng = engine()
        for t in range(8):
            f = finding(severity=2)
            f.candidates[0]["option_identity"] = f"waypoint:{t}"
            eng._debounce(t, f)
        self.assertIsNone(eng.active()["battery_route"].rule_choice)

    def test_pnr_search_uses_return_point_memory_before_picking(self):
        eng = engine()
        eng = type(eng)([(100, 0, 60), (200, 0, 60)], eng.home, eng.v)
        tm = Telemetry(0, (0, 0, 60), (0, 0, 0), 50, 22, 10, 0, 6, 0, 95, Wind(0, 0))
        cap = eng.v.battery_wh
        chosen = []
        # Probe 1 is just above 20%, but has lost qualification; it must not
        # keep displacing the earlier, stable return point until it reaches 22%.
        identity = eng._option_identity("C3", "A_RTL_AFTER_WP", 0)
        eng._is_feasible(19, identity)
        walk = [(0, 0, 0, cap * .20), (1, cap * .29, 20, 0),
                (2, cap * .40, 40, 0)]
        def candidates(tm, path, walk, avail, reserve, pnr, wind):
            chosen.append(pnr)
            return []
        with patch.object(eng, "_walk", return_value=walk), patch.object(eng, "_candidates", side_effect=candidates):
            eng._battery_route(tm, cap * .50, "soc", None)
        self.assertEqual(chosen[0][0], 0)
        self.assertFalse(eng._option_energy_ok[identity])


if __name__ == "__main__":
    unittest.main()
