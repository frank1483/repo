"""第四輪（演算法說明 v3.8）：只驗證 A 的 schema 修正。假模型，不呼叫 Ollama。"""
import json
import os
import tempfile
import unittest

from . import a4_runner as A4
from .agent_m4b import M4bController
from .agent_planb import PlanBController
from .test_m4b import COUNTER, GRAPH, scripted
from .test_round3 import tools3


class StrictParams(unittest.TestCase):
    def test_a4_step_schema_requires_empty_params(self):
        m = scripted(['{"action":"QUERY_AREA","ids":["A003"],"params":{}}', '{"action":"GEN_COVERAGE","ids":[],"params":{}}',
                      '{"action":"VERIFY_PREVIEW","ids":[],"params":{}}'])
        _, T = tools3(["A003"])
        pre = {"directions": ["plan"], "stage1_calls": 1, "stage1_source": "model", "stage1_raw": ["plan"]}
        r = A4.A4Controller(T, m, GRAPH, COUNTER, preset=pre).request("南側巡檢")
        self.assertEqual(r["status"], "DONE")
        shapes = m.calls[0]["schema"]["anyOf"]
        for sh in shapes:
            p = sh["properties"]["params"]
            self.assertEqual((p.get("properties"), p.get("additionalProperties")), ({}, False), sh["properties"]["action"])
        self.assertEqual(r["calls_used"], 4)                     # 沿用的第 1 段 1 次＋3 步

    def test_layout_keeps_value_params(self):
        c = A4.A4Controller({}, None, GRAPH, COUNTER)
        task = {"cands": {"layout": ["C014", "P002"]}}
        p = c.action_shape(task, "layout", "UI_LAYOUT_PROPOSE", strict_params=True)[1]
        self.assertEqual(p["required"], ["value"])

    def test_plain_a_and_b_unchanged(self):
        self.assertFalse(M4bController.strict_params)
        self.assertFalse(PlanBController.strict_params)
        task = {"cands": {"plan": ["A003"]}}
        self.assertEqual(PlanBController({}, None, GRAPH, COUNTER).action_shape(task, "plan", "QUERY_AREA")[1],
                         {"type": "object"})

    def test_nonempty_params_counter(self):
        reply = {"traces": [{"purpose": "step:plan", "replies": [
            {"raw": '{"action":"QUERY_AREA","ids":["A001"],"params":{"x":"y"}}'},
            {"raw": '{"action":"QUERY_AREA","ids":["A001"],"params":{}}'}]},
            {"purpose": "step:color", "replies": [{"raw": '{"action":"UI_THEME_PROPOSE","ids":["T001"],"params":{"":""}}'}]},
            {"purpose": "step:layout", "replies": [{"raw": '{"action":"UI_LAYOUT_PROPOSE","ids":["P001"],"params":{"value":"大"}}'}]}]}
        self.assertEqual(A4.nonempty_params(reply), (2, 1))

    def _probe(self, fn):
        d = tempfile.mkdtemp()
        return A4.probe(lambda log: fn, d), d

    def test_probe_requires_contrast(self):
        def honest(call):                       # 後端真的執行約束
            strict = call["schema"]["anyOf"][0]["properties"]["params"].get("additionalProperties") is False
            return '{"action":"GEN_COVERAGE","ids":[],"params":' + ('{}' if strict else '{"a":"b"}') + '}'
        self.assertTrue(self._probe(honest)[0]["enforced"])

        def always_empty(call):                 # 模型本來就回空 → 無法區辨 → 不通過
            return '{"action":"GEN_COVERAGE","ids":[],"params":{}}'
        self.assertFalse(self._probe(always_empty)[0]["enforced"])

        def ignores(call):                      # 後端忽略約束
            return '{"action":"GEN_COVERAGE","ids":[],"params":{"a":"b"}}'
        self.assertFalse(self._probe(ignores)[0]["enforced"])

        def partial(call):                      # 只回 params，完整輸出不合格
            strict = call["schema"]["anyOf"][0]["properties"]["params"].get("additionalProperties") is False
            return '{"params":{}}' if strict else '{"action":"GEN_COVERAGE","ids":[],"params":{"a":"b"}}'
        self.assertFalse(self._probe(partial)[0]["enforced"])

    def test_probe_failure_stops_before_cases(self):
        d = tempfile.mkdtemp()
        A4._S["out"], A4._S["probe"] = d, None

        def bad_factory(log):
            return lambda call: '{"action":"GEN_COVERAGE","ids":[],"params":{"area":"A001"}}'
        with self.assertRaises(SystemExit):
            A4.run_case({"id": "F01"}, {"id": "A-s6-b30"}, bad_factory, None, None, d)
        self.assertFalse(json.load(open(os.path.join(d, "BACKEND_PROBE.json"), encoding="utf-8"))["enforced"])
        A4._S["probe"] = None

    def test_existing_output_untouched(self):
        out = tempfile.mkdtemp()
        p = os.path.join(out, "RUN_INFO.json")
        with open(p, "wb") as f:
            f.write(b'{"backend_probe_enforced": true}')
        before = open(p, "rb").read()
        shared = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runs",
                              "r3v5_A_fake_research_run1")         # 合法的第三輪假模型輸出 → 一路走到 m4b_runner.main 才因目錄已存在停止
        if not os.path.exists(os.path.join(shared, "results.jsonl")):
            self.skipTest("缺第三輪假模型輸出")
        with self.assertRaises(SystemExit) as cm:
            A4.main(["--phase", "research", "--fake", "--out", out, "--shared-from", shared])
        self.assertIn("輸出目錄已存在", str(cm.exception))
        self.assertEqual(open(p, "rb").read(), before)


if __name__ == "__main__":
    unittest.main()
