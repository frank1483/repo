"""NEW synthetic checks; Claude executes once and preserves the first failure."""
import copy
import math
import unittest
from dataclasses import replace
from .energy import (Wind, Vehicle, bounds, estimate_for_bounds, leg_estimate,
                     load_airframe, route_estimate)


def loop():
    return [{"id": "H", "lat": 0, "lon": 0, "alt": 0},
            {"id": "A", "lat": .01, "lon": 0, "alt": 60},
            {"id": "H", "lat": 0, "lon": 0, "alt": 0}]


def hybrid():
    return [{"id": "H", "lat": 0, "lon": 0, "alt": 0, "kind": "takeoff"},
            {"id": "U", "lat": 0, "lon": 0, "alt": 60, "kind": "takeoff"},
            {"cmd": 3000, "to_mode": "fw"},
            {"id": "A", "lat": .01, "lon": 0, "alt": 60},
            {"cmd": 3000, "to_mode": "mc"},
            {"id": "R", "lat": 0, "lon": 0, "alt": 60},
            {"id": "L", "lat": 0, "lon": 0, "alt": 0, "kind": "landing"}]


def result(v=None, w=None, points=None, speed=8, start=100, mode=None):
    v = v or load_airframe("x500")
    return bounds(estimate_for_bounds(v, points or loop(), speed, w or Wind(3, 0), start, mode=mode), v)


def vector_rows():
    rows = []
    for speed in (0, 3, 8):
        b = result(w=Wind(speed, 25))
        rows.append([b["available"], len(b["scenarios"]), b["low_pct"], b["high_pct"],
                     b["nominal"]["energy_wh"], b["nominal"]["end_pct"]])
    b = result(v=load_airframe("vtol_example"), points=hybrid(), speed=16)
    rows.append([b["available"], len(b["scenarios"]), b["low_pct"], b["high_pct"],
                 b["nominal"]["energy_wh"], b["nominal"]["end_pct"]])
    return rows


