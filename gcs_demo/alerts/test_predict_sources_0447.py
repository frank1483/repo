"""NEW source-isolation controls; drafted, not executed by Codex."""
import unittest
from dataclasses import replace
from unittest.mock import patch
from .energy_api import Wind, default_vehicle
from .predict import PredictiveAlertEngine, Telemetry, Finding


def engine():
    return PredictiveAlertEngine([(200., 0., 50.)], (0., 0., 0.), default_vehicle())


def telemetry(t=0):
    return Telemetry(t, (0., 0., 50.), (10., 0., 0.), 80., 23., 10., 1., 6, 0, 90., Wind(2., 90.))


def feed(eng, missing=(), t=1):
    sources = eng.new_source_inputs()
    tm = telemetry(t)
    values = {"position": tm.pos, "velocity": tm.vel, "next_wp": tm.next_wp,
              "fc_pct": tm.soc_pct, "voltage": tm.voltage, "current": tm.current_a,
              "used_wh": tm.used_wh, "cell_count": tm.cell_count,
              "link": tm.link_pct, "wind": tm.wind}
    for name, value in values.items():
        if name not in missing:
            sources.put(name, value, t, t)
    return sources


class PredictorSourcesTests(unittest.TestCase):
    def test_missing_link_only_blocks_link_predictor(self):
        eng = engine()
        eng.update_sources(feed(eng, ("link",)), 1)
        rows = eng.last_state["predictor_readiness"]
        self.assertEqual(rows["link_route"]["unknown_sources"], ["link"])
        self.assertTrue(all(rows[k]["status"] == "ready" for k in rows if k != "link_route"))
        self.assertEqual((len(eng._wind_hist), len(eng._cell_hist)), (1, 1))

    def test_missing_position_preserves_capacity_and_wind(self):
        eng = engine()
        eng.update_sources(feed(eng, ("position",)), 1)
        rows = eng.last_state["predictor_readiness"]
        for key in ("battery_route", "rtl_point", "link_route"):
            self.assertEqual(rows[key]["status"], "unknown")
        for key in ("battery_capacity", "wind_trend"):
            self.assertEqual(rows[key]["status"], "ready")

    def test_invalid_current_preserves_link_and_wind(self):
        eng = engine()
        sources = feed(eng)
        sources.put("current", None, 2, 2, valid=False, invalid_reason="missing_current")
        eng.update_sources(sources, 2)
        self.assertEqual(eng.last_state["source_status"]["current"]["reason"], "missing_current")
        self.assertEqual(eng.last_state["predictor_readiness"]["link_route"]["status"], "ready")
        self.assertEqual(eng.last_state["predictor_readiness"]["battery_capacity"]["status"], "unknown")
        self.assertEqual(len(eng._cell_hist), 0)

    def test_invalid_snapshot_field_does_not_block_wind(self):
        eng = engine()
        eng.update(replace(telemetry(), voltage=float("nan"), wind=Wind(15, 0)))
        self.assertEqual(eng.last_state["source_status"]["voltage"]["status"], "unknown")
        self.assertIn("wind_trend", eng.active())
        self.assertEqual(eng.last_state["data_status"], "partial")

    def test_recent_receive_does_not_hide_expired_sensing(self):
        eng = engine()
        sources = feed(eng, ("link",), t=10)
        sources.put("link", 80, 1, 10)
        eng.update_sources(sources, 10)
        row = eng.last_state["source_status"]["link"]
        self.assertEqual((row["reason"], row["sensed_age_s"], row["recv_age_s"]), ("expired", 9, 0))
        self.assertEqual(eng.last_state["predictor_readiness"]["wind_trend"]["status"], "ready")

    def test_per_source_ttl_boundary_and_expiry(self):
        eng = engine()
        sources = feed(eng)
        eng.update_sources(sources, 4)
        self.assertEqual(eng.last_state["predictor_readiness"]["battery_capacity"]["status"], "ready")
        eng.update_sources(sources, 4.001)
        self.assertEqual(eng.last_state["predictor_readiness"]["battery_capacity"]["status"], "unknown")
        self.assertEqual(eng.last_state["predictor_readiness"]["wind_trend"]["status"], "ready")
        self.assertEqual(len(eng._cell_hist), 0)

    def test_unknown_wind_retains_existing_alert(self):
        eng = engine()
        eng.update(replace(telemetry(), wind=Wind(15, 0)))
        eng.update_sources(feed(eng, ("wind",)), 1)
        self.assertIn("wind_trend", eng.active())
        self.assertTrue(eng.active()["wind_trend"].prediction_expired)
        self.assertEqual(len(eng._wind_hist), 0)

    def test_no_wind_energy_label_and_no_flight_qualification(self):
        eng = engine()
        findings = [Finding("battery_route", True, candidates=[
            {"id": "C1", "action": "A_RTL_NOW", "feasible": True,
             "energy_feasible": True, "end_pct_raw": 50, "end_pct": 50}])]
        with patch.object(eng, "_battery_route", return_value=findings):
            eng.update_sources(feed(eng, ("wind",)), 1)
        self.assertFalse(eng.last_state["wind_included"])
        self.assertIsNotNone(eng.last_state["avail_wh"])
        self.assertIn("未含風", findings[0].value)
        self.assertFalse(findings[0].candidates[0]["feasible"])
        self.assertIsNone(findings[0].candidates[0]["energy_feasible"])

    def test_missing_velocity_only_blocks_calibration(self):
        eng = engine()
        with patch.object(eng, "_update_calib") as calibrate:
            eng.update_sources(feed(eng, ("velocity",)), 1)
        calibrate.assert_not_called()
        self.assertTrue(all(r["status"] == "ready" for r in eng.last_state["predictor_readiness"].values()))

    def test_external_cursor_rejects_before_mutation(self):
        eng = engine()
        sources = feed(eng, ("next_wp",))
        sources.put("next_wp", 99, 1, 1)
        with self.assertRaises(ValueError):
            eng.update_sources(sources, 1)
        self.assertIsNone(eng._last_tm_t)
        self.assertEqual(eng.last_state, {})

    def test_external_integral_float_cursor_normalizes(self):
        eng = engine()
        sources = feed(eng, ("next_wp",))
        sources.put("next_wp", 0.0, 1, 1)
        eng.update_sources(sources, 1)
        self.assertEqual(eng.last_state["predictor_errors"], {})

    def test_external_values_used_directly(self):
        eng = engine()
        sources = feed(eng, ("wind",))
        sources.put("wind", Wind(15, 0), 1, 1)
        eng.update_sources(sources, 1)
        self.assertIn("wind_trend", eng.active())
        self.assertEqual(eng.last_state["source_status"]["wind"]["sensed_t"], 1)

    def test_duplicate_engine_time_does_not_add_history(self):
        eng = engine()
        sources = feed(eng)
        eng.update_sources(sources, 1)
        before = (list(eng._wind_hist), list(eng._cell_hist), list(eng._link_hist))
        self.assertEqual(eng.update_sources(sources, 1), [])
        self.assertEqual(before, (list(eng._wind_hist), list(eng._cell_hist), list(eng._link_hist)))

    def test_polling_without_new_samples_cannot_manufacture_samples(self):
        eng = engine()
        sources = feed(eng)
        eng.update_sources(sources, 1)
        before = (list(eng._wind_hist), list(eng._cell_hist), list(eng._link_hist))
        metrics = {k: eng.last_state[k] for k in ("end_pct", "pnr_wp", "rem_s")}
        eng.update_sources(sources, 1.5)
        eng.update_sources(sources, 2)
        self.assertEqual(before, (list(eng._wind_hist), list(eng._cell_hist), list(eng._link_hist)))
        self.assertEqual(metrics, {k: eng.last_state[k] for k in metrics})


if __name__ == "__main__":
    unittest.main()
