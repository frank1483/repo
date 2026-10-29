"""NEW synthetic engineering controls; first execution belongs to Claude."""
import copy
import json
import math
import sys
import unittest
from dataclasses import replace

from .energy import (Wind, geographic_wind_route_estimate, load_airframe,
                     power_w)

METRES = math.pi * 6371000 / 180
ENTRY = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}


def target(east, north, entry=None, speed=16):
    p = ENTRY if entry is None else entry
    return {"kind": "straight", "lat": p["lat"] + north / METRES,
            "lon": (p["lon"] + east / (METRES * math.cos(math.radians(p["lat"]))) + 180) % 360 - 180,
            "alt": p["alt"], "ground_mps": speed}


def events(speed=0, loiter=False, clockwise=True, entry=None):
    t = 40 * math.pi / 2 / 16
    first = {"kind": "loiter" if loiter else "arc", "id": "turn", "v_air": 16,
             "clockwise": clockwise, "radius_m": 40}
    first.update({"duration_s": t} if loiter else {"angle_deg": 90})
    sign = 1 if clockwise else -1
    return [first, target(sign * 200 + speed * (t + 10), 40, entry, abs(sign * 16 + speed))]


def vectors():
    v = load_airframe("fw_example")
    rows = []
    for speed, loiter, clockwise, entry in [(0, False, True, ENTRY), (5, False, True, ENTRY),
                                            (3, True, True, ENTRY),
                                            (2, False, False, {**ENTRY, "lon": 179.9999})]:
        ev = events(speed, loiter, clockwise, entry)
        w = Wind(speed, 270)
        rows.append({"entry": entry, "events": ev, "wind": {"speed_mps": speed, "from_deg": 270},
                     "result": geographic_wind_route_estimate(v, entry, ev, w)})
    return rows


class TestGeographicWindRoute(unittest.TestCase):
    def setUp(self):
        self.v = load_airframe("fw_example")

    def run_route(self, ev=None, entry=None, wind=None, vehicle=None, **kwargs):
        return geographic_wind_route_estimate(self.v if vehicle is None else vehicle,
                                             ENTRY if entry is None else entry,
                                             events() if ev is None else ev,
                                             Wind() if wind is None else wind, **kwargs)

    def near(self, a, b):
        self.assertAlmostEqual(a, b, delta=1e-8 * max(1, abs(a), abs(b)))

    def test_north_straight_independent_distance_time_energy(self):
        r = self.run_route([target(0, 160)])
        self.near(r["straight_dist_m"], 160)
        self.near(r["time_s"], 10)
        self.near(r["energy_wh"], power_w(self.v, 16, "fw") * 10 / 3600)
        self.assertEqual(r["exit_geographic"]["alt"], 80)

    def test_arc_geography_and_energy_independently(self):
        r = self.run_route()
        t = 40 * math.pi / 2 / 16
        bank = math.degrees(math.atan(256 / (9.81 * 40)))
        self.near(r["energy_wh"], (power_w(self.v, 16, "fw", bank) * t + power_w(self.v, 16, "fw") * 10) / 3600)
        self.near(r["exit_local_m"]["east_m"], 200)
        self.near(r["exit_local_m"]["north_m"], 40)
        self.near(r["legs"][0]["exit_geographic"]["lat"], ENTRY["lat"] + 40 / METRES)
        self.assertEqual(r["legs"][1]["entry_geographic"], r["legs"][0]["exit_geographic"])
        self.assertEqual(r["legs"][0]["id"], "turn")

    def test_wind_drift_and_loiter(self):
        a = self.run_route(events(5), wind=Wind(5, 270))
        b = self.run_route(events(5, True), wind=Wind(5, 270))
        self.near(a["energy_wh"], b["energy_wh"])
        self.near(a["legs"][1]["straight_dist_m"], 210)
        self.assertGreater(a["projection"]["path_budget_m"], a["air_dist_m"])

    def test_date_line_shortest_interval(self):
        entry = {**ENTRY, "lat": 0, "lon": 179.999, "air_heading_deg": 90}
        r = self.run_route([{"kind": "straight", "lat": 0, "lon": -179.999,
                             "alt": 80, "ground_mps": 16}], entry)
        self.near(r["straight_dist_m"], .002 * METRES)
        self.near(r["exit_geographic"]["lon"], -179.999)

    def test_hemisphere_and_wrapped_heading(self):
        entry = {**ENTRY, "lat": -45, "lon": -120, "air_heading_deg": 360}
        r = self.run_route([target(0, 160, entry)], entry)
        self.near(r["straight_dist_m"], 160)

    def test_no_invented_connector_or_acceleration(self):
        with self.assertRaisesRegex(ValueError, "not tangent"):
            self.run_route([target(160, 0)])
        ev = events(); ev[1]["ground_mps"] = 17
        with self.assertRaisesRegex(ValueError, "airspeed discontinuity"):
            self.run_route(ev)

    def test_strict_geographic_schema_and_altitude(self):
        bad = [[], [None], [{"kind": "unknown"}], [{**target(0, 160), "east_m": 0}],
               [{**target(0, 160), "alt": 81}], [{**target(0, 160), "lat": True}],
               [{**target(0, 160), "id": "\U0001f680" * 129}],
               [{**events()[0], "lat": 23}], [{**events()[0], "clockwise": None}],
               [{"kind": "straight", "lat": 23, "lon": 120, "ground_mps": 16}]]
        for ev in bad:
            with self.subTest(ev=ev), self.assertRaises(ValueError):
                self.run_route(ev)
        with self.assertRaises(ValueError):
            self.run_route(entry={**ENTRY, "cmd": 16})

    def test_polar_and_distant_targets_rejected(self):
        with self.assertRaises(ValueError):
            self.run_route(entry={**ENTRY, "lat": 76})
        with self.assertRaisesRegex(ValueError, "10 km local frame"):
            self.run_route([target(0, 11000)])

    def test_full_circle_excursion_budget_not_just_endpoint(self):
        with self.assertRaisesRegex(ValueError, "cumulative path budget"):
            self.run_route([{"kind": "loiter", "v_air": 16, "duration_s": 800,
                             "clockwise": True, "radius_m": 40}])

    def test_explicit_hybrid_fw_and_mc_rejection(self):
        h = load_airframe("vtol_example")
        self.assertEqual(self.run_route(vehicle=h, mode="fw")["arrival_mode"], "fw")
        for v, mode in [(h, None), (h, "mc"), (load_airframe("x500"), None)]:
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                self.run_route(vehicle=v, mode=mode)

    def test_detached_inputs_and_calibration_once(self):
        ev, en, w = events(), copy.deepcopy(ENTRY), Wind()
        before = copy.deepcopy([self.v.to_dict(), en, ev, vars(w)])
        r = self.run_route(ev, en, w)
        self.near(self.run_route(ev, en, w, replace(self.v, calib=1.3))["energy_wh"], r["energy_wh"] * 1.3)
        r["legs"][0]["exit_geographic"]["lat"] = 0
        r["projection"]["origin"]["lat"] = 0
        self.assertEqual([self.v.to_dict(), en, ev, vars(w)], before)

    def test_energy_only_never_land_or_authorize(self):
        r = self.run_route(start_pct=0)
        self.assertFalse(r["energy_feasible"])
        self.assertFalse(r["feasible"])
        self.assertFalse(r["landing_modeled"])
        self.assertNotIn("dist_m", r)


if __name__ == "__main__":
    if "--vectors" in sys.argv:
        print(json.dumps(vectors(), ensure_ascii=False, allow_nan=False))
    else:
        unittest.main()
