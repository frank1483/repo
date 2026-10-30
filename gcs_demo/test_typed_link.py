"""NEW first-execution contracts. No old suites are invoked."""
import json
import sys
import unittest
from .energy import load_airframe
from .alerts.typed_link import typed_link_distance_snapshot, TypedLinkDistancePredictor

CFG = dict(min_samples=3, min_distance_span_m=100, window_s=10, max_gap_s=5,
           horizon_s=30, max_extrapolation_m=250)
FAST = dict(min_samples=2, min_distance_span_m=1, window_s=1, max_gap_s=1)


def vehicle(key="fw_example"):
    return load_airframe(key)


def samples(qualities=(80, 70, 60), distances=(0, 100, 200), times=(0, 1, 2)):
    return [dict(t_s=t, distance_m=d, link_pct=q) for t, d, q in zip(times, distances, qualities)]


def probes(distance=450, eta=10):
    return [dict(id="A", distance_m=distance, eta_s=eta)]


def snap(rows=None, targets=None, cfg=None):
    return typed_link_distance_snapshot(vehicle(), "home.v1", samples() if rows is None else rows,
                                        probes() if targets is None else targets, CFG if cfg is None else cfg)


def tick(f, i, q, distance=None, version="v1", time=None, targets=None):
    return f.tick(i, dict(t_s=i if time is None else time, distance_m=(i % 2) * 100 if distance is None else distance,
                         link_pct=q), probes(100) if targets is None else targets, version)


def types(r):
    return [e["type"] for e in r["events"]]


def vectors():
    snapshots = [snap(), snap(cfg={**CFG, "max_extrapolation_m": 249}),
                 snap(targets=probes(200)), snap(targets=probes(450, 31)),
                 snap(rows=samples((80, 80, 80))), snap(rows=samples((60, 70, 80))),
                 snap(rows=samples((80, 70, 80))),
                 snap(rows=samples((35,), (0,), (0,))),
                 snap(rows=samples((80,), (0,), (0,)))]
    f = TypedLinkDistancePredictor(vehicle(), "home.v1", FAST, 2, 2)
    stream = [tick(f, 0, 30), tick(f, 1, 30), tick(f, 2, 80), tick(f, 3, 80),
              tick(f, 4, 80), tick(f, 5, 30, version="v2"), tick(f, 6, 30, version="v2"),
              tick(f, 7, 80, version="v2", time=20), tick(f, 8, 80, version="v2", time=21)]
    return dict(snapshots=snapshots, stream=stream)


