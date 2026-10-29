"""New synthetic P5 contracts. Claude owns first execution; no devices/API."""
import copy
import json
import sys
import unittest

from .energy import load_airframe
from .alerts.typed_wind import TypedWindTrendPredictor, typed_wind_trend_snapshot


def vehicle(key="fw_example"):
    return load_airframe(key)


CFG = {"min_samples": 3, "min_span_s": 2, "window_s": 10, "max_gap_s": 3, "horizon_s": 20}
FAST = {"min_samples": 2, "min_span_s": 1, "window_s": 1, "max_gap_s": 1}


def samples(values, start=0, step=1):
    return [{"t_s": start + i * step, "wind_mps": v} for i, v in enumerate(values)]


def snap(values, options=None):
    return typed_wind_trend_snapshot(vehicle(), samples(values), CFG if options is None else options)


def tick(feed, seq, speed, version="v1", time=None):
    return feed.tick(seq, {"t_s": seq if time is None else time, "wind_mps": speed}, version)


def types(result):
    return [e["type"] for e in result["events"]]


def vectors():
    snapshots = [snap([1]), snap([12]), snap([2, 2, 2]), snap([1, 2, 3]),
                 snap([3, 2, 1]), snap([2, 4, 2]),
                 snap([1, 2, 3], {**CFG, "horizon_s": 9}),
                 snap([1, 2, 3], {**CFG, "horizon_s": 8.5})]
    f = TypedWindTrendPredictor(vehicle(), FAST, 2, 2)
    stream = [tick(f, 0, 13), tick(f, 1, 13), tick(f, 2, 1), tick(f, 3, 1),
              tick(f, 4, 13), tick(f, 5, 13), tick(f, 6, 13, "v2"),
              tick(f, 7, 13, "v2"), tick(f, 8, 1, "v2", 20),
              tick(f, 9, 1, "v2", 21)]
    return {"snapshots": snapshots, "stream": stream}


