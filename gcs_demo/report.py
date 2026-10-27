"""智慧任務報告：演算法先算出事實（每條有證據 ID），規則產生建議；
模型（可有可無）只負責把事實寫成白話摘要、排序建議，每句都要引用證據 ID，沒引用的丟掉。
另外輸出「下次規劃可用的耗電修正係數」，讓報告的結論回饋到下一次任務規劃。
"""
from __future__ import annotations

import json

from .energy import Vehicle, Wind, best_speed
from . import llm as llm_mod

REPORT_SCHEMA = {"required": {"summary_zh": "str", "suggestions": "list"}}


def build_facts(run, mission: dict, plan: dict, replans: list, alerts: list) -> list:
    v: Vehicle = run.v
    estimated = getattr(run, "energy_estimated", False)
    provenance = getattr(run, "provenance", None)
    facts = []

    def add(key, text, value=None):
        facts.append({"id": f"F{len(facts)+1}", "key": key, "text": text, "value": value})

    legs = [l for l in run.legs if l["pred_wh"]]
    act = sum(l["actual_wh"] for l in legs)
    pred = sum(l["pred_wh"] for l in legs)
    ratio = act / pred if pred else 1.0
    dur = run.t
    dist = 0.0
    for i in range(1, len(run.log)):
        a, b = run.log[i - 1], run.log[i]
        from .energy import haversine_m
        dist += haversine_m((a["lat"], a["lon"]), (b["lat"], b["lon"]))
    must = [t["id"] for t in mission["targets"] if t.get("priority", 1) == 1]
    all_t = [t["id"] for t in mission["targets"]]
    done = run.completed
    add("completion", f"完成目標 {len(done)}/{len(all_t)}（必要目標 {len([m for m in must if m in done])}/{len(must)}）："
        f"{'、'.join(done) or '無'}", {"done": done, "all": all_t, "must": must})
    add("duration", f"飛行 {dur/60:.1f} 分鐘、{dist/1000:.2f} 公里", {"t_s": dur, "dist_m": dist})
    energy_label = "以電量差估算耗電" if estimated else "實際耗電"
    add("energy_ratio", f"{energy_label} {act:.1f} Wh，物理模型預估 {pred:.1f} Wh，能耗是預估的 {ratio*100:.0f}%",
        {"actual_wh": act, "pred_wh": pred, "ratio": ratio, "calibration_eligible": not estimated})
    end_pct = run.pct
    add("end_battery", f"落地電量 {end_pct:.1f}%（保留門檻 {v.reserve_pct}%，起飛前預估落地 {plan['end_pct']}%）",
        {"end_pct": end_pct, "reserve": v.reserve_pct, "planned_end": plan["end_pct"]})
    worst = max(legs, key=lambda l: l["actual_wh"] / max(l["pred_wh"], 1e-6)) if legs else None
    if worst:
        add("worst_leg", f"超耗最多的航段 {worst['from']}→{worst['to']}：實際 {worst['actual_wh']} Wh／預估 "
            f"{worst['pred_wh']} Wh，平均逆風 {worst['headwind_mps']} m/s", worst)
    head = [l for l in legs if l["headwind_mps"] > 2]
    if head:
        hw_ratio = sum(l["actual_wh"] for l in head) / max(sum(l["pred_wh"] for l in head), 1e-6)
        add("headwind", f"逆風超過 2 m/s 的航段共 {len(head)} 段，耗電是預估的 {hw_ratio*100:.0f}%",
            {"n": len(head), "ratio": hw_ratio})
    winds = sorted({(r["wind_mps"], r["wind_from"]) for r in run.log})
    if len(winds) > 1:
        add("wind_change", "飛行中風況改變：" + "→".join(f"{s} m/s（從 {d:.0f}°）" for s, d in winds),
            winds)
    for r in replans:
        p = r["pick"]
        add("replan", f"第 {r['state']['t_s']/60:.1f} 分鐘因「{r['event'].get('text_zh','事件')}」重規劃，"
            f"採用 {p['choice_id'] or 'HOLD'}（{'模型選擇' if p['source']=='llm' else '規則選擇'}）",
            {"choice": p["choice_id"], "source": p["source"]})
    for a in alerts:
        add("alert", f"第 {a['t_s']/60:.1f} 分鐘告警：{a['text_zh']}", a)
    # 學到的修正係數：實際/預估 × 目前係數
    new_calib = v.calib if estimated else round(ratio, 3)  # pred_wh 已是未修正的物理模型值
    calib_text = ("SOC 差值能耗僅為估算，不據此更新耗電修正係數" if estimated else
                  f"耗電修正係數建議由 {v.calib:.2f} 更新為 {new_calib:.2f}")
    add("calib", calib_text, {"old": v.calib, "new": new_calib, "eligible": not estimated})
    w_last = Wind(winds[-1][0], winds[-1][1]) if winds else Wind()
    bs = best_speed(v, w_last, heading_deg=w_last.from_deg)
    add("best_speed", f"以本次最大風況（{w_last.speed_mps} m/s）估算，逆風最省電地速約 {bs['speed_mps']} m/s"
        f"（{bs['wh_per_km']} Wh/km），本次巡航 {plan['speed_mps']} m/s", dict(bs, cruise=plan["speed_mps"]))
    if provenance:
        add("telemetry_source", "CSV 遙測來源：" + provenance["energy_source"]
            + "；真實 QGC 匯出格式未驗證；預估為取樣軌跡未修正物理模型。"
            + (" 無電流欄，能耗以電量差估算，不用於自動校正。" if estimated else ""), provenance)
    return facts


