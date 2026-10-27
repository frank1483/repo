import unittest
from unittest import mock

from gcs_demo import scenario as S
from gcs_demo import llm
from gcs_demo.energy import Vehicle, Wind, estimate_route_energy, rtl_energy
from gcs_demo.planner import plan_mission, replan
from gcs_demo.report import make_report
from gcs_demo.sim import MissionRun


class FakeBackend(llm.LLMBackend):
    name = "fake"

    def __init__(self, data):
        super().__init__("http://x", "fake")
        self.data = data

    def available(self):
        return True

    def complete_json(self, system, user, schema, timeout_s=60):
        return {"ok": True, "data": self.data, "raw": "", "latency_s": 0, "error": None,
                "backend": "fake", "model": "fake"}


def full_run(backend=None):
    v, w = Vehicle(), Wind(**S.WIND)
    p = plan_mission(S.mission(), v, w, backend or llm.LLMBackend())
    ch = next(c for c in p["candidates"] if c["id"] == p["rule_choice"])
    run = MissionRun(v, w, S.TRUE_CALIB, S.WIND_EVENTS)
    st = run.fly(ch, stop_at_s=S.EVENT_AT_S)
    r = replan(S.mission(), v, w, st, {"type": "wind", "speed_mps": 9, "from_deg": 240, "text_zh": "風"},
               llm.LLMBackend())
    run.fly(next(c for c in r["candidates"] if c["id"] == r["rule_choice"]))
    return p, r, run, ch


class TestDemo(unittest.TestCase):
    def test_energy_headwind_costs_more(self):
        v = Vehicle()
        route = [{"lat": 24.786, "lon": 120.997, "alt": 50}, {"lat": 24.786, "lon": 120.987, "alt": 50}]
        calm = estimate_route_energy(route, v, Wind(0, 0))
        head = estimate_route_energy(route, v, Wind(8, 270))   # 往西飛、西風＝逆風
        tail = estimate_route_energy(route, v, Wind(8, 90))
        self.assertGreater(head["energy_wh"], calm["energy_wh"])
        self.assertEqual(len(head["legs"]), 1)
        self.assertGreater(head["energy_wh"], tail["energy_wh"])
        self.assertGreater(rtl_energy(route[1], route[0], v, Wind())["energy_wh"], 0)

    def test_plan_rule_choice_feasible(self):
        p = plan_mission(S.mission(), Vehicle(), Wind(**S.WIND), llm.LLMBackend())
        c = next(c for c in p["candidates"] if c["id"] == p["rule_choice"])
        self.assertTrue(c["feasible"])
        self.assertEqual(p["pick"]["source"], "rule")

    def test_replan_after_wind_learns_ratio_and_lands_safely(self):
        p, r, run, ch = full_run()
        self.assertGreater(r["state"]["observed_ratio"], 1.05)
        self.assertFalse(next(c for c in r["candidates"] if c["id"] == "L1")["feasible"])
        self.assertGreaterEqual(run.pct, Vehicle().reserve_pct - 3)
        rep = make_report(run, S.mission(), ch, [r], [], llm.LLMBackend())
        self.assertGreater(rep["next_calib"], 1.05)
        ids = {f["id"] for f in rep["facts"]}
        for s in rep["suggestions"]:
            self.assertTrue(set(s["evidence_ids"]) <= ids)

    def test_llm_invalid_choice_falls_back(self):
        fb = FakeBackend({"decision": "SELECT", "choice_id": "NOPE", "reason_zh": "x", "evidence_ids": []})
        p = plan_mission(S.mission(), Vehicle(), Wind(**S.WIND), fb)
        self.assertEqual(p["pick"]["source"], "rule")
        self.assertEqual(p["pick"]["choice_id"], p["rule_choice"])

    def test_llm_valid_choice_used(self):
        fb = FakeBackend({"decision": "SELECT", "choice_id": "C5", "reason_zh": "省電", "evidence_ids": ["E1", "E404"]})
        p = plan_mission(S.mission(), Vehicle(), Wind(**S.WIND), fb)
        self.assertEqual((p["pick"]["choice_id"], p["pick"]["source"]), ("C5", "llm"))
        self.assertEqual(p["pick"]["evidence_ids"], ["E1"])

    def test_report_drops_ungrounded_suggestions(self):
        p, r, run, ch = full_run()
        fb = FakeBackend({"summary_zh": "摘要", "suggestions": [
            {"text_zh": "有根據", "evidence_ids": ["F3"]}, {"text_zh": "捏造", "evidence_ids": ["F999"]}]})
        rep = make_report(run, S.mission(), ch, [r], [], fb)
        self.assertEqual([s["text_zh"] for s in rep["suggestions"]], ["有根據"])

    def test_backend_none_by_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(llm.get_backend().available())


if __name__ == "__main__":
    unittest.main()
