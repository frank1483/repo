"""New composite battery controls. First Python execution belongs to Claude."""
import unittest
from dataclasses import replace
from unittest.mock import patch

from .predict import Finding
from .test_predict_sources_0447 import engine, feed
from .core.state_machine import AlertEngine, CRITICAL
from .core.freshness import TRUE


def member(key, active=False, severity=4, ident="C4"):
    candidates = [{"id": ident, "action": "A_RTL_NOW", "feasible": True,
                   "energy_feasible": True, "end_pct_raw": 30., "end_pct": 30.,
                   "label": "立即返航", "completion_pct": 0.}]
    return Finding(key, active, severity=severity, title=key, candidates=candidates,
                   evidence=[{"id": "E1", "text": key, "value": "30%"}],
                   rule_choice=ident)


def assess(eng, t, *, p1=False, p2=False, p3=False, severity2=2, missing=(), sources=None):
    sources = sources or feed(eng, missing, t=t)
    f1 = member("battery_route", p1)
    f2 = member("rtl_point", p2, severity2)
    f3 = member("battery_capacity", p3, ident="C9")
    with patch.object(eng, "_available_wh", return_value=(300., "soc", 400.)), \
         patch.object(eng, "_battery_route", return_value=[f1, f2]), \
         patch.object(eng, "_battery_capacity", return_value=f3):
        return eng.update_sources(sources, t)


