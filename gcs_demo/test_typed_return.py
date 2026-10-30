"""NEW P2 engineering controls; Claude owns first Python/parity execution."""
import copy
import json
import math
import sys
import unittest
from dataclasses import replace

from .energy import Wind, load_airframe
from .alerts.typed_return import typed_return_probe_snapshot

ENTRY = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "air_heading_deg": 0.0}
TARGET = {"lat": 23.0, "lon": 120.0, "alt": 80.0, "tolerance_m": 0.001}


def vehicle(name="fw_example"):
    v = load_airframe(name)
    p = copy.deepcopy(v.airframe_profile)
    p["uncertainty"] = {"power_pct": 0, "capacity_pct": 0, "wind_mps": 0}
    return replace(v, airframe_profile=p)


def arc():
    return {"kind": "arc", "v_air": 16.0, "angle_deg": 180.0,
            "clockwise": True, "radius_m": 40.0}


def probe(key="A", n=1, ret=None):
    return {"id": key, "outbound_events": [arc() for _ in range(n)],
            "return_events": [arc() for _ in range(n if ret is None else ret)]}


def snap(items=None, v=None, pct=100, wind=None, target=None, entry=None, mode=None):
    return typed_return_probe_snapshot(vehicle() if v is None else v,
                                       ENTRY if entry is None else entry,
                                       TARGET if target is None else target,
                                       [probe()] if items is None else items,
                                       Wind(0, 0) if wind is None else wind, pct, mode)


def summary(result):
    r = copy.deepcopy(result)
    for p in r["probes"]:
        del p["bounds"]
        for s in p["scenarios"]:
            s.pop("reason", None)  # Upstream error prose is not a parity contract.
    return r


def vectors():
    one = snap()
    two = snap([probe("A"), probe("B", 2)])
    used1 = 100 - one["probes"][0]["low_pct"]
    used2 = 100 - two["probes"][1]["low_pct"]
    middle = vehicle().reserve_pct + (used1 + used2) / 2
    s = one["probes"][0]["bounds"]["scenarios"][0]
    exact_used = s["energy_wh"] / s["capacity_wh"] * 100
    return [summary(r) for r in [one, two,
            snap([probe("A"), probe("B", 2)], pct=middle),
            snap(v=replace(vehicle(), reserve_pct=0), pct=exact_used), snap(pct=0),
            snap(wind=Wind(1, 270)),
            snap(v=load_airframe("fw_example"), target={**TARGET, "tolerance_m": 100}),
            snap(v=vehicle("vtol_example"), mode="fw"),
            snap(entry={**ENTRY, "lon": 179.9999}, target={**TARGET, "lon": -179.9999, "tolerance_m": 100})]]


