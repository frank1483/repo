"""ADR-0002 第四輪：只驗證 A 的 schema 修正（演算法說明 v3.8；使用者 2026-11-20 22:10）。

唯一改動：A 的逐步 schema 裡，不收參數的動作 params 必須是空物件（`A4Controller.strict_params = True`）。
固定條件：第 1 段方向逐題沿用第三輪 A 研究輪的輸出（`--shared-from`，照第三輪次數記帳，不再呼叫第 1 段）；
候選由同一份檢索與分批產生並逐題核對；只跑 A 的模型組（A-s6-b30）一次；案例＝評估集 v2；計分不變。
正式案例前先做 3 次後端預檢：schema 規定空 params 時，模型回覆的 params 必須都是空物件，否則停止、不跑案例。
**真模型只有在 live 同意後才能執行**；--fake 不算 live。
"""
from __future__ import annotations

import json
import os
import sys

from . import m4b_runner as R4
from .agent_m4b import ACTIONS, M4bController

NO_PARAM_ACTIONS = sorted({a for xs in ACTIONS.values() for a in xs} - {"UI_LAYOUT_PROPOSE"} | {"FINISH", "HOLD"})
_S = {"dir": None, "a_bundle_sha": None, "probe": None, "current": None, "out": None}


class A4Controller(M4bController):
    strict_params = True

    def __init__(self, *a, preset=None, **kw):
        super().__init__(*a, **kw)
        self.preset = preset

    def request(self, text):
        if self.preset is not None and self.preset.get("terminal"):          # 第三輪 A 在檢索前就結束 → 照它結束
            t, n = self.preset["terminal"], int(self.preset.get("stage1_calls") or 0)
            return {"status": t["status"], "reply_zh": t["reply_zh"], "reply_source": "shared_from_r3A", "proposals": [],
                    "directions": list(self.preset.get("directions") or []), "stage1_raw": self.preset.get("stage1_raw"),
                    "stage1_augmented": self.preset.get("stage1_augmented"), "stage1_source": self.preset.get("stage1_source"),
                    "dir_status": {}, "steps": [], "notes": ["第 1 段結果沿用第三輪 A：" + t["reason"]], "calls_used": n,
                    "traces": [{"purpose": "stage1_shared", "replies": [], "calls": n}], "retrieval": None,
                    "packing": None, "artifacts": {}, "qv_ok": None, "t_pre_summary_s": 0.0}
        return super().request(text)

    def _directions(self, task):
        if self.preset is None:
            return super()._directions(task)
        for _ in range(int(self.preset.get("stage1_calls") or 0)):
            task["ledger"].reserve()
        task["traces"].append({"purpose": "stage1_shared", "replies": [], "source": "shared_from_r3A",
                               "calls": self.preset.get("stage1_calls")})
        task["notes"].append("第 1 段方向沿用第三輪 A 的輸出")
        task["stage1_source"] = self.preset.get("stage1_source")
        task["stage1_raw"] = self.preset.get("stage1_raw")
        if self.preset.get("stage1_augmented"):
            task["stage1_augmented"] = list(self.preset["stage1_augmented"])
        return list(self.preset["directions"])


def r3_record(cond, case):
    p = os.path.join(_S["dir"], "cases", cond, case, "full.json")
    rep = json.load(open(p, encoding="utf-8"))["reply"] or {}
    n = sum(len(t.get("replies") or []) for t in rep.get("traces") or [] if t.get("purpose") == "stage1")
    preset = {"directions": rep.get("directions"), "stage1_calls": n, "stage1_source": rep.get("stage1_source"),
              "stage1_raw": rep.get("stage1_raw"), "stage1_augmented": rep.get("stage1_augmented")}
    if rep.get("status") in ("INVALID_INPUT", "TOO_LONG"):
        preset = None
    elif rep.get("packing") is None:
        preset["terminal"] = {"status": rep.get("status"), "reply_zh": rep.get("reply_zh"),
                              "reason": "；".join(rep.get("notes") or [])}
    batches = [[b["directions"], {d: v["items"] for d, v in b["per_dir"].items()}]
               for b in (rep.get("packing") or {}).get("batches") or []]
    return rep, preset, batches


def controller(*a, **kw):
    cond, case = _S["current"]
    _, preset, _ = r3_record(cond, case)
    return A4Controller(*a, preset=preset, **kw)