def rule_suggestions(facts: list, vehicle: Vehicle) -> list:
    f = {x["key"]: x for x in facts if x["key"] not in ("replan", "alert")}
    out = []

    def sug(text, *keys, level="info"):
        out.append({"text_zh": text, "evidence_ids": [f[k]["id"] for k in keys if k in f], "level": level})

    r = (f["energy_ratio"]["value"]["ratio"]
         if f["energy_ratio"]["value"].get("calibration_eligible", True) else 1.0)
    if r > 1.08:
        sug(f"實際耗電比預估多 {(r-1)*100:.0f}%，下次規劃請套用新的修正係數 "
            f"{f['calib']['value']['new']:.2f}（系統可自動帶入），並檢查電池健康度與循環次數。",
            "energy_ratio", "calib", level="warn")
    elif r < 0.92:
        sug(f"實際耗電比預估少 {(1-r)*100:.0f}%，預估偏保守，可考慮套用修正係數 "
            f"{f['calib']['value']['new']:.2f} 以排入更多目標。", "energy_ratio", "calib")
    eb = f["end_battery"]["value"]
    if eb["end_pct"] < eb["reserve"]:
        sug(f"落地電量 {eb['end_pct']:.1f}% 低於保留門檻 {eb['reserve']}%，同樣的任務下次應分兩趟或減少選配目標。",
            "end_battery", level="crit")
    elif eb["end_pct"] < eb["reserve"] + 8:
        sug(f"落地電量只比保留門檻多 {eb['end_pct']-eb['reserve']:.1f}%，餘裕偏小，建議出發前預留更多電量或提高保留門檻。",
            "end_battery", level="warn")
    if f["energy_ratio"]["value"].get("calibration_eligible", True) and "headwind" in f and f["headwind"]["value"]["ratio"] > 1.1:
        sug("逆風航段是超耗主因，建議把逆風段排在電量充足的前段，回程順風；"
            "規劃時選用「最省電順序」候選。", "headwind", "worst_leg", level="warn")
    bs = f["best_speed"]["value"]["speed_mps"]
    if "wind_change" in f and abs(bs - f["best_speed"]["value"]["cruise"]) >= 1:
        sug(f"風大時把逆風段速度調到約 {bs} m/s 可降低單位距離耗電。", "best_speed", "wind_change")
    comp = f["completion"]["value"]
    missing = [t for t in comp["all"] if t not in comp["done"]]
    missing_must = [t for t in comp["must"] if t not in comp["done"]]
    done_opt = [t for t in comp["done"] if t not in comp["must"]]
    if missing_must and done_opt:
        sug(f"本次先做了選配目標（{'、'.join(done_opt)}），卻漏掉必要目標（{'、'.join(missing_must)}）；"
            "下次請選「必要目標優先」順序。", "completion", level="warn")
    if missing:
        sug(f"未完成目標：{'、'.join(missing)}，建議排入下一趟任務（可從本報告一鍵帶入規劃）。", "completion")
    if not out:
        text = ("本次能耗為電量差估算，尚不足以判定模型誤差；請補充電流紀錄再評估校正。"
                if not f["energy_ratio"]["value"].get("calibration_eligible", True) else
                "本次任務耗電與預估相符、電量餘裕充足，維持目前設定即可。")
        sug(text, "energy_ratio", "end_battery")
    return out


def make_report(run, mission, plan, replans=None, alerts=None, backend=None) -> dict:
    replans = replans or []
    alerts = alerts or []
    facts = build_facts(run, mission, plan, replans, alerts)
    sugs = rule_suggestions(facts, run.v)
    fid = {x["id"] for x in facts}
    comp = next(x for x in facts if x["key"] == "completion")
    er = next(x for x in facts if x["key"] == "energy_ratio")
    eb = next(x for x in facts if x["key"] == "end_battery")
    summary = f"{comp['text']}。{er['text']}。{eb['text']}。"
    out = {"facts": facts, "suggestions": sugs, "summary_zh": summary, "source": "rule", "llm": None,
           "next_calib": next(x for x in facts if x["key"] == "calib")["value"]["new"]}
    if getattr(run, "provenance", None):
        out["data_provenance"] = run.provenance
        out["calibration_eligible"] = not getattr(run, "energy_estimated", False)
    backend = backend or llm_mod.get_backend()
    if not backend.available():
        return out
    system = ("你是無人機任務報告助理。只能根據給定事實（facts）寫，不可新增數字。"
              "輸出 JSON：{\"summary_zh\":\"3 句內繁體中文摘要\","
              "\"suggestions\":[{\"text_zh\":\"建議\",\"evidence_ids\":[\"F1\"]}]}。"
              "建議依重要性排序，最多 5 條，每條都要引用 facts 的 id。可改寫給定的規則建議，但不可捏造。")
    user = json.dumps({"facts": [{k: x[k] for k in ("id", "text")} for x in facts],
                       "rule_suggestions": sugs}, ensure_ascii=False)
    res = backend.complete_json(system, user, REPORT_SCHEMA)
    res["prompt_hash"] = llm_mod.prompt_hash(system, user)
    out["llm"] = res
    if not res["ok"]:
        return out
    kept = []
    for s in res["data"].get("suggestions", [])[:5]:
        if not isinstance(s, dict):
            continue
        ids = [e for e in s.get("evidence_ids", []) if e in fid]
        if ids and isinstance(s.get("text_zh"), str):
            kept.append({"text_zh": s["text_zh"], "evidence_ids": ids, "level": "info"})
    if kept:
        out["suggestions"] = kept
        out["summary_zh"] = res["data"]["summary_zh"]
        out["source"] = "llm"
        out["rule_suggestions"] = sugs
    return out