class TypedLinkTests(unittest.TestCase):
    def test_hand_calculated_distance_fit_and_limit_equality(self):
        r = snap()
        self.assertEqual((r["status"], r["risk"], r["first_probe_id"], r["lead_s"]), ("ok", True, "A", 10))
        self.assertAlmostEqual(r["slope_pct_per_m"], -0.1)
        self.assertEqual(r["r2"], 1)
        self.assertEqual(r["probes"][0]["predicted_link_pct"], 35)

    def test_immediate_observed_limit_without_fit(self):
        r = snap(rows=samples((35,), (0,), (0,)))
        self.assertEqual((r["risk"], r["lead_s"], r["reason"]), (True, 0, "observed_limit_reached"))

    def test_warmup_and_stationary_distance_unknown(self):
        self.assertIsNone(snap(rows=samples((80,), (0,), (0,)))["risk"])
        self.assertEqual(snap(rows=samples(distances=(100, 100, 100)))["reason"], "insufficient_distance_span")

    def test_flat_fit_known_only_with_distance_span(self):
        r = snap(rows=samples((80, 80, 80)))
        self.assertEqual((r["status"], r["risk"], r["slope_pct_per_m"]), ("ok", False, 0))

    def test_positive_and_low_quality_fit_unknown(self):
        self.assertEqual(snap(rows=samples((60, 70, 80)))["reason"], "distance_fit_increasing")
        self.assertEqual(snap(rows=samples((80, 70, 80)))["reason"], "distance_fit_unreliable")

    def test_default_disallows_extrapolation(self):
        r = snap(cfg={**CFG, "max_extrapolation_m": 0})
        self.assertIsNone(r["risk"])
        self.assertEqual(r["probes"][0]["reason"], "outside_distance_envelope")

    def test_extrapolation_boundary_and_unclipped_raw_fit(self):
        self.assertTrue(snap()["risk"])
        self.assertIsNone(snap(cfg={**CFG, "max_extrapolation_m": 249})["risk"])
        r = snap(targets=probes(1000), cfg={**CFG, "max_extrapolation_m": 800})
        self.assertEqual(r["probes"][0]["predicted_link_pct"], -20)

    def test_horizon_boundary_and_any_unsupported_probe_unknown(self):
        self.assertTrue(snap(targets=probes(450, 30))["risk"])
        self.assertIsNone(snap(targets=probes(450, 31))["risk"])
        r = snap(targets=[dict(id="A", distance_m=450, eta_s=10), dict(id="B", distance_m=451, eta_s=11)])
        self.assertIsNone(r["risk"])
        self.assertIsNone(r["first_probe_id"])

    def test_first_input_probe_is_first_time_crossing(self):
        targets = [dict(id="B", distance_m=200, eta_s=1), dict(id="C", distance_m=450, eta_s=2)]
        self.assertEqual((snap(targets=targets)["first_probe_id"], snap(targets=targets)["lead_s"]), ("C", 2))

    def test_window_and_contiguous_suffix(self):
        rows = samples((80, 70, 60), (0, 100, 200), (0, 8, 9))
        self.assertEqual(snap(rows=rows)["sample_count"], 2)
        self.assertEqual(snap(cfg={**CFG, "window_s": 1, "max_gap_s": 1})["sample_count"], 2)

    def test_schema_numeric_order_and_bounded_history(self):
        for rows in ([], [dict(t_s=0)], samples(times=(0, 0, 1)), samples(qualities=(80, True, 60)),
                     samples(distances=(0, -1, 200)), samples(distances=(0, 10001, 200)),
                     [dict(t_s=i, distance_m=0, link_pct=80) for i in range(602)]):
            with self.assertRaises(ValueError):
                snap(rows=rows)
        for key in ("t_s", "distance_m", "link_pct"):
            for val in (True, float("nan"), float("inf")):
                with self.assertRaises(ValueError):
                    snap(rows=[{**samples()[0], key: val}])

    def test_probe_schema_and_order_are_not_inferred(self):
        for targets in ([], probes() * 2, probes() * 1001, [dict(id="X", distance_m=0)],
                        [{**probes()[0], "action": "RTL"}], probes(-1), probes(0, -1),
                        [dict(id="X", distance_m=0, eta_s=2), dict(id="Y", distance_m=0, eta_s=1)]):
            with self.assertRaises(ValueError):
                snap(targets=targets)

    def test_policy_profile_and_identity_validation(self):
        for cfg in (dict(typo=1), dict(min_samples=True), dict(min_samples=1), dict(max_gap_s=181),
                    dict(min_distance_span_m=0), dict(min_r2=2), dict(link_min_pct=101), dict(max_extrapolation_m=-1)):
            with self.assertRaises(ValueError):
                snap(cfg=cfg)
        with self.assertRaises(ValueError):
            typed_link_distance_snapshot(vehicle("x500"), "home", samples(), probes(), CFG)
        for identity in ("", "a\n", "非ASCII", "a" * 129):
            with self.assertRaises(ValueError):
                TypedLinkDistancePredictor(vehicle(), identity)

    def test_raise_then_debounced_resolve(self):
        f = TypedLinkDistancePredictor(vehicle(), "home", FAST, 2, 2)
        self.assertEqual(types(tick(f, 0, 30)), ["known"])
        self.assertEqual(types(tick(f, 1, 30)), ["raise"])
        tick(f, 2, 80)
        self.assertTrue(tick(f, 3, 80)["active"])
        self.assertEqual(types(tick(f, 4, 80)), ["resolve"])

    def test_unknown_breaks_latch_without_resolve(self):
        f = TypedLinkDistancePredictor(vehicle(), "home", FAST, 1, 1)
        tick(f, 0, 30, distance=100)
        r = tick(f, 1, 80, distance=100)
        self.assertEqual(types(r), ["unknown"])
        self.assertIsNone(r["active"])
        self.assertEqual(types(tick(f, 2, 80, distance=0)), ["known"])

    def test_version_and_gap_reset_are_neutral(self):
        f = TypedLinkDistancePredictor(vehicle(), "home", FAST, 1, 1)
        tick(f, 0, 30)
        for r in (tick(f, 1, 80, version="v2"), tick(f, 2, 80, version="v2", time=10)):
            self.assertEqual(types(r), ["reset", "unknown"])
            self.assertIsNone(r["events"][0]["active"])
            self.assertEqual(r["events"][0]["evidence"], [])
            self.assertEqual(r["sample_count"], 1)

    def test_invalid_tick_is_transactional(self):
        f = TypedLinkDistancePredictor(vehicle(), "home", FAST, 1, 1)
        tick(f, 0, 30)
        for args in ((1, 80, "bad version", 1, []), (0, 30, "v1", 1, probes()),
                     (1, 80, "v1", 0, probes()), (1, 80, "v2", 1, [])):
            i, q, version, time, targets = args
            with self.assertRaises(ValueError):
                tick(f, i, q, version=version, time=time, targets=targets)
        self.assertEqual(types(tick(f, 1, 30)), [])

    def test_outputs_are_detached_and_have_no_action_authority(self):
        f = TypedLinkDistancePredictor(vehicle(), "home", FAST, 1, 1)
        r = tick(f, 0, 30)
        r["finding"]["active"] = False
        self.assertTrue(tick(f, 1, 30)["active"])
        for r in (r, snap()):
            for key in ("executable", "feasible", "geometry_evaluated", "eta_verified", "distance_reference_verified"):
                self.assertFalse(r[key])
        self.assertEqual(r.get("finding", {}).get("candidates", []), [])

    def test_inputs_and_constructor_policy_are_detached(self):
        v, cfg = vehicle(), {**CFG}
        f = TypedLinkDistancePredictor(v, "home", cfg, 1, 1)
        cfg["link_min_pct"] = 0
        rec = dict(t_s=0, distance_m=0, link_pct=35)
        targets = probes(0)
        before = json.dumps([rec, targets])
        r = f.tick(0, rec, targets, "v1")
        self.assertTrue(r["risk"])
        self.assertEqual(json.dumps([rec, targets]), before)

    def test_sequence_version_and_streak_types(self):
        for value in (True, -1, 0.5, 9007199254740992):
            with self.assertRaises(ValueError):
                tick(TypedLinkDistancePredictor(vehicle(), "home"), value, 80)
        for value in (True, 0, 0.5, 10001):
            with self.assertRaises(ValueError):
                TypedLinkDistancePredictor(vehicle(), "home", raise_ticks=value)
        for version in (None, "", "v1\n"):
            with self.assertRaises(ValueError):
                tick(TypedLinkDistancePredictor(vehicle(), "home"), 0, 80, version=version)

    def test_bounded_feed_history(self):
        f = TypedLinkDistancePredictor(vehicle(), "home", {"window_s": 1000}, 1, 1)
        for i in range(605):
            r = tick(f, i, 80)
        self.assertEqual(r["sample_count"], 601)

    def test_hybrid_profile_has_same_measured_link_semantics(self):
        r = typed_link_distance_snapshot(vehicle("vtol_example"), "home", samples(), probes(), CFG)
        self.assertEqual(r, snap().copy() | {"reference_id": "home"})


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False))
    else:
        unittest.main()
