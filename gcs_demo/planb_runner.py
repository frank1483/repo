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


def a_row(cond, case):
    rows = [json.loads(l) for l in open(os.path.join(_SHARED["dir"], "results.jsonl"), encoding="utf-8") if l.strip()]
    hit = [r for r in rows if r["cond"] == cond and r["case"] == case]
    return hit[0] if len(hit) == 1 else None


def a_valid(cond, case):
    """A 這一列可以當共用輸入嗎：唯一一列、沒有案例例外、詳細檔存在且 reply 非空。"""
    row = a_row(cond, case)
    p = os.path.join(_SHARED["dir"], "cases", cond, case, "full.json")
    if row is None or row.get("error") or not os.path.exists(p):
        return False
    try:
        return bool(json.load(open(p, encoding="utf-8")).get("reply"))
    except ValueError:
        return False


def a_record(cond, case):
    if not a_valid(cond, case):                  # v5（0409 第 1 點）：A 例外／空 reply 不當共用輸入，B 這列隔離
        return {}, {"invalid_a": True, "directions": None, "stage1_calls": 0}, None
    p = os.path.join(_SHARED["dir"], "cases", cond, case, "full.json")
    rep = json.load(open(p, encoding="utf-8"))["reply"] or {}
    n = sum(len(t.get("replies") or []) for t in rep.get("traces") or [] if t.get("purpose") == "stage1")
    batches = [[b["directions"], {d: v["items"] for d, v in b["per_dir"].items()}]
               for b in (rep.get("packing") or {}).get("batches") or []]
    preset = {"directions": rep.get("directions"), "stage1_calls": n}
    if rep.get("status") in ("INVALID_INPUT", "TOO_LONG"):
        preset = None                            # Gate 擋下：第 1 段沒跑，B 自己的 Gate 會得到同樣結果
    elif not rep.get("directions"):              # 第 1 段跑了但在規劃前結束（例如方向超過上限）→ B 照 A 的結果結束
        preset["terminal"] = {"status": rep.get("status"), "reply_zh": rep.get("reply_zh"),
                              "reason": "；".join(rep.get("notes") or [])}
    return rep, preset, batches


def controller(*a, **kw):
    cond, case = _SHARED["current"]
    _, preset, _ = a_record(cond, case)
    if preset and preset.get("invalid_a"):     # 照常跑 B（保留原始結果），但這列不進主表
        preset = None
    return PlanBController(*a, preset=preset, **kw)


R4.M4bController = controller
R4.gateway_model = gateway_model
_run_case = R4.run_case


def run_case(case, cond, model_factory, graph, counter, work):
    _SHARED["current"] = (cond["id"], case["id"])
    rec, full = _run_case(case, cond, model_factory, graph, counter, work)
    r = full.get("reply") or {}
    a_rep, preset, a_batches = a_record(cond["id"], case["id"])
    b_batches = [[b["directions"], {d: v["items"] for d, v in b["per_dir"].items()}]
                 for b in (r.get("packing") or {}).get("batches") or []]
    rec["shared_from_a"] = preset and {k: preset.get(k) for k in ("directions", "stage1_calls", "invalid_a")}
    rec["shared_input_match"] = not (preset or {}).get("invalid_a") and \
        (r.get("directions") or []) == (a_rep.get("directions") or []) and b_batches == a_batches
    # v4（0408 第 2 點）：首頁相依改按實際步驟來源核對——提案引用的預覽必須是本計畫某個 VERIFY 步驟產生的合格預覽
    deps = case.get("expect_dependency") or {}
    if deps and r:
        good = {}
        for s in r.get("plan") or []:
            pv = (s.get("out") or {}).get("route_preview") or {}
            if s["action"] == "VERIFY_PREVIEW" and s.get("state") == "OK" and pv.get("verdict") == "pass":
                good[pv.get("ref")] = pv
        art = dict(r.get("artifacts") or {})
        for p in r.get("proposals") or []:
            src = p.get("source") or {}
            if p["action"] == "PROPOSE_HOME_ROUTE" and src.get("verdict") == "pass" and src.get("preview_ref") in good:
                art["route_preview"] = good[src["preview_ref"]]       # v5：整份換成實際綁定的預覽（含判定）
        rescored = R4.score(case, dict(r, artifacts=art))
        if rescored["correct"] != rec["correct"]:
            rec["rescored_by_step_source"] = True
        rec.update(rescored)
    rec["replans"] = r.get("replans")
    rec["plan_states"] = [[s["id"], s["action"], s["state"]] for s in r.get("plan") or []]
    return rec, full