class TypedWindTests(unittest.TestCase):
    def test_measured_limit_does_not_wait_for_regression(self):
        r = typed_wind_trend_snapshot(vehicle(), samples([12]))
        self.assertEqual((r["status"], r["risk"], r["lead_s"]), ("ok", True, 0))

    def test_warmup_is_unknown_not_clear(self):
        r = snap([1, 2])
        self.assertIsNone(r["risk"])
        self.assertEqual(r["reason"], "insufficient_samples")

    def test_short_span_is_unknown(self):
        r = typed_wind_trend_snapshot(vehicle(), samples([1, 2, 3], step=0.1), CFG)
        self.assertEqual(r["reason"], "insufficient_span")

    def test_independent_linear_oracle(self):
        r = snap([1, 2, 3])
        self.assertEqual((r["trend_mps_per_s"], r["r2"], r["lead_s"]), (1, 1, 9))
        self.assertTrue(r["risk"])

    def test_horizon_boundary_is_inclusive(self):
        self.assertTrue(snap([1, 2, 3], {**CFG, "horizon_s": 9})["risk"])
        self.assertFalse(snap([1, 2, 3], {**CFG, "horizon_s": 8.5})["risk"])

    def test_constant_and_falling_are_known(self):
        self.assertEqual(snap([2, 2, 2])["reason"], "constant_wind")
        self.assertFalse(snap([3, 2, 1])["risk"])

    def test_low_fit_is_unknown(self):
        r = snap([2, 4, 2])
        self.assertEqual((r["status"], r["reason"], r["r2"]), ("unknown", "trend_fit_unreliable", 0))

    def test_minimum_slope_not_qualified(self):
        self.assertEqual(snap([1, 2, 3], {**CFG, "min_slope_mps2": 1})["reason"], "trend_not_rising")

    def test_default_si_units_and_large_timestamp(self):
        a = typed_wind_trend_snapshot(vehicle(), samples([1 + i / 10 for i in range(60)]))
        b = typed_wind_trend_snapshot(vehicle(), samples([1 + i / 10 for i in range(60)], start=10**12))
        self.assertAlmostEqual(a["lead_s"], 51)
        self.assertAlmostEqual(a["trend_mps_per_s"], 0.1)
        self.assertEqual(a["lead_s"], b["lead_s"])

    def test_window_and_last_contiguous_segment(self):
        r = snap([1] * 11, {**CFG, "window_s": 4})
        self.assertEqual(r["sample_count"], 5)
        rows = [{"t_s": t, "wind_mps": 1} for t in (0, 1, 10, 11, 12)]
        r = typed_wind_trend_snapshot(vehicle(), rows, {**CFG, "window_s": 20})
        self.assertEqual((r["sample_count"], r["span_s"]), (3, 2))

    def test_snapshot_validation(self):
        for rows in ([], samples([1]) * 602, samples([1, 2], step=0), [{"t_s": 0}], samples([True]), samples([-1])):
            with self.assertRaises(ValueError):
                typed_wind_trend_snapshot(vehicle(), rows)
        for key in ("t_s", "wind_mps"):
            for value in (True, float("nan"), float("inf")):
                rec = {"t_s": 0, "wind_mps": 0, key: value}
                with self.assertRaises(ValueError):
                    typed_wind_trend_snapshot(vehicle(), [rec])

    def test_options_validation_and_profile_scope(self):
        for cfg in ({"typo": 1}, {"min_samples": True}, {"min_samples": 1}, {"min_samples": 602},
                    {"min_span_s": 181}, {"max_gap_s": 0}, {"min_r2": 1.1}, {"horizon_s": -1}):
            with self.assertRaises(ValueError):
                TypedWindTrendPredictor(vehicle(), cfg)
        with self.assertRaises(ValueError):
            TypedWindTrendPredictor(vehicle("x500"))
        self.assertTrue(typed_wind_trend_snapshot(vehicle("vtol_example"), samples([100]))["risk"])

    def test_raise_clear_hysteresis(self):
        f = TypedWindTrendPredictor(vehicle(), FAST, 2, 2)
        r = [tick(f, i, v) for i, v in enumerate((13, 13, 1, 1))]
        self.assertEqual([types(x) for x in r], [["known"], ["raise"], [], ["resolve"]])
        self.assertEqual([x["active"] for x in r], [False, True, True, False])

    def test_unknown_breaks_streak_and_never_resolves(self):
        f = TypedWindTrendPredictor(vehicle(), CFG, 1, 1)
        self.assertTrue(tick(f, 0, 13)["active"])
        r = tick(f, 1, 1)
        self.assertEqual(types(r), ["unknown"])
        self.assertIsNone(r["active"])
        self.assertTrue(tick(f, 2, 13)["active"])

    def test_version_and_gap_reset_history_and_latch(self):
        f = TypedWindTrendPredictor(vehicle(), FAST, 2, 2)
        tick(f, 0, 13)
        tick(f, 1, 13)
        r = tick(f, 2, 13, "v2")
        self.assertEqual((types(r), r["active"], r["raise_streak"]), (["reset", "known"], False, 1))
        self.assertEqual(r["reset_reason"], "mission_version_changed")
        self.assertIsNone(r["events"][0]["active"])
        self.assertEqual(r["events"][0]["evidence"], [])
        r = tick(f, 3, 1, "v2", 10)
        self.assertEqual((types(r), r["sample_count"], r["reset_reason"]), (["reset", "unknown"], 1, "telemetry_gap"))

    def test_invalid_tick_is_transactional(self):
        f = TypedWindTrendPredictor(vehicle(), FAST, 2, 2)
        tick(f, 0, 13)
        for rec, version in (({"t_s": 0, "wind_mps": 13}, "v2"), ({"t_s": 1}, "v2"),
                             ({"t_s": 1, "wind_mps": 13}, "版本")):
            with self.assertRaises(ValueError):
                f.tick(1, rec, version)
        self.assertTrue(tick(f, 1, 13)["active"])
        with self.assertRaises(ValueError):
            tick(f, 1, 13, "v2", 2)

    def test_safe_sequences_versions_and_thresholds(self):
        for seq in (True, -1, 0.5, 9007199254740992):
            with self.assertRaises(ValueError):
                tick(TypedWindTrendPredictor(vehicle()), seq, 1)
        for version in (None, "", "a" * 129, "v1\n"):
            with self.assertRaises(ValueError):
                tick(TypedWindTrendPredictor(vehicle()), 0, 1, version)
        for n in (True, 0, 0.5, 10001):
            with self.assertRaises(ValueError):
                TypedWindTrendPredictor(vehicle(), raise_ticks=n)

    def test_snapshot_ownership_and_no_authority(self):
        v, cfg = vehicle(), dict(CFG)
        f = TypedWindTrendPredictor(v, cfg, 1, 1)
        v.airframe_profile["limits"]["wind_limit_mps"] = 0
        cfg["min_samples"] = 2
        rec = {"t_s": 0, "wind_mps": 1, "battery_pct": 0}
        old = copy.deepcopy(rec)
        r = f.tick(0, rec, "v1")
        r["finding"]["value"] = "edited"
        self.assertEqual(rec, old)
        self.assertEqual(r["limit_mps"], 12)
        self.assertIsNone(tick(f, 1, 1)["active"])
        self.assertEqual(r["finding"]["candidates"], [])
        self.assertIsNone(r["finding"]["rule_choice"])
        for key in ("feasible", "executable", "sensor_validated", "direction_predicted", "probability_interval"):
            self.assertIs(r[key], False)

    def test_history_is_bounded_by_count(self):
        f = TypedWindTrendPredictor(vehicle(), {"window_s": 1000}, 1, 1)
        for i in range(605):
            r = tick(f, i, 1)
        self.assertEqual(r["sample_count"], 601)


if __name__ == "__main__":
    if sys.argv[1:] == ["--vectors"]:
        print(json.dumps(vectors(), allow_nan=False))
    else:
        unittest.main()
