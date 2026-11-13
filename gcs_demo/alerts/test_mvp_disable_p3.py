"""0458 first-run controls for Claude; no explanations, backend or devices.

Run on the patched 8752fba tree:
    python -m unittest gcs_demo.alerts.test_mvp_disable_p3 -v
"""
import math
import unittest
from unittest.mock import patch

from gcs_demo.alert_bridge import AlertFeed
from . import energy_api, sim


class _SimulationFeed:
    """Drive the real AlertFeed.tick with the demo's geographic telemetry.

    The simulation still owns flight dynamics. AlertFeed still synthesizes
    its own voltage/current; this adapter does not bypass that MVP path.
    """

    def __init__(self, route, home, vehicle, config, *, capacity_check=True):
        del capacity_check  # Adapter exercises AlertFeed's own MVP policy.
        del config  # AlertFeed owns its MVP config, including cell_empty_v=3.5.
        self.home = {"lat": energy_api.REF_LAT, "lon": energy_api.REF_LON}
        self.m_per_deg = math.pi * 6371000.0 / 180.0
        self.lon_scale = self.m_per_deg * math.cos(math.radians(self.home["lat"]))
        path = [self.home] + [self._point(p) for p in route] + [self.home]
        self.feed = AlertFeed(self.home, path, vehicle, explain_fn=None)
        self.events = []
        self.member_samples = []

    def _point(self, pos):
        return {"lat": self.home["lat"] + pos[1] / self.m_per_deg,
                "lon": self.home["lon"] + pos[0] / self.lon_scale, "alt": pos[2]}

    def update(self, tm):
        # Reconstruct the demo's pre-sag electrical power. Its noisy loaded
        # voltage is not fed into the bridge's synthetic-voltage estimator.
        power = tm.current_a * (tm.voltage + tm.current_a * 0.004 * tm.cell_count)
        rec = {**self._point(tm.pos), "t_s": tm.t, "battery_pct": tm.soc_pct,
               "power_w": power, "used_wh": tm.used_wh,
               "vel_e": tm.vel[0], "vel_n": tm.vel[1],
               "wind_mps": tm.wind.speed_mps, "wind_from": tm.wind.from_deg}
        rows = self.feed.tick(rec, tm.next_wp)
        self.events.extend(rows)
        self.member_samples.append(dict(self.feed.engine.last_state["battery_members"]))
        return rows

    @property
    def last_state(self):
        return self.feed.engine.last_state

    def active(self):
        return self.feed.engine.active()


def _mvp_run(scenario):
    feeds = []

    def factory(*args, **kwargs):
        adapter = _SimulationFeed(*args, **kwargs)
        feeds.append(adapter)
        return adapter

    # AlertFeed writes these globals. Restore them even if a first run fails.
    with patch.object(energy_api, "REF_LAT", energy_api.REF_LAT), \
         patch.object(energy_api, "REF_LON", energy_api.REF_LON), \
         patch.object(sim, "PredictiveAlertEngine", side_effect=factory):
        result = sim.run(scenario=scenario, policy="ignore", explain_fn=None)
    return result, feeds[0]


class MvpDisableP3Tests(unittest.TestCase):
    def assert_p3_disabled(self, adapter):
        self.assertFalse(adapter.feed.engine.capacity_check)
        self.assertTrue(adapter.member_samples)
        for members in adapter.member_samples:
            self.assertEqual(members["P3"], {"truth": "FALSE", "disabled": True})
        for row in adapter.events:
            if row["key"] != "battery":
                continue
            self.assertEqual(row["member_status"]["P3"],
                             {"truth": "FALSE", "disabled": True})
            self.assertFalse(any(e.get("source_predictor") == "P3"
                                 for e in row.get("evidence", [])))

    def test_gusty_alert_feed_has_no_p3_only_battery_event(self):
        # Use the MVP's planner and MissionRun telemetry directly. The demo
        # adapter reconstructs coordinates/power and is not this mission path.
        from types import SimpleNamespace
        from gcs_demo import scenario as S
        from gcs_demo.alert_bridge import battery_raise
        from gcs_demo.energy import Vehicle, Wind
        from gcs_demo.llm import LLMBackend
        from gcs_demo.planner import plan_mission
        from gcs_demo.sim import MissionRun

        vehicle, wind, mission = Vehicle(), Wind(**S.WIND), S.mission()
        plan = plan_mission(mission, vehicle, wind, backend=LLMBackend())
        chosen = next(c for c in plan["candidates"] if c["id"] == plan["rule_choice"])
        self.assertTrue(chosen["feasible"])
        self.assertFalse(chosen.get("sorties"))
        # AlertFeed changes these module globals; restore even on failure.
        with patch.object(energy_api, "REF_LAT", energy_api.REF_LAT), \
             patch.object(energy_api, "REF_LON", energy_api.REF_LON):
            feed = AlertFeed(mission["home"], chosen["path"], vehicle, explain_fn=None)
            adapter = SimpleNamespace(feed=feed, events=feed.events, member_samples=[])
            run = MissionRun(vehicle, wind, S.TRUE_CALIB, S.WIND_EVENTS)

            def on_tick(rec, next_idx):
                rows = feed.tick(rec, next_idx)
                adapter.member_samples.append(dict(feed.engine.last_state["battery_members"]))
                # Same battery stop condition as server /api/start.
                return battery_raise(rows) is not None

            run.fly(chosen, on_tick=on_tick)
            self.assertTrue(run.log)
            self.assert_p3_disabled(adapter)
            battery = [r for r in feed.events if r["key"] == "battery"]
            self.assertTrue(battery, "MVP mission must exercise a real P1/P2 battery event")
            first = battery[0]
            self.assertEqual(first["type"], "raise")
            self.assertEqual(first["t"], run.log[-1]["t_s"])
            for row in battery:
                if row["type"] == "raise":
                    self.assertTrue(any(row["member_status"][p]["truth"] == "TRUE"
                                        for p in ("P1", "P2")))
            # No demo-route time target: mission route/voltage differ. Claude's
            # prior MVP run observed t=306; this test asserts event semantics.

    def test_direct_engine_default_keeps_p3_raise_at_126(self):
        # No factory override: run_demo's original constructor/default path.
        with patch.object(energy_api, "REF_LAT", energy_api.REF_LAT), \
             patch.object(energy_api, "REF_LON", energy_api.REF_LON):
            result = sim.run(scenario="gusty", policy="ignore", explain_fn=None)
        first = next(r for r in result["events"]
                     if r["key"] == "battery" and r["type"] == "raise")
        self.assertEqual(first["t"], 126.0)
        self.assertEqual(first["member_status"]["P3"]["truth"], "TRUE")
        self.assertNotIn("disabled", first["member_status"]["P3"])
        self.assertTrue(any(e.get("source_predictor") == "P3"
                            for e in first["evidence"]))

    def test_calm_with_p3_disabled_has_no_battery_events(self):
        result, adapter = _mvp_run("calm")
        self.assert_p3_disabled(adapter)
        self.assertEqual([r for r in result["events"] if r["key"] == "battery"], [])


if __name__ == "__main__":
    unittest.main()