class BatteryMerge0452Tests(unittest.TestCase):
    def test_one_key_highest_severity_title_and_p1_options(self):
        eng = engine()
        rows = assess(eng, 0., p1=True, p2=True, p3=True)
        battery = [r for r in rows if r["key"] == "battery"]
        self.assertEqual(len(battery), 1)
        row = battery[0]
        self.assertEqual((row["severity"], row["title"]), (2, "rtl_point"))
        self.assertEqual([c["id"] for c in row["candidates"]], ["C4"])
        self.assertEqual([e["id"] for e in row["evidence"]], ["E1", "E2", "E3"])
        self.assertEqual([e["source_predictor"] for e in row["evidence"]], ["P1", "P2", "P3"])
        self.assertTrue(all(e["source_evidence_id"] == "E1" for e in row["evidence"]))
        self.assertFalse(set(eng._states.states) & {"battery_route", "rtl_point", "battery_capacity"})
        self.assertEqual(eng.current_state("battery")["feasible_ids"], ["C4"])

    def test_missing_p1_never_borrows_capacity_options(self):
        eng = engine()
        row = next(r for r in assess(eng, 0., p3=True, missing=("position",))
                   if r["key"] == "battery")
        self.assertEqual((row["severity"], row["rule_decision"]), (2, "HOLD"))
        self.assertEqual(row["candidates"], [])
        self.assertEqual(row["member_status"]["P1"]["truth"], "UNKNOWN")
        self.assertEqual(row["member_status"]["P3"]["truth"], "TRUE")

    def test_p3_can_use_valid_inactive_p1_options(self):
        eng = engine()
        rows = []
        for t in (0., .5, 1.):
            rows += assess(eng, t, p3=True)
        row = next(r for r in rows if r["key"] == "battery")
        self.assertEqual((row["severity"], row["rule_choice"]), (4, "C4"))
        self.assertEqual(row["member_status"]["P1"]["truth"], "FALSE")

    def test_cached_member_retains_original_time_when_other_source_advances(self):
        eng = engine()
        sources = feed(eng, t=0.)
        assess(eng, 0., p3=True, sources=sources)
        for t in (.5, 1.):
            sources.put("position", (t, 0., 50.), t, t)
            sources.put("next_wp", 0, t, t)
            rows = assess(eng, t, p3=False, sources=sources)
        row = next(r for r in rows if r["key"] == "battery")
        self.assertEqual(row["member_status"]["P3"]["truth"], "TRUE")
        self.assertEqual(row["member_status"]["P3"]["sensed_t"], 0.)
        self.assertEqual(next(e for e in row["evidence"] if e["source_predictor"] == "P3")["sensed_t"], 0.)

    def test_polling_cannot_confirm_warning(self):
        eng = engine()
        sources = feed(eng, t=0.)
        self.assertEqual(assess(eng, 0., p1=True, sources=sources), [])
        for t in (.5, 1., 2.):
            self.assertEqual(assess(eng, t, p1=True, sources=sources), [])
        self.assertFalse(eng._states.states["battery"].active)
        self.assertEqual(eng._states.states["battery"].true_count, 1)

    def test_expired_member_is_unknown_and_cannot_clear(self):
        eng = engine()
        assess(eng, 0., p2=True)
        for t in (1., 2., 11.):
            assess(eng, t, missing=("current",))
        self.assertIn("battery", eng.active())
        self.assertTrue(eng.active()["battery"].prediction_expired)
        self.assertFalse(eng.current_state("battery")["active"])
        self.assertEqual(eng.last_state["battery_members"]["P3"]["truth"], "UNKNOWN")

    def test_only_all_valid_false_for_ten_seconds_clears_group(self):
        eng = engine()
        assess(eng, 0., p2=True)
        for t in range(1, 11):
            self.assertFalse(any(r["type"] == "resolve" for r in assess(eng, float(t))))
        rows = assess(eng, 11.)
        self.assertEqual([(r["key"], r["type"]) for r in rows], [("battery", "resolve")])

    def test_p2_alert_does_not_latch_p1_hysteresis(self):
        eng = engine()
        assess(eng, 0., p2=True)
        self.assertTrue(eng._states.states["battery"].active)
        self.assertFalse(eng._battery_p1_active)

    def test_p1_hysteresis_still_waits_for_confirmation_and_clear(self):
        eng = engine()
        assess(eng, 0., p1=True)
        self.assertFalse(eng._battery_p1_active)
        assess(eng, .5, p1=True)
        self.assertFalse(eng._battery_p1_active)
        assess(eng, 1., p1=True)
        self.assertTrue(eng._battery_p1_active)
        for t in range(2, 12):
            assess(eng, float(t))
            self.assertTrue(eng._battery_p1_active)
        assess(eng, 12.)
        self.assertFalse(eng._battery_p1_active)

    def test_empty_route_disables_p1_p2_and_preserves_p3(self):
        eng = engine()
        eng.set_route([])
        row = next(r for r in assess(eng, 0., p3=True) if r["key"] == "battery")
        self.assertTrue(row["member_status"]["P1"]["disabled"])
        self.assertTrue(row["member_status"]["P2"]["disabled"])
        self.assertEqual(row["member_status"]["P3"]["truth"], "TRUE")
        self.assertEqual((row["candidates"], row["rule_decision"]), ([], "HOLD"))

    def test_changed_route_cannot_reuse_old_p1_options(self):
        eng = engine()
        assess(eng, 0., p2=True)
        eng.set_route([(300., 0., 50.)])
        row = next(r for r in assess(eng, 1., p3=True, missing=("position",))
                   if r["key"] == "battery")
        self.assertEqual((row["candidates"], row["rule_choice"]), ([], None))

    def test_new_slower_member_signature_is_not_dropped_by_equal_max_timestamp(self):
        core = AlertEngine()
        first = core.step("battery", 10., TRUE, CRITICAL,
                          sensed_t=10., recv_t=10., assessment_id="P1=10;P3=9")
        self.assertEqual(first[0]["type"], "raise")
        core.step("battery", 10.5, TRUE, CRITICAL,
                  sensed_t=10., recv_t=10., assessment_id="P1=10;P3=9.5")
        self.assertEqual(core.states["battery"].last_t, 10.5)
        self.assertEqual(core.dropped, {})
        self.assertEqual(core.step("battery", 11., TRUE, CRITICAL,
                                  sensed_t=10., recv_t=10., assessment_id="P1=10;P3=9.5"), [])
        self.assertEqual(core.dropped["battery"], 1)


if __name__ == "__main__":
    unittest.main()
