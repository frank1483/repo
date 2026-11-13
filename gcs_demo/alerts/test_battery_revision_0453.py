"""0453 first-run controls; execute only in Claude's rules-only environment."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

from .core.state_machine import AlertEngine
from .predict import Finding
from .test_predict_sources_0447 import engine, feed, telemetry
from .test_battery_merge_0452 import member


def snapshot(eng):
    """Include every field, with value comparison for identity-only engines."""
    return deepcopy({key: vars(value) if isinstance(value, AlertEngine) else value
                     for key, value in vars(eng).items()})


class BatteryRevision0453Tests(unittest.TestCase):
    def test_sync_rejection_preserves_both_engines_and_same_timestamp_retry(self):
        eng = engine()
        eng.update(telemetry(0.))
        before = snapshot(eng)
        states, p1_states = eng._states, eng._battery_p1_states
        with self.assertRaises(ValueError):
            eng.update(replace(telemetry(1.), next_wp=999))
        self.assertIs(eng._states, states)
        self.assertIs(eng._battery_p1_states, p1_states)
        self.assertEqual(snapshot(eng), before)
        eng.update(telemetry(1.))
        self.assertEqual(eng._last_tm_t, 1.)

    def test_async_rejection_preserves_both_engines_and_same_timestamp_retry(self):
        eng = engine()
        eng.update_sources(feed(eng, t=0.), 0.)
        before = snapshot(eng)
        states, p1_states = eng._states, eng._battery_p1_states
        sources = feed(eng, missing=("next_wp",), t=1.)
        sources.put("next_wp", 999, 1., 1.)
        with self.assertRaises(ValueError):
            eng.update_sources(sources, 1.)
        self.assertIs(eng._states, states)
        self.assertIs(eng._battery_p1_states, p1_states)
        self.assertEqual(snapshot(eng), before)
        eng.update_sources(feed(eng, t=1.), 1.)
        self.assertEqual(eng._last_tm_t, 1.)

    def test_content_snapshot_detects_private_engine_mutation(self):
        eng = engine()
        eng.update(telemetry(0.))
        before = snapshot(eng)
        eng._battery_p1_states.engine_seq += 1
        self.assertNotEqual(snapshot(eng), before)

    def test_route_change_c3_none_c1_keeps_only_p1_actions(self):
        eng = engine()
        rows = []
        for t in range(5):
            if t == 1:
                eng.set_route([(100., 0., 50.)])
            ident = "C3" if t == 0 else "C1"
            action = "A_RTL_AFTER_WP" if t == 0 else "A_CONTINUE"
            candidate = deepcopy(member("battery_route").candidates[0])
            candidate.update(id=ident, action=action,
                             option_identity=eng._option_identity(ident, action),
                             label="P1 route option")
            p1 = Finding("battery_route", t == 0, severity=4,
                         candidates=[candidate], rule_choice=ident)
            p2 = member("rtl_point", True, severity=2)
            # Same numeric id as P1 after the route change; provenance is ACTION,
            # never an id-only assertion that could accept P3's estimate option.
            p3 = Finding("battery_capacity", True, severity=4, rule_choice="C1",
                         candidates=[{"id": "C1", "action": "A_USE_VOLTAGE_ESTIMATE",
                                      "feasible": True, "label": "P3 estimate"}])
            with patch.object(eng, "_available_wh", return_value=(300., "soc", 400.)), \
                 patch.object(eng, "_battery_route", return_value=[p1, p2]), \
                 patch.object(eng, "_battery_capacity", return_value=p3):
                events = eng.update_sources(feed(eng, t=float(t)), float(t))
            active = eng.active()["battery"]
            self.assertEqual(active.candidates, [candidate])
            for event in events:
                if event["key"] == "battery":
                    self.assertEqual(event["candidates"], [candidate])
                    rows.append(event)
            if t in (1, 2, 3):
                self.assertIsNone(active.rule_choice)
        self.assertEqual([r["rule_choice"] for r in rows], ["C3", None, "C1"])
        self.assertEqual([r["t"] for r in rows], [0., 1., 4.])
        self.assertEqual(rows[-1]["candidates"][0]["action"], "A_CONTINUE")


if __name__ == "__main__":
    unittest.main()
