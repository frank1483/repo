"""NEW synthetic caller controls. Claude owns first execution; no devices/API."""
import copy
import json
import sys
import unittest
from dataclasses import replace

from .energy import load_airframe
from .alerts.typed_capacity_feed import TypedCapacityFeed


def vehicle(name="fw_example"):
    return replace(load_airframe(name), battery_wh=100.0)


def options():
    return {"cell_r_ohm": 0.004, "cell_empty_v": 3.55, "min_samples": 3}


def sample(i, pct=90.0):
    used = 5.0*i
    return {"t_s": float(i), "battery_id": "battery:one", "used_wh": used,
            "voltage": (4.2-0.65/80.0*used-5*0.004)*4,
            "current_a": 5.0, "cell_count": 4, "battery_pct": pct}


def feed(**kwargs):
    return TypedCapacityFeed(vehicle(), options(), raise_ticks=2, clear_ticks=2, max_samples=3, **kwargs)


def run_rows(f, rows, start=0, session="session:one"):
    return [f.tick(start+i, r, session) for i, r in enumerate(rows)]


def vector_cases():
    # Stream envelopes allow invalid ticks followed by retry of the same sequence.
    def case(name, rows, airframe="fw_example"):
        return {"name": name, "airframe": airframe, "steps": [
            {"sequence": i, "rec": r, "session_id": "session:one"} for i, r in enumerate(rows)]}
    risk = [sample(i, 0 if i >= 4 else 90) for i in range(6)]
    cases = [case("raise_clear", risk)]
    unknown = [sample(i) for i in range(10)]
    for r in unknown[4:7]:
        r["voltage"] = 16.0
    cases.append(case("unknown_rearm", unknown))
    gap = [sample(i) for i in range(5)]
    gap[-1]["t_s"] = 34.0
    cases.append(case("gap", gap))
    session = case("session", [sample(i) for i in range(4)] + [sample(0)])
    session["steps"][-1].update(session_id="session:two")
    session["steps"][-1]["rec"].update(t_s=4.0, battery_id="battery:two", cell_count=5, voltage=20.0)
    cases.append(session)
    rollback = case("rollback", [sample(i) for i in range(4)])
    bad = sample(4); bad["current_a"] = -1
    rollback["steps"].extend([{"sequence": 4, "rec": bad, "session_id": "session:one"},
                               {"sequence": 4, "rec": sample(4), "session_id": "session:one"}])
    cases.extend([rollback, case("rolling", [sample(i) for i in range(12)]),
                  case("hybrid", [sample(i) for i in range(4)], "vtol_example")])
    return cases


def vectors():
    cases = []
    for c in vector_cases():
        f = TypedCapacityFeed(vehicle(c["airframe"]), options(), 2, 2, 3)
        outputs = []
        for s in c["steps"]:
            try:
                outputs.append({"output": f.tick(s["sequence"], s["rec"], s["session_id"])})
            except ValueError:
                outputs.append({"error": True})
        cases.append({**c, "outputs": outputs})
    return {"contract": "typed_capacity_feed_v1", "cases": cases}


