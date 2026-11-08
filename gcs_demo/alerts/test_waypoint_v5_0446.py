"""0446 route-cursor boundary regressions; no model or hardware I/O."""
from copy import deepcopy
import unittest

from .energy_api import Wind, default_vehicle
from .predict import PredictiveAlertEngine, Telemetry


ROUTE = [(100, 0, 60), (200, 0, 60)]


def telemetry(index=0, t=0):
    return Telemetry(t, (0, 0, 60), (0, 0, 0), 80, 23, 10, 0,
                     6, index, 95, Wind(0, 0))


def engine(route=ROUTE):
    return PredictiveAlertEngine(route, (0, 0, 0), default_vehicle())


class Waypoint0446(unittest.TestCase):
    def test_outside_both_boundaries_raises(self):
        for index in (-1, len(ROUTE) + 1, 999):
            with self.subTest(index=index), self.assertRaises(ValueError):
                engine().update(telemetry(index))

    def test_nonintegral_missing_nonfinite_and_bool_rejected(self):
        for index in (0.5, None, "1", True, False, float("nan"),
                      float("inf"), float("-inf")):
            with self.subTest(index=index), self.assertRaises(ValueError):
                engine().update(telemetry(index))

    def test_valid_route_and_completed_sentinel(self):
        for index in (0, len(ROUTE) - 1, len(ROUTE), 1.0):
            with self.subTest(index=index):
                eng = engine()
                self.assertIsInstance(eng.update(telemetry(index)), list)
                self.assertEqual(eng._reached, set(range(int(index))))
                self.assertEqual(eng.last_state["input_error"], None)

    def test_empty_route_accepts_only_zero(self):
        eng = engine([])
        self.assertIsInstance(eng.update(telemetry(0)), list)
        for index in (-1, 1):
            with self.subTest(index=index), self.assertRaises(ValueError):
                eng.update(telemetry(index, 1))

    def test_rejection_preserves_state_and_same_timestamp_retry(self):
        eng = engine()
        eng.update(telemetry(0, 0))
        before = deepcopy(eng.__dict__)
        with self.assertRaises(ValueError):
            eng.update(telemetry(999, 1))
        # AlertEngine has identity equality, so compare its field dictionary
        # separately; all other fields retain their native equality checks.
        self.assertEqual(eng._states.__dict__, before["_states"].__dict__)
        for key in before.keys() - {"_states"}:
            self.assertEqual(eng.__dict__[key], before[key], key)
        eng.update(telemetry(1, 1))
        self.assertEqual(eng._last_tm_t, 1)
        self.assertEqual(eng._reached, {0})

    def test_duplicate_timestamp_does_not_hide_bad_waypoint(self):
        eng = engine()
        eng.update(telemetry(0, 1))
        with self.assertRaises(ValueError):
            eng.update(telemetry(-1, 1))


if __name__ == "__main__":
    unittest.main()
