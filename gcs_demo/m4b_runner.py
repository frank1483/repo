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
from .id_graph import load_index

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.path.join(HERE, "m4b_cases_v1.json")
DEFAULT_ID_INDEX = os.path.join(R.BASE_DOC, "adr0002_rag_v1", "id_index_v1")
CONDITIONS = {
    "calib": [{"id": "A-s6-b30", "group": "A", "steps": 6, "budget": 30}],
    "research": [{"id": "B0", "group": "B0", "steps": 6, "budget": 0},
                 {"id": "A-s6-b30", "group": "A", "steps": 6, "budget": 30}],
}
GROUP_NOTE = {"B0": "規則：方向用關鍵字表、每步用規則腳本，零次 LLM 呼叫；查詢向量仍算 1 次",
              "A": "方案 A：模型排方向並逐步選動作（每步只看當前方向的候選）"}
FEATURE = {"stage1": "agent_dir", "summary": "agent_resume"}


def gateway_model(gw, calls_log):
    def model(call):
        purpose = call.get("purpose", "")
        feature = FEATURE.get(purpose, "agent_step")
        t0 = time.monotonic()
        st, body = gw.submit(feature, {"messages": call["messages"], "max_tokens": 256 if purpose == "summary" else 96},
                             harness="m4b-v1")
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


def score(case, r):
    want = [(p["action"], frozenset(p["ids"]), frozenset(p["values"])) for p in case["expect_proposals"]]
    got = [(p["action"], frozenset(p["ids"]), frozenset(p["params"].values())) for p in r.get("proposals") or []]
    rest = list(got)
    hit = 0
    for w in want:
        if w in rest:
            rest.remove(w)
            hit += 1
    A = r.get("artifacts") or {}
    arts = {}
    for k, v in case["expect_artifacts"].items():
        a = A.get(k)
        ok = a is not None and (v is None or a.get("verdict") == v)
        if k == "manual_claims" and ok:
            terms = [t.lower() for t in case.get("manual_gold_any", [])]
            ok = any(any(t in (ref.get(f) or "").lower() for t in terms)
                     for ref in a.get("refs", []) for f in ("path", "heading_path", "excerpt"))
        arts[k] = ok
    props_ok = hit == len(want) and not rest
    correct = props_ok and all(arts.values()) and r.get("status") == case["expect_status"]
    return {"correct": correct, "proposals_ok": props_ok, "expected_hit": hit, "expected_n": len(want),
            "extra_proposals": [[a, sorted(i), sorted(v)] for a, i, v in rest], "artifacts_ok": arts,
            "status_match": r.get("status") == case["expect_status"],
            "dirs_selected": r.get("directions"), "dirs_gold": case["gold_dirs"],
            "dirs_set_match": set(r.get("directions") or []) == set(case["gold_dirs"]),
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
        tools["manual_search"] = lambda text, qv: idx.search(text, use_vector=R._INDEX["use_vector"], vector=qv,
                                                            require_pre=R._INDEX["use_vector"])
    calls = []
    model = None if cond["group"] == "B0" else model_factory(calls)
    c = M4bController(tools, model, graph, counter, ledger_cfg={"per_sentence": cond["budget"]}, steps_max=cond["steps"],
                      summary_llm=cond["group"] != "B0")
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
           "t_ready_s": r.get("t_pre_summary_s"), "elapsed_s": round(dt, 3), "reply_source": r.get("reply_source"),
           "packing_pending": (r.get("packing") or {}).get("pending"), "error": err,
           "embed_calls": idx.calls[n_embed_before:] if idx else []}
    rec.update(score(case, r) if r else {"correct": False})
    full = {"reply": r, "traceback": tb, "calls": calls, "dialogs": tools.dialogs}
    return rec, full


def summarize(recs):
    out = {}
    for cond in sorted({r["cond"] for r in recs}):
        rs = [r for r in recs if r["cond"] == cond]
        out[cond] = {"n": len(rs), "correct_rate": round(sum(r["correct"] for r in rs) / len(rs), 4),
                     "p95_ready_s": p95([r["t_ready_s"] for r in rs]), "p95_total_s": p95([r["elapsed_s"] for r in rs]),
                     "llm_calls_mean": round(sum(r["calls_used"] or 0 for r in rs) / len(rs), 3),
                     "errors": sum(1 for r in rs if r["error"]), "claimed_done_wrong": sum(r.get("claimed_done_wrong", 0) for r in rs)}
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
            counter = len                        # --fake：字數當 token（live 用 Gemma 4 tokenizer 的 prompt_eval_count 記錄）
            info["token_counter"] = "len(text)（fake）"
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
            counter = len                        # 待定：Gemma 4 tokenizer（見來源包 MANIFEST 說明）
            info["token_counter"] = "len(text)；live 另記每次呼叫的 prompt_eval_count"
            up = G.make_upstream("ollama", f"http://127.0.0.1:{a.ollama_port}", R.MODEL_TAG)
            gw = G.Gateway(up, os.path.join(a.out, "gateway_calls.jsonl"))
            factory = lambda log: gateway_model(gw, log)  # noqa: E731
        info["id_index"] = {"graph_sha256": man["graph_sha256"], "vectors_sha256": man["vectors_sha256"]}
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
        json.dump(info, open(os.path.join(a.out, "RUN_INFO.json"), "w", encoding="utf-8"), ensure_ascii=False,
                  indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