class TestBounds(unittest.TestCase):
    def assertNear(self, a, b):
        self.assertAlmostEqual(a, b, delta=2e-9 * max(1, abs(a), abs(b)))

    def test_nominal_replays_complete_loop(self):
        v = load_airframe("x500")
        b = result(v)
        e = route_estimate(v, loop(), 8, Wind(3, 0), 100, 0)
        self.assertNear(b["nominal"]["energy_wh"], e["energy_wh"])

    def test_one_wind_outbound_and_return_independent_oracle(self):
        v = load_airframe("x500")
        for row in result(v)["scenarios"]:
            speed = row["wind"]["speed_mps"]
            # Due north then south: SAME north-from wind gives 8+w and |8-w| airspeeds.
            seconds = 6371000 * math.radians(.01) / 8
            watts = lambda a: 190 + .5 * 1.225 * .12 * a ** 3 / .7
            joules = (watts(8 + speed) + watts(abs(8 - speed))) * seconds
            joules += 2 * 9.81 * 60 / .7 + 190 * (60 / 3 + 60 / 2)
            self.assertNear(row["base_energy_wh"], joules / 3600)
            self.assertNear(row["legs"][0]["headwind_mps"], speed)
            self.assertNear(row["legs"][1]["headwind_mps"], -speed)

    def test_endpoint_pct_with_capacity_and_start(self):
        b = result(start=72)
        for row in b["scenarios"]:
            self.assertNear(row["end_pct"], 72 - row["energy_wh"] / row["capacity_wh"] * 100)

    def test_extrema_are_actual_scenarios(self):
        b = result()
        self.assertEqual(b["low_pct"], min(r["end_pct"] for r in b["scenarios"]))
        self.assertEqual(b["high_pct"], max(r["end_pct"] for r in b["scenarios"]))
        self.assertIn(b["conservative"], b["scenarios"])
        self.assertIn(b["optimistic"], b["scenarios"])

    def test_deduplicate_zero_uncertainty(self):
        v = load_airframe("x500")
        v.airframe_profile["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
        b = result(v)
        self.assertEqual(len(b["scenarios"]), 1)
        self.assertEqual(b["low_pct"], b["high_pct"])

    def test_wind_speed_clamped_nonnegative(self):
        b = result(w=Wind(0, 15))
        self.assertTrue(all(r["wind"]["speed_mps"] >= 0 for r in b["scenarios"]))
        self.assertEqual(len(b["scenarios"]), 9)

    def test_hybrid_transition_scaled_once_and_modeled_landing(self):
        b = result(v=load_airframe("vtol_example"), points=hybrid(), speed=16)
        self.assertTrue(b["available"])
        for row in b["scenarios"]:
            self.assertNear(row["energy_wh"], sum(x["energy_wh"] for x in row["legs"]) * row["power_multiplier"])
            self.assertEqual([x["to_mode"] for x in row["legs"] if "to_mode" in x], ["fw", "mc"])
            self.assertTrue(row["landing_modeled"])

    def test_unsupported_arc_invalidates_whole_interval(self):
        v = load_airframe("fw_example")
        points = [{"lat": 0, "lon": 0, "alt": 60}, {"lat": .01, "lon": 0, "alt": 60},
                  {"lat": .01, "lon": .01, "alt": 60}]
        b = result(v=v, points=points, speed=16, w=Wind())
        self.assertFalse(b["available"])
        self.assertIsNone(b["low_pct"])
        self.assertIsNone(b["optimistic"])
        self.assertEqual(b["nominal"]["status"], "ok")
        self.assertTrue(any(r["status"] == "unsupported" for r in b["scenarios"]))

    def test_no_replay_context_rejected(self):
        with self.assertRaises(ValueError):
            bounds({"energy_wh": 1}, load_airframe("x500"))

    def test_vehicle_snapshot_mismatch_rejected(self):
        v = load_airframe("x500")
        e = estimate_for_bounds(v, loop(), 8, Wind())
        with self.assertRaises(ValueError):
            bounds(e, replace(v, calib=1.1))

    def test_inputs_detached_and_unchanged(self):
        v = load_airframe("x500")
        p = loop()
        before = copy.deepcopy((p, v.to_dict()))
        e = estimate_for_bounds(v, p, 8, Wind())
        bounds(e, v)
        self.assertEqual((p, v.to_dict()), before)
        p[1]["lat"] = .02
        self.assertEqual(e["bounds_context"]["route"][1]["lat"], .01)

    def test_stale_result_numbers_are_not_trusted(self):
        v = load_airframe("x500")
        e = estimate_for_bounds(v, loop(), 8, Wind())
        expected = bounds(e, v)
        e["energy_wh"], e["end_pct"] = 0, 100
        self.assertEqual(bounds(e, v), expected)

    def test_invalid_runtime_numbers_rejected(self):
        v = load_airframe("x500")
        for speed in (0, True, float("nan"), -1):
            with self.assertRaises(ValueError):
                estimate_for_bounds(v, loop(), speed, Wind())
        for start in (-1, 101, True):
            with self.assertRaises(ValueError):
                estimate_for_bounds(v, loop(), 8, Wind(), start)

    def test_no_profile_uncertainty_rejected(self):
        v = Vehicle()
        with self.assertRaises(ValueError):
            bounds(estimate_for_bounds(v, loop(), 8, Wind()), v)

    def test_negative_pct_not_clamped(self):
        self.assertLess(result(start=0)["low_pct"], 0)

    def test_no_return_or_landing_inference(self):
        b = result(points=loop()[:2])
        self.assertFalse(b["return_inferred"])
        self.assertFalse(b["nominal"]["landing_modeled"])
        self.assertEqual(len(b["nominal"]["legs"]), 1)

    def test_invalid_context_schema_rejected(self):
        v = load_airframe("x500")
        for change in ({"schema": True}, {"extra": 1}):
            e = estimate_for_bounds(v, loop(), 8, Wind())
            e["bounds_context"].update(change)
            with self.assertRaises(ValueError):
                bounds(e, v)

    def test_invalid_capacity_uncertainty_rejected(self):
        v = load_airframe("x500")
        v.airframe_profile["uncertainty"]["capacity_pct"] = 100
        with self.assertRaises(ValueError):
            result(v)

    def test_multirotor_rejects_mode_events(self):
        v = load_airframe("x500")
        with self.assertRaisesRegex(ValueError, "hybrid"):
            estimate_for_bounds(v, [loop()[0], {"cmd": 3000, "to_mode": "fw"}], 8, Wind())


if __name__ == "__main__":
    unittest.main()
