"""正式 UI 面板送真實航點到 /api/plan，以及遙測頁讀 /api/report。"""
import os
import unittest
from unittest import mock

from . import scenario as S
from . import server as srv
from .mission_input import mission_from_body


def ui_mission():
    m = S.mission()
    return {"name": "規劃頁任務", "home": {"lat": m["home"]["lat"], "lon": m["home"]["lon"]}, "cruise_alt_m": 50,
            "speed_mps": 8.0,
            "targets": [{"id": f"WP{i}", "lat": t["lat"], "lon": t["lon"], "alt": 50.0, "required": t["priority"] == 1}
                        for i, t in enumerate(m["targets"], start=1)]}


class MissionInput(unittest.TestCase):
    def test_valid_mission_maps_required_to_priority(self):
        m = mission_from_body(ui_mission())
        self.assertEqual([t["priority"] for t in m["targets"]], [1, 1, 2, 1, 2, 1])
        self.assertEqual(m["source"], "ui")
        self.assertEqual(m["no_fly"], [])

    def test_rejects_bad_input(self):
        bad = []
        m = ui_mission(); m["targets"] = []; bad.append(m)
        m = ui_mission(); m["targets"][1]["id"] = "WP1"; bad.append(m)
        m = ui_mission(); m["targets"][0]["lat"] = float("nan"); bad.append(m)
        m = ui_mission(); m["targets"][0]["lat"] += 0.3; bad.append(m)          # 超過 20 km
        m = ui_mission(); m["targets"][0]["required"] = "yes"; bad.append(m)
        m = ui_mission(); m["targets"][0]["alt"] = 500; bad.append(m)
        m = ui_mission(); m["home"] = None; bad.append(m)
        for b in bad:
            with self.assertRaises(ValueError):
                mission_from_body(b)


class PlanWithUiMission(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"GCS_LLM_BACKEND": "none"})
        self.env.start()
        srv.SESSION.reset()

    def tearDown(self):
        srv.SESSION.reset()
        self.env.stop()

    def test_plan_uses_ui_waypoints_and_report_is_readable(self):
        self.assertIsNone(srv.handle("/api/report", {})["report"])
        p = srv.handle("/api/plan", {"mission": ui_mission(), "wind": {"speed_mps": 4.0, "from_deg": 270.0}})
        self.assertIn("candidates", p)
        ids = {i for c in p["candidates"] for i in c["order"]}
        self.assertTrue(ids <= {f"WP{i}" for i in range(1, 7)} and "WP1" in ids)
        self.assertEqual(p["pick"]["source"], "rule")
        r = srv.handle("/api/start", {"mission_version": p["mission_version"], "choice_id": p["rule_choice"]})
        if "replan" in r:
            rp = r["replan"]
            r = srv.handle("/api/continue", {"mission_version": rp["mission_version"],
                                             "choice_id": rp["pick"]["choice_id"] or rp["rule_choice"]})
        rep = srv.handle("/api/report", {})
        self.assertEqual(rep["mission_source"], "ui")
        self.assertEqual(rep["report"]["summary_zh"], r["report"]["summary_zh"])

    def test_bad_mission_is_refused_and_session_unchanged(self):
        m = ui_mission(); m["targets"][0]["lat"] = 999
        out = srv.handle("/api/plan", {"mission": m})
        self.assertIs(out["ok"], False)
        self.assertIn("緯度", out["reason_zh"])
        self.assertNotEqual(srv.SESSION.mission.get("source"), "ui")

    def test_plan_without_mission_keeps_demo(self):
        p = srv.handle("/api/plan", {})
        self.assertEqual(p["rule_choice"], "C3")
        self.assertEqual(srv.handle("/api/report", {})["mission_source"], "demo")


if __name__ == "__main__":
    unittest.main()
