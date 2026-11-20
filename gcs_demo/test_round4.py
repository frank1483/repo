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

    def test_probe_failure_stops_before_cases(self):
        d = tempfile.mkdtemp()
        A4._S["out"], A4._S["probe"] = d, None

        def bad_factory(log):
            return lambda call: '{"action":"GEN_COVERAGE","ids":[],"params":{"area":"A001"}}'
        with self.assertRaises(SystemExit):
            A4.run_case({"id": "F01"}, {"id": "A-s6-b30"}, bad_factory, None, None, d)
        self.assertFalse(json.load(open(os.path.join(d, "BACKEND_PROBE.json"), encoding="utf-8"))["enforced"])
        A4._S["probe"] = None


if __name__ == "__main__":
    unittest.main()