class TestTypedCapacityFeed(unittest.TestCase):
    def test_warmup_raise_clear(self):
        out = run_rows(feed(), [sample(i, 0 if i >= 4 else 90) for i in range(6)])
        self.assertIsNone(out[0]["active"])
        self.assertIs(out[2]["active"], False)
        self.assertIs(out[3]["active"], True)
        self.assertEqual([e["type"] for e in out[3]["events"]], ["raise"])
        self.assertIs(out[4]["active"], True)
        self.assertEqual(out[4]["finding"]["value"], "conditional_capacity_risk_latched_pending_clear")
        self.assertIs(out[5]["active"], False)
        self.assertEqual([e["type"] for e in out[5]["events"]], ["resolve"])

    def test_unknown_breaks_without_resolve_and_rearms(self):
        f = feed(); run_rows(f, [sample(i) for i in range(4)])
        rows = [sample(i) for i in range(4, 7)]
        for r in rows: r["voltage"] = 16.0
        out = run_rows(f, rows, 4)
        self.assertIsNone(out[-1]["active"])
        self.assertEqual(out[-1]["snapshot"]["reason"], "degenerate_fit")
        self.assertNotIn("resolve", [e["type"] for o in out for e in o["events"]])
        recovery = run_rows(f, [sample(i) for i in range(7, 11)], 7)
        risk_recovery = [o for o in recovery if o["status"] == "ok" and o["risk"]]
        self.assertIs(risk_recovery[0]["active"], False)
        self.assertEqual(risk_recovery[0]["raise_streak"], 1)
        self.assertIs(risk_recovery[-1]["active"], True)

    def test_gap_discards_history_and_latch(self):
        f = feed(); run_rows(f, [sample(i) for i in range(4)])
        r = sample(4); r["t_s"] = 34.0
        o = f.tick(4, r, "session:one")
        self.assertEqual(o["reset_reasons"], ["telemetry_gap"])
        self.assertEqual(o["window_sample_count"], 1)
        self.assertIsNone(o["active"])
        self.assertEqual([e["type"] for e in o["events"]], ["reset", "unknown"])

    def test_gap_equality_does_not_reset(self):
        f = feed(); run_rows(f, [sample(i) for i in range(4)])
        r = sample(4); r["t_s"] = 33.0
        o = f.tick(4, r, "session:one")
        self.assertEqual(o["reset_reasons"], [])
        self.assertIs(o["active"], True)

    def test_explicit_new_session_same_or_new_battery(self):
        for changed_battery in (False, True):
            f = feed(); run_rows(f, [sample(i) for i in range(4)])
            r = sample(0); r["t_s"] = 4.0
            if changed_battery: r.update(battery_id="battery:two", cell_count=5, voltage=20.0)
            o = f.tick(4, r, "session:two")
            self.assertEqual(o["reset_reasons"], ["session_changed"])
            self.assertEqual(o["window_sample_count"], 1)
            self.assertIsNone(o["active"])

    def test_identity_cell_counter_reject_is_atomic(self):
        for key, value in (("battery_id", "battery:two"), ("cell_count", 5), ("used_wh", 0.0)):
            f = feed(); run_rows(f, [sample(i) for i in range(4)])
            r = sample(4); r[key] = value
            with self.assertRaises(ValueError): f.tick(4, r, "session:one")
            self.assertIs(f.tick(4, sample(4), "session:one")["active"], True)

    def test_bad_sample_reject_is_atomic(self):
        for key, value in (("current_a", -1), ("t_s", 3.0), ("battery_pct", True), ("voltage", float("nan")), ("extra", 1)):
            f = feed(); run_rows(f, [sample(i) for i in range(4)])
            r = sample(4); r[key] = value
            with self.assertRaises(ValueError): f.tick(4, r, "session:one")
            self.assertEqual(f.tick(4, sample(4), "session:one")["raise_streak"], 2)

    def test_sequence_session_and_clock_validation(self):
        f = feed(); f.tick(0, sample(0), "session:one")
        for seq, session in ((0, "session:one"), (True, "session:one"), (1, "bad id"), (1, "session:one\n")):
            with self.assertRaises(ValueError): f.tick(seq, sample(1), session)
        with self.assertRaises(ValueError): f.tick(1, sample(0), "session:two")
        self.assertEqual(f.tick(1, sample(1), "session:one")["window_sample_count"], 2)

    def test_rolling_bound_and_counter_origin(self):
        f = feed(); rows = [sample(i) for i in range(12)]
        for r in rows: r["used_wh"] += 10
        out = run_rows(f, rows)
        self.assertTrue(all(o["window_sample_count"] <= 3 for o in out))
        self.assertAlmostEqual(out[-1]["snapshot"]["estimated_total_wh"], 90)
        self.assertAlmostEqual(out[-1]["snapshot"]["estimated_remaining_wh"], 25)

    def test_copy_isolation_and_flags(self):
        v, cfg, r = vehicle(), options(), sample(0)
        f = TypedCapacityFeed(v, cfg, 2, 2, 3)
        before = copy.deepcopy(r); out = f.tick(0, r, "session:one")
        self.assertEqual(r, before)
        cfg["min_samples"] = 601; r["battery_id"] = "changed"
        v.battery_wh = 1; out["snapshot"]["assumptions"]["min_samples"] = 601
        known = run_rows(f, [sample(1), sample(2)], 1)[-1]
        self.assertEqual(known["snapshot"]["nominal_wh"], 100)
        self.assertEqual(known["snapshot"]["assumptions"]["min_samples"], 3)
        for k in ("measured_capacity", "sensor_validated", "telemetry_freshness_verified", "independent_window_evidence", "energy_correction_applied", "landing_modeled", "feasible", "executable"):
            self.assertIs(known[k], False)
        self.assertEqual(known["candidates"], []); self.assertIsNone(known["rule_choice"])

    def test_options_bounds_and_profiles(self):
        for cfg in ({}, {**options(), "extra": 1}, {**options(), "min_samples": True}, {**options(), "max_gap_s": 0}):
            with self.assertRaises(ValueError): TypedCapacityFeed(vehicle(), cfg)
        for args in ((True, 2, 3), (2, 0, 3), (2, 2, 2), (2, 2, 602)):
            with self.assertRaises(ValueError): TypedCapacityFeed(vehicle(), options(), *args)
        with self.assertRaises(ValueError): TypedCapacityFeed(vehicle("x500"), options())
        self.assertEqual(TypedCapacityFeed(vehicle("vtol_example"), options()).tick(0, sample(0), "session:one")["status"], "unknown")

    def test_combined_reset_reasons(self):
        f = feed(); run_rows(f, [sample(i) for i in range(4)])
        r = sample(0); r["t_s"] = 34.0
        o = f.tick(4, r, "session:two")
        self.assertEqual(o["reset_reasons"], ["session_changed", "telemetry_gap"])
        self.assertEqual([e["type"] for e in o["events"]], ["reset", "unknown"])


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False))
    else:
        unittest.main()
