"""ADR-0002 新架構（方案 B）執行器：沿用 m4b_runner 的案例、計分、核對與只跑一次規則，只把控制器換成 PlanBController。

v3（CODEX-APP-0406 第 B3 點）：A／B 共用輸入固定。`--shared-from <方案 A 同 phase 的輸出目錄>` 必填：
每個案例×條件的第 1 段方向直接沿用 A 的輸出（照 A 實際的第 1 段呼叫次數記帳，B 不再呼叫第 1 段），
並逐案例核對 B 的檢索分批（每批方向與候選 ID）是否和 A 相同，記 shared_input_match；不同就照記，不改結果。
規劃輸出較長：plan／replan 的 max_tokens＝512、期限 180 秒（m4b_runner.DEADLINE_S）。
**真模型只有在 live 同意後才能執行**；--fake 不算 live。
"""
from __future__ import annotations

import json
import os
import sys
import time

from . import m4b_runner as R4
from .agent_planb import PlanBController

R4.GROUP_NOTE = {"B0": "規則：方向用關鍵字表、規則計畫，零次 LLM 呼叫；查詢向量仍算 1 次",
                 "A": "方案 B：第 1 段方向沿用方案 A 同案例輸出；每批輸出一次結構化計畫，程式驗證後執行（重規劃每任務最多 2 次）"}
MAX_TOKENS = {"plan": 512, "replan": 512, "summary": 256}
_SHARED = {"dir": None, "current": None}


def gateway_model(gw, calls_log):
    def model(call):
        purpose = call.get("purpose", "")
        feature = R4.FEATURE.get(purpose, "agent_step")
        t0 = time.monotonic()
        st, body = gw.submit(feature, {"messages": call["messages"], "max_tokens": MAX_TOKENS.get(purpose, 96)},
                             harness="planb-v3", deadline_s=R4.deadline_for(purpose))
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


def a_record(cond, case):
    p = os.path.join(_SHARED["dir"], "cases", cond, case, "full.json")
    rep = json.load(open(p, encoding="utf-8"))["reply"] or {}
    n = sum(len(t.get("replies") or []) for t in rep.get("traces") or [] if t.get("purpose") == "stage1")
    batches = [[b["directions"], {d: v["items"] for d, v in b["per_dir"].items()}]
               for b in (rep.get("packing") or {}).get("batches") or []]
    return rep, {"directions": rep.get("directions"), "stage1_calls": n}, batches


def controller(*a, **kw):
    cond, case = _SHARED["current"]
    rep, preset, _ = a_record(cond, case)
    if not preset["directions"]:                 # A 在第 1 段前就結束（Gate）→ B 照常走自己的第 1 段（一樣會被 Gate 擋）
        preset = None
    return PlanBController(*a, preset=preset, **kw)


R4.M4bController = controller
R4.gateway_model = gateway_model
_run_case = R4.run_case


def run_case(case, cond, model_factory, graph, counter, work):
    _SHARED["current"] = (cond["id"], case["id"])
    rec, full = _run_case(case, cond, model_factory, graph, counter, work)
    r = full.get("reply") or {}
    _, preset, a_batches = a_record(cond["id"], case["id"])
    b_batches = [[b["directions"], {d: v["items"] for d, v in b["per_dir"].items()}]
                 for b in (r.get("packing") or {}).get("batches") or []]
    rec["shared_from_a"] = {"directions": preset["directions"], "stage1_calls": preset["stage1_calls"]}
    rec["shared_input_match"] = (r.get("directions") == preset["directions"]) and b_batches == a_batches
    rec["replans"] = r.get("replans")
    rec["plan_states"] = [[s["id"], s["action"], s["state"]] for s in r.get("plan") or []]
    return rec, full


R4.run_case = run_case


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--shared-from" not in argv:
        raise SystemExit("需要 --shared-from <方案 A 同 phase 的輸出目錄>（A／B 共用輸入）")
    k = argv.index("--shared-from")
    _SHARED["dir"] = argv[k + 1]
    del argv[k:k + 2]
    if not os.path.exists(os.path.join(_SHARED["dir"], "results.jsonl")):
        raise SystemExit("--shared-from 目錄沒有 results.jsonl")
    return R4.main(argv)


if __name__ == "__main__":
    sys.exit(main())