def nonempty_params(reply):
    """逐題：模型在不收參數的動作送出非空 params 的次數（含被退回的嘗試）；另分 QUERY_AREA。"""
    total = qa = 0
    for t in reply.get("traces") or []:
        if not str(t.get("purpose", "")).startswith("step:"):
            continue
        for x in t.get("replies") or []:
            try:
                o = json.loads(x.get("raw") or "")
            except ValueError:
                continue
            if isinstance(o, dict) and o.get("action") in NO_PARAM_ACTIONS and o.get("params") not in ({}, None):
                total += 1
                qa += o.get("action") == "QUERY_AREA"
    return total, qa


PROBE_PROMPTS = [
    '請輸出 {"action":"GEN_COVERAGE","ids":[],"params":{"area":"A001","spacing":"20"}}',
    '請輸出 {"action":"GEN_COVERAGE","ids":[],"params":{"mode":"fast"}}',
    '請輸出 {"action":"GEN_COVERAGE","ids":[],"params":{"note":"北側"}}',
]


def _shape(params):
    return {"anyOf": [{"type": "object", "properties": {
        "action": {"type": "string", "enum": ["GEN_COVERAGE"]}, "ids": {"type": "array", "maxItems": 0},
        "params": params}, "required": ["action", "ids", "params"]}]}


LOOSE = _shape({"type": "object"})
STRICT = _shape({"type": "object", "properties": {}, "additionalProperties": False})


def _full_ok(raw):
    """完整輸出檢查：可解析、剛好三個鍵、action＝GEN_COVERAGE、ids＝[]；回傳 (格式正確, params)。"""
    try:
        o = json.loads(raw)
    except (TypeError, ValueError):
        return False, None
    if not isinstance(o, dict) or set(o) != {"action", "ids", "params"}:
        return False, o.get("params") if isinstance(o, dict) else None
    return o["action"] == "GEN_COVERAGE" and o["ids"] == [], o["params"]