R4.run_case = run_case
_summarize = R4.summarize


def summarize(recs):
    """v4（0408 第 1 點）：共用輸入不一致的列隔離，不進主表；另報不一致數與列。"""
    ok = [r for r in recs if r.get("shared_input_match")]
    bad = [r for r in recs if not r.get("shared_input_match")]
    out = _summarize(ok) if ok else {}
    out["_shared_input_mismatch"] = {"n": len(bad), "rows": [[r["cond"], r["case"]] for r in bad]}
    return out


R4.summarize = summarize


def check_a_dir(phase, fake):
    """鎖定 A 同 phase 的完整輸出：phase、fake／live、來源包（live 須為 M4b v3 已同意的包）、結束時間與案例數。"""
    info = json.load(open(os.path.join(_SHARED["dir"], "RUN_INFO.json"), encoding="utf-8"))
    rows = [json.loads(l) for l in open(os.path.join(_SHARED["dir"], "results.jsonl"), encoding="utf-8") if l.strip()]
    n_cases = len(json.load(open(R4.CASES, encoding="utf-8"))["cases"])
    want = {c["id"] for c in R4.CONDITIONS[phase]}
    errs = []
    if info.get("phase") != phase:
        errs.append(f"A phase={info.get('phase')}，B phase={phase}")
    if bool(info.get("fake")) != bool(fake):
        errs.append("A 與 B 的 fake／live 不一致")
    if not fake and (info.get("bundle_verification") or {}).get("sums_sha256") != A_BUNDLE_SHA:
        errs.append("A 不是用已同意的 M4b v3 來源包跑的")
    if not info.get("end"):
        errs.append("A 沒有正常結束")
    case_ids = {c["id"] for c in json.load(open(R4.CASES, encoding="utf-8"))["cases"]}
    pairs = [(r["cond"], r["case"]) for r in rows]
    if len(pairs) != len(set(pairs)):
        errs.append("A 有重複的條件×案例列")
    if {r["cond"] for r in rows} != want:
        errs.append(f"A 的條件 {sorted({r['cond'] for r in rows})} 與 B 的 {sorted(want)} 不同")
    for c in want:
        got = {r["case"] for r in rows if r["cond"] == c}
        if got != case_ids:
            errs.append(f"A 條件 {c} 的案例不完整（{len(got)}/{n_cases}）")
        for k in got:
            if not os.path.exists(os.path.join(_SHARED["dir"], "cases", c, k, "full.json")):
                errs.append(f"A 缺 {c}/{k}/full.json")
    if (info.get("summary") or None) is None:
        errs.append("A 沒有寫出摘要（可能沒有正常結束）")
    if errs:
        raise SystemExit("--shared-from 核對不通過：" + "；".join(errs))
    bad = sorted([r["cond"], r["case"]] for r in rows if not a_valid(r["cond"], r["case"]))
    return {"dir": os.path.abspath(_SHARED["dir"]), "phase": info.get("phase"), "fake": info.get("fake"),
            "a_rows_isolated": bad,
            "a_bundle_sha256": (info.get("bundle_verification") or {}).get("sums_sha256"), "a_end": info.get("end")}


A_BUNDLE_SHA = "81b575ac6dd9ce157b25a9278a5115258801b9e701cb69bd3b2bd6c76809b0bb"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--shared-from" not in argv:
        raise SystemExit("需要 --shared-from <方案 A 同 phase 的輸出目錄>（A／B 共用輸入）")
    k = argv.index("--shared-from")
    _SHARED["dir"] = argv[k + 1]
    del argv[k:k + 2]
    if not os.path.exists(os.path.join(_SHARED["dir"], "results.jsonl")):
        raise SystemExit("--shared-from 目錄沒有 results.jsonl")
    phase = argv[argv.index("--phase") + 1]
    shared = check_a_dir(phase, "--fake" in argv)
    out = argv[argv.index("--out") + 1]
    rc = R4.main(argv)
    p = os.path.join(out, "RUN_INFO.json")                 # 把共用來源記進 B 的 RUN_INFO（主程式結束後補一欄）
    info = json.load(open(p, encoding="utf-8"))
    info["shared_from_a"] = shared
    json.dump(info, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    return rc


if __name__ == "__main__":
    sys.exit(main())
