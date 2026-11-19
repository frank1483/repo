"""ADR-0002 新架構（方案 B）執行器：沿用 m4b_runner 的案例、計分、核對與只跑一次規則，只把控制器換成 PlanBController。

同一份案例（m4b_cases_v1.json）、同一套檢索與分批、同一主表三項，比較時只差決策方式（v3.5 第 4 題）。
規劃輸出較長：plan／replan 的 max_tokens＝512（A 每步 96）；其他與 m4b_runner 相同。
**真模型只有在 live 同意後才能執行**；--fake 不算 live。
"""
from __future__ import annotations

import sys
import time

from . import m4b_runner as R4
from .agent_planb import PlanBController

R4.M4bController = PlanBController          # run_case 內建立的控制器改為方案 B
R4.GROUP_NOTE = {"B0": "規則：方向用關鍵字表、規則計畫，零次 LLM 呼叫；查詢向量仍算 1 次",
                 "A": "方案 B：模型排方向後，每批輸出一次結構化計畫，程式驗證後執行（重規劃每任務最多 2 次）"}
MAX_TOKENS = {"plan": 512, "replan": 512, "summary": 256}


def gateway_model(gw, calls_log):
    def model(call):
        purpose = call.get("purpose", "")
        feature = R4.FEATURE.get(purpose, "agent_step")
        t0 = time.monotonic()
        st, body = gw.submit(feature, {"messages": call["messages"], "max_tokens": MAX_TOKENS.get(purpose, 96)},
                             harness="planb-v1")
        text = ""
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        calls_log.append({"purpose": purpose, "feature": feature, "status": st, "latency_s": round(time.monotonic() - t0, 3),
                          "raw": text, "usage": body.get("usage") if isinstance(body, dict) else None})
        if st != 200:
            raise RuntimeError(f"gateway {st}")
        return text
    return model


R4.gateway_model = gateway_model

_run_case = R4.run_case


def run_case(case, cond, model_factory, graph, counter, work):
    rec, full = _run_case(case, cond, model_factory, graph, counter, work)
    r = full.get("reply") or {}
    rec["replans"] = r.get("replans")
    rec["plan_states"] = [[s["id"], s["action"], s["state"]] for s in r.get("plan") or []]
    return rec, full


R4.run_case = run_case

if __name__ == "__main__":
    sys.exit(R4.main())
