"""ADR-0002 M4b 執行器（方案 A 逐方向逐步；演算法說明 v3.4）。

沿用 m4_runner 的來源包核對、專用 Ollama（埠／PID 歸屬）、RAM 取樣、只跑一次與結果先寫規則。
主表三項（使用者 2026-11-19 裁決 Z-1／Z-2）：正確提案完成率、到提案就緒的 P95 延遲、每案例 LLM 呼叫次數。
- 正確提案完成率：應開的提案（動作＋ID 集合＋允許值）全部開對、沒有多開、必要成果判定相符、終態相符，才算正確。
- 提案就緒時間：從句子送出到整理回覆前（t_pre_summary_s）；含整理回覆的總延遲另列（elapsed_s）。
- LLM 呼叫：所有決策模型呼叫（第 1 段、每一步、整理回覆）；EmbeddingGemma 2 編碼另計（每句 1 次）。
**真模型只有在 live 同意後才能執行**（兩方對同一份來源包 SHA256 精確同意，使用者親打「同意 <hash8>」）。
--fake 只用固定回覆的假模型檢查執行器，不算 live。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

from . import llm_gateway as G
from . import m4_runner as R
from .agent_m4b import M4bController
from . import gemma4_tokenizer as TK
from .id_graph import load_index

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "m4b_cases_v2.json")
# v4（v3.6 §6）：校準＝開發集（首跑 36 題，已看過失敗）；研究＝評估集（沒有用來調提示）
CASES_BY_PHASE = {"calib": os.path.join(HERE, "m4b_cases_dev_v3.json"), "research": os.path.join(HERE, "m4b_cases_eval_v2.json")}
# v3.7 §5：calib＝開發集（前兩輪看過的 60 題）；research＝第三輪評估集 v2（沒有參與調整）
DEFAULT_ID_INDEX = os.path.join(R.BASE_DOC, "adr0002_rag_v1", "id_index_v1")
CONDITIONS = {
    "calib": [{"id": "A-s6-b30", "group": "A", "steps": 6, "budget": 30}],
    "research": [{"id": "B0", "group": "B0", "steps": 6, "budget": 0},
                 {"id": "A-s6-b30", "group": "A", "steps": 6, "budget": 30}],
}
GROUP_NOTE = {"B0": "規則：方向用關鍵字表、每步用規則腳本，零次 LLM 呼叫；查詢向量仍算 1 次",
              "A": "方案 A：模型排方向並逐步選動作（每步只看當前方向的候選）"}
FEATURE = {"stage1": "agent_dir", "summary": "agent_resume"}
# v3：閘道每功能預設 15 秒，對 1,500～3,000 token 的提示太短（CPU prefill 約 6.3 ms/token）；本實驗明訂每次呼叫的期限
DEADLINE_S = {"stage1": 60.0, "step": 60.0, "plan": 180.0, "replan": 180.0, "summary": 60.0}


GATEWAY_BUDGETS = {"agent_dir": 60.0, "agent_step": 180.0, "agent_resume": 60.0}   # 上限；每次呼叫再用 DEADLINE_S 縮短


def deadline_for(purpose):
    return DEADLINE_S.get(purpose.split(":")[0], 60.0)


EXTRA_INFO = None          # 可呼叫物件：回傳要併入 RUN_INFO 的欄位；None＝不加（A、B 的正式執行都不設）
MAX_TOKENS = {"summary": 256, "plan": 512, "replan": 512}
HARNESS = {"name": "m4b-v5"}
TIMING_KEYS = ("prompt_eval_count", "eval_count", "prompt_eval_duration", "eval_duration", "load_duration", "total_duration")


def gateway_model(gw, calls_log):
    """v4（演算法說明 v3.6 §6）：有 schema 就交給 Ollama 做 JSON Schema 約束；記錄提示處理／生成／載入時間。"""
    def model(call):
        purpose = call.get("purpose", "")
        feature = FEATURE.get(purpose, "agent_step")
        req = {"messages": call["messages"], "max_tokens": MAX_TOKENS.get(purpose.split(":")[0], 96)}
        if call.get("schema") is not None:
            req["response_format"] = {"type": "json_schema", "json_schema": {"schema": call["schema"]}}
        t0 = time.monotonic()
        st, body = gw.submit(feature, req, harness=HARNESS["name"], deadline_s=deadline_for(purpose))
        text = ""
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        meta = (body.get("gcs_upstream_meta") or {}) if isinstance(body, dict) else {}
        calls_log.append({"purpose": purpose, "feature": feature, "status": st, "latency_s": round(time.monotonic() - t0, 3),
                          "raw": text, "schema": call.get("schema") is not None,
                          "attempt": call.get("attempt"), "decision": call.get("decision"),
                          "timing": {k: meta.get(k) for k in TIMING_KEYS if k in meta},
                          "error": (body.get("error") or {}).get("message") if isinstance(body, dict) and st != 200 else None})
        if st != 200:
            raise RuntimeError(f"gateway {st}")
        return text
    return model


def fake_model(calls_log):
    """固定回覆：第 1 段回關鍵字表方向，每步回 FINISH 以外的不合法字串 → 走規則腳本；整理回覆回不合法 → 模板。"""
    from .agent_m4b import KEYWORDS, KINDS

    def model(call):
        purpose = call.get("purpose", "")
        text = call["messages"][1]["content"]
        if purpose == "stage1":
            sent = text.split("\n", 1)[0]
            out = json.dumps({"directions": [k for k in KINDS if any(w in sent for w in KEYWORDS.get(k, []))] or ["chat"]},
                             ensure_ascii=False)
        else:
            out = "not json"
        calls_log.append({"purpose": purpose, "feature": "fake", "status": 200, "latency_s": 0.0, "raw": out, "usage": None})
        return out
    return model


def _want(p):
    params = {"value": p["values"][0]} if p["values"] else {}
    return (p["action"], frozenset(p["ids"]), tuple(sorted(params.items())))


def score(case, r):
    """v2（CODEX-APP-0405 第 2、3 點）：提案逐項比動作、ID 集合、具名參數（鍵＋值）與狀態 PROPOSED；重複開窗算多開。
    提案就緒時間＝最後一個應有提案「第一次」記 PROPOSED 的時間，只在該案例提案全對時定義。"""
    want = [_want(p) for p in case["expect_proposals"]]
    by = []
    deps = case.get("expect_dependency") or {}
    got = [((p["action"], frozenset(p["ids"]), tuple(sorted(p["params"].items()))), p) for p in r.get("proposals") or []]
    rest = list(got)
    hit_t = []
    for w in want:
        m = next((g for g in rest if g[0] == w and g[1].get("state") == "PROPOSED"), None)
        if m is not None:
            rest.remove(m)
            hit_t.append(m[1].get("t_ready_s"))
            by.append(m[1].get("by", "rule"))
    A = r.get("artifacts") or {}
    arts = {}
    for k, v in case["expect_artifacts"].items():
        a = A.get(k)
        ok = a is not None and (v is None or a.get("verdict") == v)
        if k == "manual_claims" and ok:
            terms = [t.lower() for t in case.get("manual_gold_any", [])]
            gref = case.get("manual_gold_ref")              # v3.7.1（F20）：指定手冊與章節時，要命中該來源的章節
            if gref:
                ok = any(ref.get("manual") == gref["manual"] and (ref.get("path") or "") in gref["paths"] and
                         gref["heading_segment"] in [x.strip() for x in (ref.get("heading_path") or "").split(">")]
                         for ref in a.get("refs", []))           # v4：完整路徑＋標題層級完全相同（含其下子段落）
            else:
                ok = any(any(t in (ref.get(f) or "").lower() for t in terms)
                         for ref in a.get("refs", []) for f in ("path", "heading_path", "excerpt"))
        arts[k] = ok
    dep_ok = {}
    final_prev = A.get("route_preview") or {}
    for act, rule in deps.items():                      # v3：凍結的必要相依（不是單純「然後」）
        if rule == "pass_preview":                     # 首頁提案必須引用本案例合格的預覽
            ps = [p for p in r.get("proposals") or [] if p["action"] == act]
            dep_ok[act] = bool(ps) and all((p.get("source") or {}).get("verdict") == "pass" and
                                           (p.get("source") or {}).get("preview_ref") == final_prev.get("ref")
                                           for p in ps)
    props_ok = len(hit_t) == len(want) and not rest and all(dep_ok.values())
    correct = props_ok and all(arts.values()) and r.get("status") == case["expect_status"]
    is_prop_case = bool(want)
    return {"correct": correct, "prop_case": is_prop_case,
            "model_decided": correct and is_prop_case and bool(by) and all(b == "model" for b in by),
            "rule_assisted": correct and is_prop_case and any(b != "model" for b in by),
            "stage1_source": r.get("stage1_source"), "proposals_ok": props_ok, "expected_hit": len(hit_t),
            "expected_n": len(want),
            "extra_proposals": [[g[0][0], sorted(g[0][1]), dict(g[0][2]), g[1].get("state")] for g in rest],
            "false_open": (not is_prop_case) and bool(got),
            "t_proposal_ready_s": max(hit_t) if (is_prop_case and correct and all(t is not None for t in hit_t)) else None,
            "dependency_ok": dep_ok, "artifacts_ok": arts, "status_match": r.get("status") == case["expect_status"],
            "dirs_selected": r.get("directions"), "dirs_gold": case["gold_dirs"],
            "dirs_set_match": set(r.get("directions") or []) == set(case["gold_dirs"]),
            "dirs_raw_match": set(r.get("stage1_raw") or r.get("directions") or []) == set(case["gold_dirs"]),
            "flight_notice": "flight_notice" in A, "claimed_done_wrong": r.get("status") == "DONE" and not correct}


def p95(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = max(0, math.ceil(0.95 * len(xs)) - 1)
    return xs[k]


def run_case(case, cond, model_factory, graph, counter, work):
    svc, tools = R.build_env(work)
    idx = R.manual_index()
    n_embed_before = len(idx.calls) if idx else 0
    if idx is not None:
        tools["embed_query"] = lambda text: idx.query_vector(text) if R._INDEX["use_vector"] else None
        tools["manual_search"] = lambda text, qv, manual=None, extra=None: idx.search(
            text, use_vector=R._INDEX["use_vector"], vector=qv, require_pre=R._INDEX["use_vector"], manual=manual,
            extra=extra)
    calls = []
    model = None if cond["group"] == "B0" else model_factory(calls)
    c = M4bController(tools, model, graph, counter, ledger_cfg={"per_sentence": cond["budget"]}, steps_max=cond["steps"],
                      summary_llm=False)            # v3：整理回覆固定用模板（CODEX-APP-0406 第 1 點）
    t0 = time.monotonic()
    err = tb = None
    try:
        r = c.request(case["text"])
    except Exception as e:  # noqa: BLE001 - 首敗原樣記錄
        import traceback
        r, err, tb = {}, repr(e), traceback.format_exc()
    dt = time.monotonic() - t0
    rec = {"case": case["id"], "cond": cond["id"], "group": cond["group"], "status": r.get("status"),
           "expect_status": case["expect_status"], "calls_used": r.get("calls_used"),
           "t_pre_summary_s": r.get("t_pre_summary_s"), "elapsed_s": round(dt, 3), "reply_source": r.get("reply_source"),
           "packing_pending": (r.get("packing") or {}).get("pending"), "error": err,
           "embed_calls": idx.calls[n_embed_before:] if idx else [],
           "model_calls_sent": len(calls), "scope": case.get("scope"),
           "stage1_augmented": (r or {}).get("stage1_augmented"), "stage1_raw": (r or {}).get("stage1_raw"),
           "stage1_corrections": (r or {}).get("stage1_corrections"),
           "area_status": (r or {}).get("area_status"),
           "timing": _sum_timing(calls),
           "model_call_failures": sum(1 for x in calls if x.get("status") != 200),
           "model_call_timeouts": sum(1 for x in calls if x.get("status") == 504)}
    rec.update(score(case, r) if r else {"correct": False, "prop_case": bool(case["expect_proposals"]),
                                          "false_open": False, "t_proposal_ready_s": None})
    full = {"reply": r, "traceback": tb, "calls": calls, "dialogs": tools.dialogs}
    return rec, full


def _sum_timing(calls):
    """每案例：提示處理、生成、載入時間（秒，Ollama 回報）與重試次數、重試耗時。
    重試＝同一個決策的修正嘗試（attempt>0）；新動作、新批次、續做與重規劃的第一次呼叫都不算（CODEX-APP-0413 第 3 點）。"""
    t = {"prompt_eval_s": 0.0, "eval_s": 0.0, "load_s": 0.0, "retries": 0, "retry_wall_s": 0.0, "failed_calls": 0,
         "decisions": len({c.get("decision") for c in calls if c.get("decision") is not None})}
    for c in calls:
        tm = c.get("timing") or {}
        t["prompt_eval_s"] += (tm.get("prompt_eval_duration") or 0) / 1e9
        t["eval_s"] += (tm.get("eval_duration") or 0) / 1e9
        t["load_s"] += (tm.get("load_duration") or 0) / 1e9
        if (c.get("attempt") or 0) > 0:
            t["retries"] += 1
            t["retry_wall_s"] += c.get("latency_s") or 0
        if c.get("status") != 200:
            t["failed_calls"] += 1
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in t.items()}


def _timing(rs):
    keys = ("prompt_eval_s", "eval_s", "load_s", "retry_wall_s")
    return {k: round(sum((r.get("timing") or {}).get(k, 0) for r in rs) / len(rs), 3) for k in keys} | \
        {"retries_total": sum((r.get("timing") or {}).get("retries", 0) for r in rs)}


def summarize(recs):
    """主表（v3.5 §7 比較口徑）：正確提案完成率（分母＝應提案案例）、提案就緒 P95（只算提案全對的案例，旁列納入數）、
    每案例 LLM 呼叫次數；另列誤開率、未達終點／錯誤數、整理前與含整理的 P95，以及各組都答對的相同案例 P95。"""
    out = {}
    conds = sorted({r["cond"] for r in recs})
    by = {c: {r["case"]: r for r in recs if r["cond"] == c} for c in conds}
    common = set.intersection(*[{k for k, r in by[c].items() if r.get("t_proposal_ready_s") is not None}
                                for c in conds]) if conds else set()
    for c in conds:
        rs = list(by[c].values())
        pc = [r for r in rs if r.get("prop_case")]
        neg = [r for r in rs if not r.get("prop_case")]
        ready = [r["t_proposal_ready_s"] for r in pc if r.get("t_proposal_ready_s") is not None]
        out[c] = {"n_cases": len(rs), "n_prop_cases": len(pc),
                  "correct_prop_rate": round(sum(r["correct"] for r in pc) / len(pc), 4) if pc else None,
                  "correct_all_rate": round(sum(r["correct"] for r in rs) / len(rs), 4),
                  # v3.7.1（F23）：主表含全部應提案題；另列「兩組都支援的流程」（排除 scope＝both_not_supported 的題）
                  "correct_prop_rate_common_scope": (lambda q: f"{sum(r['correct'] for r in q)}/{len(q)}")(
                      [r for r in pc if r.get("scope") != "both_not_supported"]),
                  "model_decided_rate": round(sum(bool(r.get("model_decided")) for r in pc) / len(pc), 4) if pc else None,
                  "rule_assisted_rate": round(sum(bool(r.get("rule_assisted")) for r in pc) / len(pc), 4) if pc else None,
                  "stage1_model_share": f"{sum(1 for r in rs if r.get('stage1_source') == 'model')}/{len(rs)}",
                  "timing_s": _timing(rs),
                  "p95_proposal_ready_s": p95(ready), "p95_included": f"{len(ready)}/{len(pc)}",
                  "not_reached": len(pc) - len(ready), "case_errors": sum(1 for r in rs if r.get("error")),
                  "model_call_failures": sum(r.get("model_call_failures") or 0 for r in rs),
                  "model_call_timeouts": sum(r.get("model_call_timeouts") or 0 for r in rs),
                  "cases_with_model_timeout": sum(1 for r in rs if r.get("model_call_timeouts")),
                  "false_open_rate": round(sum(r.get("false_open", False) for r in neg) / len(neg), 4) if neg else None,
                  "p95_pre_summary_s": p95([r.get("t_pre_summary_s") for r in rs]),
                  "p95_total_s": p95([r.get("elapsed_s") for r in rs]),
                  "p95_proposal_ready_common_s": p95([by[c][k]["t_proposal_ready_s"] for k in common]),
                  "common_cases": sorted(common),
                  "llm_calls_mean": round(sum(r.get("calls_used") or 0 for r in rs) / len(rs), 3),
                  "claimed_done_wrong": sum(r.get("claimed_done_wrong", False) for r in rs),
                  # v3.7 §4 口徑
                  "calls_sent_mean": round(sum(r.get("model_calls_sent") or 0 for r in rs) / len(rs), 3),
                  "extra_in_prop_cases": sum(1 for r in pc if r.get("extra_proposals")),
                  "dir_exact_rate": f"{sum(1 for r in rs if r.get('dirs_set_match'))}/{len(rs)}",          # 補方向後
                  "dir_exact_raw_rate": f"{sum(1 for r in rs if r.get('dirs_raw_match'))}/{len(rs)}",      # 補方向前（模型或關鍵字原輸出）
                  "dir_augmented": sum(1 for r in rs if r.get("stage1_augmented")),
                  "dir_corrected": sum(1 for r in rs if r.get("stage1_corrections")),     # v3.9：程式校正次數
                  "area_fixed_cases": sum(1 for r in rs if r.get("area_status") == "ONE")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("calib", "research"), required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fake", action="store_true", help="只用假模型檢查執行器（不是 live）")
    ap.add_argument("--ollama-port", type=int, default=11555)
    ap.add_argument("--bundle", default="")
    ap.add_argument("--consent-hash8", default="")
    a = ap.parse_args(argv)
    if os.path.exists(a.out):
        raise SystemExit("輸出目錄已存在。依「只跑一次」規則不重跑；要修正請開新目錄。")
    info = {"phase": a.phase, "fake": a.fake, "start": R.now(), "group_definitions": GROUP_NOTE,
            "qa_note": R.QA_TOOL_NOTE, "consent_hash8_input": a.consent_hash8 or None}
    if not a.fake:
        if not a.bundle:
            raise SystemExit("live 需要 --bundle")
        vb = R.verify_bundle(a.bundle, a.consent_hash8)
        info["bundle_verification"] = vb
        if not vb["ok"]:
            os.makedirs(a.out)
            json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            raise SystemExit("來源包核對不通過，未啟動模型（紀錄見 RUN_INFO.json）")
    os.makedirs(a.out)
    global CASES
    CASES = CASES_BY_PHASE[a.phase]
    info["cases_file"] = os.path.basename(CASES)
    from .rag_index import QUERY_GLOSSARY_V2
    info["query_glossary_v2_sha256"] = R.hashlib.sha256(json.dumps(QUERY_GLOSSARY_V2, ensure_ascii=False,
                                                                   sort_keys=True).encode("utf-8")).hexdigest()
    cases = json.load(open(CASES, encoding="utf-8"))["cases"]
    proc = gw = None
    sampler = R.RamSampler()
    info["ram_all_ollama_baseline_kb"] = sampler.sample_all()
    recs = []
    try:
        if a.fake:
            factory = fake_model
            R.set_manual_index(R.DEFAULT_INDEX_DIR, "http://127.0.0.1:1", use_vector=False)
            graph, man = load_index(DEFAULT_ID_INDEX)
        else:
            proc = R.start_ollama(a.ollama_port, os.path.join(a.out, "ollama_serve.log"))
            info["ollama_pid"] = proc.pid
            R.check_owner(proc, a.ollama_port)
            lines = info["bundle_verification"]["lines"]
            line = next(l for l in lines if l["name"].endswith("index_v1/INDEX_MANIFEST.json"))
            idx_dir = os.path.dirname(os.path.join(R.BASE_DOC, line["name"]))
            R.set_manual_index(idx_dir, f"http://127.0.0.1:{a.ollama_port}", use_vector=True)
            lid = next(l for l in lines if l["name"].endswith("ID_INDEX_MANIFEST.json"))
            graph, man = load_index(os.path.dirname(os.path.join(R.BASE_DOC, lid["name"])))
            up = G.make_upstream("ollama", f"http://127.0.0.1:{a.ollama_port}", R.MODEL_TAG)
            gw = G.Gateway(up, os.path.join(a.out, "gateway_calls.jsonl"), budgets=GATEWAY_BUDGETS)
            info["gateway_budgets"] = GATEWAY_BUDGETS
            info["call_deadlines_s"] = DEADLINE_S
            factory = lambda log: gateway_model(gw, log)  # noqa: E731
        info["id_index"] = {"graph_sha256": man["graph_sha256"], "vectors_sha256": man["vectors_sha256"]}
        tok = TK.load_vocab()                    # v2：Gemma 4 E2B tokenizer（離線，讀本機 GGUF；manifest 雜湊不符就停）
        counter = lambda text: len(TK.encode(text, tok))  # noqa: E731
        info["token_counter"] = {"impl": "gcs_demo/gemma4_tokenizer.py（llama.cpp gemma4 規則，曾與伺服器 token ID 比對 12/12）",
                                 "blob_digest": tok["blob_digest"], "vocab_merges_types_sha256": tok["vocab_merges_types_sha256"],
                                 "n_tokens": tok["n_tokens"], "n_merges": tok["n_merges"]}
        sampler.start()
        with open(os.path.join(a.out, "results.jsonl"), "a", encoding="utf-8") as f:
            for cond in CONDITIONS[a.phase]:
                for case in cases:
                    if proc is not None:
                        R.check_owner(proc, a.ollama_port)
                    work = os.path.join(a.out, "cases", cond["id"], case["id"])
                    os.makedirs(work)
                    rec, full = run_case(case, cond, factory, graph, counter, work)
                    rec["ts"] = R.now()
                    recs.append(rec)
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    json.dump(full, open(os.path.join(work, "full.json"), "w", encoding="utf-8"),
                              ensure_ascii=False, indent=1, default=str)
    finally:
        sampler.stop.set()
        info["ram_all_ollama_peak_kb"] = sampler.peak_all_kb
        if proc is not None:
            info["ollama_stop"] = R.stop_ollama(proc, a.ollama_port)
        info["summary"] = summarize(recs) if recs else None
        info["end"] = R.now()
        if EXTRA_INFO is not None:                      # 取得目錄的這個程序自己寫附加資訊（第四輪 a4_runner 用）
            info.update(EXTRA_INFO())
        json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False,
                  indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
