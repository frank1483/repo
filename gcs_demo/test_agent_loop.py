"""一致性測試：Python 引擎必須逐字重現 gcs_demo/agent_loop_vectors.json（JS 引擎也跑同一份）。

    python -m unittest gcs_demo.test_agent_loop
"""
from __future__ import annotations

import copy
import json
import os
import unittest

from gcs_demo import agent_loop as L

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS = json.load(open(os.path.join(HERE, "agent_loop_vectors.json"), encoding="utf-8"))


class SpecLib:
    """與 ui_agent/test/slot_loop_spec_lib.js 相同邏輯的宣告式方法庫，只給一致性測試用。"""

    def __init__(self, spec):
        self.spec = spec
        self.h = None

    def _act(self, a):
        h = self.h
        for k, v in (a.get("set") or {}).items():
            if k == "kind":
                h.st["kind"] = v
            else:
                h.st["slots"][k] = v
        if a.get("go"):
            h.go(a["go"], a.get("obs"))
            return ""
        if a.get("finish"):
            h.finish(a["finish"], a.get("source"), a.get("why"))
            return ""
        if a.get("escalate"):
            h.escalate(a["escalate"])
            return ""
        if a.get("rule"):
            h.rule_fallback(a["rule"], a.get("source"))
            return ""
        if a.get("problem"):
            return a["problem"]
        raise ValueError("bad action")

    def begin(self, h):
        self.h = h
        self._act(self.spec["start"])

    def options(self, st):
        s = self.spec["states"][st["state"]]
        return {"need": s["need"], "allowed": [{"code": c, "zh": z} for c, z in s["allowed"]]}

    def header(self, st):
        lines = list(self.spec["header"]) + ["目前步驟：" + st["state"]]
        if st["kind"]:
            lines.append("已知：類別=" + st["kind"])
        if st["last_observation"]:
            lines.append("觀察：" + st["last_observation"])
        return lines

    def transition(self, code, h):
        return self._act(self.spec["states"][h.st["state"]]["on"][code])

    def rule_decision(self):
        return copy.deepcopy(self.spec["rule"])


class ConformanceTest(unittest.TestCase):
    def test_vectors(self):
        for v in VECTORS["vectors"]:
            with self.subTest(v["name"]):
                cfg = v["config"]
                kw = {"version": "vec-1", "system_prompt": "只填一格", "goal": v["spec"]["goal"]}
                if cfg["maxCalls"]:
                    kw["max_calls"] = cfg["maxCalls"]
                if cfg["modelEnabled"] is not None:
                    kw["model_enabled"] = cfg["modelEnabled"]
                s = L.Session(SpecLib(v["spec"]), **kw)
                replies = iter(v["replies"])

                def model(call, replies=replies):
                    try:
                        return next(replies)
                    except StopIteration:
                        raise RuntimeError("script exhausted")
                r = L.run(s, model)
                got = {"decision": r["decision"], "model_calls": r["model_calls"], "trace": r["trace"],
                       "prompts": [c["messages"][1]["content"] for c in r["calls"]],
                       "codes": [c["codes"] for c in r["calls"]], "repair_flags": [c["repair"] for c in r["calls"]]}
                self.assertEqual(got, v["expect"])


if __name__ == "__main__":
    unittest.main()