class TestTypedReturn(unittest.TestCase):
    def test_full_circle_and_probe_time(self):
        r = snap()
        self.assertEqual(r["status"], "ok")
        self.assertFalse(r["sampled_energy_risk"])
        s = r["probes"][0]["scenarios"][0]
        self.assertAlmostEqual(s["eta_s"], math.pi * 40 / 16)
        self.assertAlmostEqual(s["exit_geographic"]["lat"], ENTRY["lat"])
        self.assertAlmostEqual(s["exit_geographic"]["lon"], ENTRY["lon"])
        self.assertTrue(s["endpoint_supported"])

    def test_first_sampled_crossing_and_last_prefix(self):
        r = vectors()[2]
        self.assertTrue(r["sampled_energy_risk"])
        self.assertEqual(r["first_sampled_infeasible_id"], "B")
        self.assertEqual(r["last_sampled_feasible_prefix_id"], "A")
        self.assertAlmostEqual(r["first_sampled_infeasible_nominal_eta_s"], 2 * math.pi * 40 / 16)

    def test_reserve_equality_supported(self):
        r = vectors()[3]
        self.assertFalse(r["sampled_energy_risk"])
        self.assertEqual(r["last_sampled_feasible_prefix_id"], "A")

    def test_first_probe_risky_no_safe_prefix(self):
        r = snap(pct=0)
        self.assertTrue(r["sampled_energy_risk"])
        self.assertEqual(r["first_sampled_infeasible_id"], "A")
        self.assertIsNone(r["last_sampled_feasible_prefix_id"])
        self.assertLess(r["probes"][0]["low_pct"], 0)

    def test_wind_drift_invalidates_endpoint(self):
        r = snap(wind=Wind(1, 270))
        self.assertEqual(r["status"], "unknown")
        self.assertTrue(r["probes"][0]["bounds"]["available"])
        self.assertFalse(r["probes"][0]["scenarios"][0]["endpoint_supported"])
        self.assertIsNone(r["sampled_energy_risk"])

    def test_all_scenarios_must_reach_target(self):
        r = snap(v=load_airframe("fw_example"))
        self.assertTrue(r["probes"][0]["scenarios"][0]["endpoint_supported"])
        self.assertTrue(any(not s["endpoint_supported"] for s in r["probes"][0]["scenarios"]))
        self.assertEqual(r["status"], "unknown")

    def test_endpoint_tolerance_explicit(self):
        r = snap(wind=Wind(1, 270), target={**TARGET, "tolerance_m": 20})
        self.assertEqual(r["status"], "ok")
        self.assertGreater(r["probes"][0]["scenarios"][0]["endpoint_error_m"], 10)

    def test_unsupported_geometry_poison_aggregate(self):
        bad = probe("B", 2)
        bad["return_events"] = [{"kind": "landing"}]
        r = snap([probe(), bad])
        self.assertEqual(r["probes"][0]["status"], "ok")
        self.assertEqual(r["probes"][1]["status"], "unknown")
        for key in ("sampled_energy_risk", "first_sampled_infeasible_id", "last_sampled_feasible_prefix_id"):
            self.assertIsNone(r[key])

    def test_reentry_not_last_safe_boundary(self):
        items = [probe("A", 1, 7), probe("B", 2, 2)]
        full = snap(items)
        a, b = (100 - r["low_pct"] for r in full["probes"])
        r = snap(items, pct=vehicle().reserve_pct + (a + b) / 2)
        self.assertTrue(r["sampled_feasibility_reentry"])
        self.assertEqual(r["first_sampled_infeasible_id"], "A")
        self.assertIsNone(r["last_sampled_feasible_prefix_id"])

    def test_prefix_order_not_just_increasing_length(self):
        for items in ([probe("A", 2), probe("B", 1)], [probe("A"), probe("B")]):
            with self.assertRaises(ValueError):
                snap(items)
        bad = probe("B", 2)
        bad["outbound_events"][0]["radius_m"] = 41
        with self.assertRaises(ValueError):
            snap([probe(), bad])

    def test_prefix_object_field_order_irrelevant(self):
        b = probe("B", 2)
        b["outbound_events"][0] = dict(reversed(list(arc().items())))
        self.assertEqual(snap([probe(), b])["status"], "ok")

    def test_batch_schema(self):
        for items in ([], [probe()] * 17, [probe(), probe()], [{**probe(), "action": "RTL"}],
                      [{**probe(), "return_events": []}], [{**probe(), "outbound_events": [0]}]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                snap(items)

    def test_total_event_budget(self):
        with self.assertRaises(ValueError):
            snap([probe(n=501)])

    def test_target_and_entry_schema(self):
        for t in ({k: v for k, v in TARGET.items() if k != "tolerance_m"},
                  {**TARGET, "tolerance_m": -1}, {**TARGET, "tolerance_m": 101},
                  {**TARGET, "tolerance_m": True}, {**TARGET, "alt": 0}):
            with self.assertRaises(ValueError):
                snap(target=t)
        with self.assertRaises(ValueError):
            snap(entry={**ENTRY, "lat": 76})

    def test_profile_and_hybrid_mode(self):
        self.assertEqual(snap(v=vehicle("vtol_example"), mode="fw")["status"], "ok")
        for v, mode in ((vehicle("vtol_example"), None), (vehicle("vtol_example"), "mc"),
                        (load_airframe("x500"), None), (replace(vehicle(), airframe_profile=None), None)):
            with self.assertRaises(ValueError):
                snap(v=v, mode=mode)

    def test_finite_json_and_numeric_inputs(self):
        for pct in (True, -1, 101, float("nan")):
            with self.assertRaises(ValueError):
                snap(pct=pct)
        p = probe()
        p["return_events"][0]["radius_m"] = float("inf")
        with self.assertRaises(ValueError):
            snap([p])

    def test_no_alias_or_mutation(self):
        p, e, t = [probe()], copy.deepcopy(ENTRY), copy.deepcopy(TARGET)
        before = copy.deepcopy((p, e, t))
        r = snap(p, entry=e, target=t)
        self.assertEqual((p, e, t), before)
        r["probes"][0]["scenarios"][0]["exit_geographic"]["lat"] = 0
        self.assertEqual(p, before[0])
        self.assertEqual(snap()["status"], "ok")

    def test_no_execution_or_continuous_boundary_claim(self):
        r = snap()
        for k in ("continuous_boundary_known", "return_inferred", "recovery_reference_verified",
                  "landing_modeled", "wind_direction_varied", "feasible", "executable"):
            self.assertIs(r[k], False)
        self.assertEqual(r["candidates"], [])
        self.assertIsNone(r["rule_choice"])

    def test_dateline_wrap(self):
        r = vectors()[8]
        self.assertEqual(r["status"], "ok")
        self.assertLess(r["probes"][0]["scenarios"][0]["endpoint_error_m"], 30)


if __name__ == "__main__":
    if "--vectors" in sys.argv:
        print(json.dumps(vectors(), allow_nan=False, sort_keys=True))
    else:
        unittest.main()
