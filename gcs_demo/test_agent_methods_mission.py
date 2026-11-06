"""任務規劃方法庫（新迴圈）的離線測試：假後端照劇本回覆，不連網。

    python -m unittest gcs_demo.test_agent_methods_mission
"""
from __future__ import annotations

import unittest

from gcs_demo import agent_methods_mission as M

CANDS = [
    {"id": "C1", "label": "距離最短", "order": ["T1", "T2"], "time_min": 9.1, "energy_wh": 40.2, "end_pct": 41, "feasible": True},
    {"id": "C2", "label": "能耗最低", "order": ["T1", "T2"], "time_min": 9.8, "energy_wh": 38.0, "end_pct": 44, "feasible": True},
    {"id": "C3", "label": "最快", "order": ["T1", "T2"], "time_min": 7.0, "energy_wh": 55.0, "end_pct": 12, "feasible": False},
    {"id": "S1", "label": "分兩趟", "order": ["T1", "T2"], "time_min": 14.0, "energy_wh": 60.0, "end_pct": 50, "feasible": True,
     "requires_battery_swap": True},
]
EV = [{"id": "E1", "text": "風速 4 m/s，風從 90° 吹來"}, {"id": "E2", "text": "電池 99 Wh"},
      {"id": "E3", "text": "C1 距離最短：落地剩 41%，可行"}, {"id": "E4", "text": "C2 能耗最低：落地剩 44%，可行"},
      {"id": "E5", "text": "C3 最快：落地剩 12%，不可行"}, {"id": "E6", "text": "S1 分兩趟：落地剩 50%，可行"},
      {"id": "E7", "text": "觸發事件：風變強"}]


class FakeBackend:
    name = "fake"
    model = "fake-1b"

    def __init__(self, replies, up=True):
        self.replies = list(replies)
        self.up = up
        self.seen = []

    def available(self):
        return self.up

    def complete_json(self, system, user, schema, timeout_s=None):
        self.seen.append((system, user, schema))
        r = self.replies.pop(0)
        if r is None:
            return {"ok": False, "data": None, "raw": "", "latency_s": 0.1, "error": "timed out", "backend": self.name, "model": self.model}
        return {"ok": True, "data": None, "raw": r, "latency_s": 0.2, "error": None, "backend": self.name, "model": self.model}


def pick(replies, up=True, rc="C2"):
    b = FakeBackend(replies, up)
    return M.pick_candidate(b, "出發前任務規劃：選一條航線。", CANDS, EV, rc), b


class MissionPickTest(unittest.TestCase):
    def test_model_picks_applicable(self):
        p, b = pick(['{"value":"C1"}'])
        self.assertEqual((p["decision"], p["choice_id"], p["source"]), ("SELECT", "C1", "llm"))
        self.assertEqual(p["evidence_ids"], ["E1", "E2", "E3"])
        self.assertIn("與規則選擇 C2 不同", p["reason_zh"])
        self.assertEqual(len(b.seen), 1)
        user = b.seen[0][1]
        self.assertIn("只能選：C1 ", user)
        self.assertNotIn("C3 最快", user)          # 不可行的不給選
        self.assertNotIn("S1 ", user.split("只能選：")[1])  # 要換電的不給選
        self.assertIn("E7：觸發事件：風變強", user)
        self.assertEqual(p["llm"]["ok"], True)

    def test_hold(self):
        p, _ = pick(['{"value":"HOLD"}'])
        self.assertEqual((p["decision"], p["choice_id"], p["source"]), ("HOLD", "", "llm"))

    def test_repair_once_then_ok(self):
        p, b = pick(['{"decision":"SELECT","choice_id":"C2"}', '{"value":"C2"}'])
        self.assertEqual((p["choice_id"], p["source"]), ("C2", "llm"))
        self.assertIn("上次錯誤：只能有 value 一個欄位", b.seen[1][1])

    def test_invalid_twice_rule(self):
        p, b = pick(['{"value":"C3"}', '{"value":"S1"}'])
        self.assertEqual((p["decision"], p["choice_id"], p["source"]), ("SELECT", "C2", "rule"))
        self.assertIn("已退回規則", p["reason_zh"])
        self.assertEqual(len(b.seen), 2)
        self.assertFalse(p["llm"]["ok"])

    def test_timeout_then_ok(self):
        p, _ = pick([None, '{"value":"C2"}'])
        self.assertEqual((p["choice_id"], p["source"]), ("C2", "llm"))

    def test_backend_down_rule_no_call(self):
        p, b = pick([], up=False)
        self.assertEqual((p["choice_id"], p["source"], p["llm"]), ("C2", "rule", None))
        self.assertEqual(b.seen, [])

    def test_schema_is_single_value(self):
        _, b = pick(['{"value":"C2"}'])
        self.assertEqual(b.seen[0][2], {"required": {"value": "str"}})


if __name__ == "__main__":
    unittest.main()
