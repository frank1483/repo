"""New HOLD controls; first Python execution belongs to Claude."""
import unittest
from dataclasses import replace

from .predict import (PredictiveAlertEngine, Finding, HOLD_ZH, PENDING_ZH,
                      SEV_CRITICAL, SEV_WARNING, SEV_NOTICE)
from .energy_api import default_vehicle


def engine():
    return PredictiveAlertEngine([(200., 0., 50.)], (0., 0., 0.), default_vehicle())


def candidate(feasible=True):
    return {"id": "C4", "action": "A_RTL_NOW", "feasible": feasible,
            "energy_feasible": feasible, "end_pct_raw": 30., "end_pct": 30.,
            "completion_pct": 0., "label": "立即返航"}


def finding(*, active=True, severity=SEV_NOTICE, feasible=False):
    return Finding("battery_route", active, severity=severity, title="電量告警",
                   candidates=[candidate(feasible)], rule_choice="C4" if feasible else None)


class Hold0451Tests(unittest.TestCase):
    def test_no_feasible_plan_raises_critical_immediately(self):
        eng = engine()
        original = finding()
        rows = eng._debounce(0., original)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["type"], row["severity"], row["severity_zh"]),
                         ("raise", SEV_CRITICAL, "嚴重"))
        self.assertEqual((row["rule_decision"], row["rule_decision_zh"]),
                         ("HOLD", "無符合條件方案，請人工決策"))
        self.assertIsNone(row["rule_choice"])
        self.assertEqual(original.severity, SEV_NOTICE)  # no mutation of caller facts

    def test_no_candidates_is_also_critical_hold(self):
        eng = engine()
        row = eng._debounce(0., replace(finding(), candidates=[]))[0]
        self.assertEqual((row["severity"], row["rule_decision_zh"]), (SEV_CRITICAL, HOLD_ZH))

    def test_inactive_assessment_does_not_create_critical_alarm(self):
        eng = engine()
        for t in (0., 1., 2., 12.):
            self.assertEqual(eng._debounce(t, finding(active=False)), [])
        self.assertEqual(eng.active(), {})

    def test_existing_warning_upgrades_and_revokes_immediately(self):
        eng = engine()
        for t in (0., 1., 2.):
            eng._debounce(t, finding(severity=SEV_WARNING, feasible=True))
        self.assertEqual(eng.active()["battery_route"].rule_choice, "C4")
        rows = eng._debounce(3., finding(severity=SEV_WARNING))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["type"], row["severity"], row["rule_decision_zh"]),
                         ("update", SEV_CRITICAL, HOLD_ZH))
        self.assertIsNone(row["rule_choice"])
        self.assertIsNone(eng._states.states["battery_route"].recommendation)

    def test_critical_hold_bypasses_cooling(self):
        eng = engine()
        eng._debounce(0., finding())
        for t in range(1, 12):
            eng._debounce(float(t), finding(active=False))
        self.assertFalse(eng._states.states["battery_route"].active)
        row = eng._debounce(12., finding())[0]
        self.assertEqual((row["type"], row["severity"]), ("raise", SEV_CRITICAL))

    def test_feasible_pending_choice_retains_three_second_timer(self):
        eng = engine()
        eng._debounce(0., finding())
        rows = eng._debounce(1., finding(severity=SEV_CRITICAL, feasible=True))
        self.assertEqual(rows, [])
        state = eng._states.states["battery_route"]
        self.assertEqual(state.facts["rule_decision"], "HOLD")
        self.assertEqual(state.facts["rule_decision_zh"], PENDING_ZH)
        for t in (2., 3.):
            self.assertEqual(eng._debounce(t, finding(severity=SEV_CRITICAL, feasible=True)), [])
        row = eng._debounce(4., finding(severity=SEV_CRITICAL, feasible=True))[0]
        self.assertEqual((row["rule_decision"], row["rule_choice"]), ("SELECT", "C4"))
        self.assertEqual(eng._decision_zh("HOLD", [candidate()]), PENDING_ZH)
        self.assertNotEqual(row["rule_decision_zh"], HOLD_ZH)

    def test_metadata_survives_unknown_without_fabricating_new_event(self):
        eng = engine()
        eng._debounce(0., finding())
        self.assertEqual(eng._unknown(1., "battery_route"), [])
        self.assertEqual(eng._states.states["battery_route"].facts["rule_decision_zh"], HOLD_ZH)
        self.assertTrue(eng.active()["battery_route"].prediction_expired)


if __name__ == "__main__":
    unittest.main()
