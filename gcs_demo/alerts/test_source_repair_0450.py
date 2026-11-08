"""0450 regression drafts. Claude runs first execution; no model/devices."""
import unittest
from unittest.mock import patch

from .energy_api import Wind, default_vehicle
from .predict import PredictiveAlertEngine, Telemetry, Finding


def engine():
    return PredictiveAlertEngine([(3000, 0, 60), (5000, 0, 60)],
                                 (0, 0, 0), default_vehicle())


def sample(t):
    return Telemetry(t, (100, 0, 60), (12, 0, 0), 80, 23, 20, 0,
                     6, 0, 90, Wind(3, 90))


class SourceRepair0450(unittest.TestCase):
    def test_fresh_route_uses_previous_valid_duration_for_wind_trend(self):
        eng = engine()
        eng.update(sample(0))
        previous_duration = eng.last_state["rem_s"]
        self.assertGreater(previous_duration, 100)
        eng._wind_trend = (.01, 1)
        original = eng._plan_wind
        observed = []

        def capture(tm):
            result = original(tm)
            observed.append((eng.last_state["rem_s"], result.speed_mps))
            return result

        with patch.object(eng, "_wind", return_value=Finding("wind_trend", False)), \
             patch.object(eng, "_plan_wind", side_effect=capture):
            eng.update(sample(1))
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], previous_duration)
        self.assertGreater(observed[0][1], sample(1).wind.speed_mps)
        self.assertEqual(eng.last_state["predictor_readiness"]["battery_route"]["status"], "ready")

    def test_invalid_geometry_does_not_retain_route_numbers(self):
        eng = engine()
        eng.update(sample(0))
        bad = sample(1)
        bad.pos = None
        eng.update(bad)
        self.assertEqual(eng.last_state["rem_s"], 0)
        self.assertIsNone(eng.last_state["end_pct"])

    def test_predictor_failure_clears_duration_and_does_not_reuse_old_forecast(self):
        eng = engine()
        eng.update(sample(0))
        with patch.object(eng, "_battery_route", side_effect=RuntimeError("injected")):
            eng.update(sample(1))
        self.assertEqual(eng.last_state["rem_s"], 0)
        self.assertIsNone(eng.last_state["end_pct"])
        self.assertEqual(eng.last_state["predictor_errors"]["battery_route"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
