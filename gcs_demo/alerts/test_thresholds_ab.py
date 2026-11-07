"""A/B threshold regressions: deterministic local fixtures, no model/devices.

Run once on a fresh patched fd40ee8 tree:
    python -m unittest gcs_demo.alerts.test_thresholds_ab -v
"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from .core.freshness import TRUE
from .core.state_machine import AlertEngine
from .energy_api import Wind, default_vehicle
from .predict import Config, Finding, PredictiveAlertEngine, SEV_WARNING, SEV_NOTICE


def engine(config=None):
    return PredictiveAlertEngine([(1000, 0, 60)], (0, 0, 0), default_vehicle(), config)


def energy_finding(eng, raw, *, feasible=True, identity="C4", key="battery_route"):
    candidate = {"id": "C4", "option_identity": identity, "action": "A_RTL_NOW",
                 "end_pct_raw": raw, "end_pct": round(raw, 1),
                 "feasible": feasible and eng._is_feasible(raw, identity)}
    return Finding(key, True, severity=SEV_WARNING,
                   candidates=[candidate], rule_choice="C4")


class LinkThresholdsAB(unittest.TestCase):
    def link_sample(self, eng, t, seconds):
        # Keep fit confidence/distance fixed and vary only time to the weak leg.
        if not eng._link_hist:
            eng._link_hist.extend((i * 10, 100 - i) for i in range(60))
        tm = SimpleNamespace(t=t, pos=(0, 0, 60), link_pct=100,
                             next_wp=0, wind=Wind(0, 0))
        with patch("gcs_demo.alerts.predict.linfit", return_value=(-0.1, 100, 1)), \
             patch("gcs_demo.alerts.predict.leg_energy", return_value={"time_s": seconds}):
            f = eng._link(tm)
        rows = eng._debounce(t, f)
        return f, rows

    def test_119_130_140_149_then_151_ten_seconds_and_immediate_reentry(self):
        eng = engine()
        for t in range(4):
            self.link_sample(eng, t, 119)
        self.assertEqual(eng._states.states["link_route"].severity, SEV_WARNING)
        for t, seconds in enumerate((130, 140, 149, 150), 4):
            f, _ = self.link_sample(eng, t, seconds)
            self.assertEqual(f.severity, SEV_WARNING)
        for t in range(8, 18):
            self.link_sample(eng, t, 151)
            self.assertEqual(eng._states.states["link_route"].severity, SEV_WARNING)
        _, rows = self.link_sample(eng, 18, 151)
        self.assertEqual(rows[-1]["severity"], SEV_NOTICE)
        _, rows = self.link_sample(eng, 19, 120)
        self.assertEqual(rows[-1]["severity"], SEV_WARNING)

    def test_return_to_150_interrupts_downgrade_continuity(self):
        eng = engine()
        for t in range(4):
            self.link_sample(eng, t, 119)
        for t in range(4, 10):
            self.link_sample(eng, t, 151)
        self.link_sample(eng, 10, 150)
        for t in range(11, 21):
            self.link_sample(eng, t, 151)
            self.assertEqual(eng._states.states["link_route"].severity, SEV_WARNING)
        self.link_sample(eng, 21, 151)
        self.assertEqual(eng._states.states["link_route"].severity, SEV_NOTICE)

    def test_band_does_not_create_warning_without_a_warning_state(self):
        eng = engine()
        for t in range(4):
            f, _ = self.link_sample(eng, t, 130)
            self.assertEqual(f.severity, SEV_NOTICE)
        self.assertEqual(eng._states.states["link_route"].severity, SEV_NOTICE)

    def test_config_thresholds_are_used(self):
        eng = engine(Config(link_warn_enter_s=100, link_warn_exit_s=110))
        for t in range(4):
            self.link_sample(eng, t, 100)
        self.assertEqual(self.link_sample(eng, 4, 110)[0].severity, SEV_WARNING)
        self.assertEqual(self.link_sample(eng, 5, 111)[0].severity, SEV_NOTICE)


class RecommendationThresholdsAB(unittest.TestCase):
    def test_21_block_22_three_seconds_20_5_retain_19_9_withdraw(self):
        eng = engine()
        for t in range(4):
            eng._debounce(t, energy_finding(eng, 21))
        self.assertIsNone(eng._states.states["battery_route"].recommendation)
        for t in range(4, 7):
            eng._debounce(t, energy_finding(eng, 22))
            self.assertIsNone(eng._states.states["battery_route"].recommendation)
        eng._debounce(7, energy_finding(eng, 22))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")
        eng._debounce(8, energy_finding(eng, 20.5))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")
        eng._debounce(9, energy_finding(eng, 20))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")
        rows = eng._debounce(10, energy_finding(eng, 19.9))
        self.assertIsNone(eng._states.states["battery_route"].recommendation)
        self.assertEqual(rows[-1]["rule_decision"], "HOLD")
        self.assertIsNone(rows[-1]["rule_choice"])

    def test_nonenergy_failure_withdraws_immediately_even_above_22(self):
        eng = engine()
        for t in range(4):
            eng._debounce(t, energy_finding(eng, 40))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")
        rows = eng._debounce(4, energy_finding(eng, 40, feasible=False))
        self.assertIsNone(eng._states.states["battery_route"].recommendation)
        self.assertIsNone(rows[-1]["rule_choice"])

    def test_initial_raise_includes_recommendation_without_extra_update(self):
        eng = engine()
        self.assertEqual(eng._debounce(0, energy_finding(eng, 22)), [])
        self.assertEqual(eng._debounce(.5, energy_finding(eng, 22)), [])
        rows = eng._debounce(1, energy_finding(eng, 22))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "raise")
        self.assertEqual(rows[0]["rule_choice"], "C4")
        for t in (2, 3):
            self.assertEqual(eng._debounce(t, energy_finding(eng, 22)), [])

    def test_drop_below_entry_before_adoption_resets_the_three_seconds(self):
        eng = engine()
        for t in range(4):
            eng._debounce(t, energy_finding(eng, 21))
        eng._debounce(4, energy_finding(eng, 22))
        eng._debounce(5, energy_finding(eng, 21.99))
        for t in range(6, 9):
            eng._debounce(t, energy_finding(eng, 22))
            self.assertIsNone(eng._states.states["battery_route"].recommendation)
        eng._debounce(9, energy_finding(eng, 22))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")

    def test_entry_is_per_alert_not_shared_option_qualification(self):
        eng = engine()
        for t in range(4):
            eng._debounce(t, energy_finding(eng, 30))
        eng._debounce(4, energy_finding(eng, 21, key="rtl_point"))
        self.assertIsNone(eng._states.states["rtl_point"].recommendation)
        eng._debounce(4, energy_finding(eng, 21))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")

    def test_reranks_eligible_alternative_instead_of_holding_for_21_winner(self):
        eng = engine()
        for t in range(4):
            f = energy_finding(eng, 21)
            f.candidates.append({"id": "C6", "action": "A_SKIP_OPTIONAL",
                                 "end_pct_raw": 23, "feasible": True})
            eng._debounce(t, f)
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C6")

    def test_monitor_has_no_landing_estimate_and_can_fail_nonenergy_condition(self):
        eng = engine()
        def monitor(ok=True):
            return Finding("wind_trend", True, severity=SEV_WARNING, rule_choice="C1",
                           candidates=[{"id": "C1", "action": "A_CONTINUE_MONITOR",
                                        "feasible": ok}])
        for t in range(4):
            eng._debounce(t, monitor())
        self.assertEqual(eng._states.states["wind_trend"].recommendation, "C1")
        rows = eng._debounce(4, monitor(False))
        self.assertIsNone(rows[-1]["rule_choice"])

    def test_changed_identity_requires_new_entry_qualification(self):
        eng = engine()
        for t in range(4):
            eng._debounce(t, energy_finding(eng, 30, identity="route0"))
        rows = eng._debounce(4, energy_finding(eng, 21, identity="route1"))
        self.assertIsNone(rows[-1]["rule_choice"])
        self.assertIsNone(eng._states.states["battery_route"].recommendation)

    def test_missing_nan_and_rounded_22_do_not_qualify_flight_advice(self):
        eng = engine()
        for c in ({"feasible": True, "action": "A_RTL_NOW", "end_pct": 22},
                  {"feasible": True, "action": "A_RTL_NOW", "end_pct_raw": float("nan")},
                  {"feasible": True, "action": "A_RTL_NOW", "end_pct_raw": 21.99}):
            self.assertFalse(eng._recommendation_eligible(c))

    def test_unknown_resets_pending_recommendation_change_confirmation(self):
        eng = engine()
        # First raise is HOLD because raw 21 is below the new-adoption gate.
        for t in range(4):
            eng._debounce(t, energy_finding(eng, 21))
        eng._debounce(4, energy_finding(eng, 22))
        eng._unknown(5, "battery_route")
        for t in range(6, 9):
            eng._debounce(t, energy_finding(eng, 22))
            self.assertIsNone(eng._states.states["battery_route"].recommendation)
        eng._debounce(9, energy_finding(eng, 22))
        self.assertEqual(eng._states.states["battery_route"].recommendation, "C4")

    def test_existing_direct_core_callers_keep_initial_recommendation_behavior(self):
        core = AlertEngine()
        core.step("x", 0, TRUE, recommendation="C1", feasible_ids={"C1"})
        core.step("x", .5, TRUE, recommendation="C1", feasible_ids={"C1"})
        rows = core.step("x", 1, TRUE, recommendation="C1", feasible_ids={"C1"})
        self.assertEqual(rows[-1]["recommendation"], "C1")


if __name__ == "__main__":
    unittest.main()