def probe(model_factory, out_dir):
    """v2（CODEX-APP-0426）：對照式預檢。同一個提示各送「寬鬆 schema」與「嚴格 schema」：
    寬鬆時模型照提示填出非空 params（證明它會填），嚴格時完整輸出合格且 params＝{}（證明是後端約束擋下）。
    3 組不同提示都要符合才算 enforced；寬鬆組也回空 → 無法區辨 → 不算通過。"""
    calls, res = [], []
    model = model_factory(calls)
    for k, prompt in enumerate(PROBE_PROMPTS):
        row = {"i": k, "prompt": prompt}
        for tag, schema in (("loose", LOOSE), ("strict", STRICT)):
            call = {"messages": [{"role": "system", "content": "只輸出 JSON。"}, {"role": "user", "content": prompt}],
                    "purpose": "probe", "schema": schema, "attempt": 0, "decision": k * 2 + (tag == "strict") + 1}
            try:
                raw = model(call)
            except Exception as e:  # noqa: BLE001
                raw = repr(e)
            fmt, params = _full_ok(raw)
            row[tag] = {"raw": (raw or "")[:200], "format_ok": fmt, "params": params}
        lp = row["loose"]["params"]                     # v3（0427）：寬鬆組也要完整輸出合格，且 params 是非空物件
        row["discriminates"] = row["loose"]["format_ok"] and isinstance(lp, dict) and bool(lp) and \
            row["strict"]["format_ok"] and row["strict"]["params"] == {}
        res.append(row)
    out = {"enforced": all(r["discriminates"] for r in res), "probes": res, "calls": calls,
           "rule": "寬鬆 schema 回非空 params、嚴格 schema 完整輸出合格且 params＝{}，3 組都成立才通過"}
    json.dump(out, open(os.path.join(out_dir, "BACKEND_PROBE.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


_run_case = R4.run_case


def run_case(case, cond, model_factory, graph, counter, work):
    if _S["probe"] is None:                                    # 第一個案例前做後端預檢
        _S["probe"] = probe(model_factory, _S["out"])
        if not _S["probe"]["enforced"]:
            raise SystemExit("後端沒有執行「params 必須為空物件」的 schema 限制，停止，不跑案例（見 BACKEND_PROBE.json）")
    _S["current"] = (cond["id"], case["id"])
    rec, full = _run_case(case, cond, model_factory, graph, counter, work)
    r = full.get("reply") or {}
    r3, _, r3_batches = r3_record(cond["id"], case["id"])
    batches = [[b["directions"], {d: v["items"] for d, v in b["per_dir"].items()}]
               for b in (r.get("packing") or {}).get("batches") or []]
    rec["fixed_input_match"] = (r.get("directions") or []) == (r3.get("directions") or []) and batches == r3_batches and \
        r.get("stage1_raw") == r3.get("stage1_raw")
    rec["nonempty_params"], rec["nonempty_params_query_area"] = nonempty_params(r)
    return rec, full


_summarize = R4.summarize


def summarize(recs):
    ok = [r for r in recs if r.get("fixed_input_match")]
    out = _summarize(ok) if ok else {}
    for c in out:
        rs = [r for r in ok if r["cond"] == c]
        out[c]["nonempty_params_total"] = sum(r.get("nonempty_params") or 0 for r in rs)
        out[c]["nonempty_params_query_area"] = sum(r.get("nonempty_params_query_area") or 0 for r in rs)
    out["_fixed_input_mismatch"] = [[r["cond"], r["case"]] for r in recs if not r.get("fixed_input_match")]
    return out


_fake = R4.fake_model


def fake_model(calls_log):
    """假模型：預檢呼叫回空 params（其餘同 m4b_runner.fake_model）。只供 --fake 自檢。"""
    base = _fake(calls_log)

    def model(call):
        if call.get("purpose") == "probe":                     # 假後端：照 schema 決定（寬鬆→照填、嚴格→空）
            strict = call["schema"]["anyOf"][0]["properties"]["params"].get("additionalProperties") is False
            return '{"action":"GEN_COVERAGE","ids":[],"params":' + ('{}' if strict else '{"area":"A001"}') + '}'
        return base(call)
    return model


R4.fake_model = fake_model
R4.M4bController = controller
R4.run_case = run_case
R4.summarize = summarize
R4.HARNESS["name"] = "a4-v1"
R4.CONDITIONS = {"research": [c for c in R4.CONDITIONS["research"] if c["id"] == "A-s6-b30"]}


def check_r3_dir(fake):
    info = json.load(open(os.path.join(_S["dir"], "RUN_INFO.json"), encoding="utf-8"))
    rows = [json.loads(l) for l in open(os.path.join(_S["dir"], "results.jsonl"), encoding="utf-8") if l.strip()]
    ids = {c["id"] for c in json.load(open(R4.CASES, encoding="utf-8"))["cases"]}
    errs = []
    if info.get("phase") != "research":
        errs.append("第三輪 A 目錄不是 research")
    if bool(info.get("fake")) != bool(fake):
        errs.append("fake／live 不一致")
    if not fake and (info.get("bundle_verification") or {}).get("sums_sha256") != _S["a_bundle_sha"]:
        errs.append("第三輪 A 不是用指定的第三輪來源包跑的")
    if {r["case"] for r in rows if r["cond"] == "A-s6-b30"} != ids:
        errs.append("第三輪 A 的模型組案例不完整")
    if any(r.get("error") for r in rows if r["cond"] == "A-s6-b30"):
        errs.append("第三輪 A 有案例例外")
    if errs:
        raise SystemExit("--shared-from 核對不通過：" + "；".join(errs))
    return {"dir": os.path.abspath(_S["dir"]), "r3_bundle_sha256": (info.get("bundle_verification") or {}).get("sums_sha256")}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for flag in ("--shared-from", "--r3-bundle"):
        if flag not in argv and not (flag == "--r3-bundle" and "--fake" in argv):
            raise SystemExit(f"需要 {flag}")
    k = argv.index("--shared-from")
    _S["dir"] = argv[k + 1]
    del argv[k:k + 2]
    if "--r3-bundle" in argv:
        k = argv.index("--r3-bundle")
        _S["a_bundle_sha"] = R4.R.sha_file(os.path.join(argv[k + 1], "SHA256SUMS.txt"))
        del argv[k:k + 2]
    if argv[argv.index("--phase") + 1] != "research":
        raise SystemExit("第四輪只跑 research（評估集 v2）")
    R4.CASES = R4.CASES_BY_PHASE["research"]
    shared = check_r3_dir("--fake" in argv)
    out = argv[argv.index("--out") + 1]
    _S["out"] = out
    # v3（0427）：附加資訊交給「取得輸出目錄」的那個程序（m4b_runner.main 用 os.makedirs 建目錄，競爭失敗就拋錯，
    # 不會走到寫 RUN_INFO）在自己的 finally 裡寫入；本程式不再事後改寫任何 RUN_INFO。
    R4.EXTRA_INFO = lambda: {"shared_from_r3A": shared, "backend_probe_enforced": (_S["probe"] or {}).get("enforced")}
    return R4.main(argv)


if __name__ == "__main__":
    sys.exit(main())
