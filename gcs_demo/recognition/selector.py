"""場域 → 辨識模型候選（進模型前由程式決策）。

1. 硬性過濾（任一不過就不是候選，原因要顯示）：
   F1 已安裝（manifest 合法、檔案存在、SHA256 相符、driver 可用）
   F2 模型類別（經別名對應）涵蓋場域的全部必要類別
   F3 本機量測延遲 ≤ 場域上限；沒量測過的放行但標「未量測」並扣分
2. 評分（越高越好）：
   score = 2.0 × 選配類別涵蓋比例 + 1.0 × (1 − 延遲/上限) + 0.5 × 場域提示相符 − 0.5 × 未量測
   （選配類別為空時涵蓋比例記 1；未量測時延遲項記 0）
3. 規則選擇：分數最高；同分取延遲較低，再同取 id 字母序。
   遲滯：目前模型若也是候選且分數 ≥ 最高分 − 0.1，就維持不換（避免來回切）。
4. 沒有候選 → HOLD：保留目前模型，列出缺什麼。
5. 有模型後端時，模型只能在候選 id 內選或 HOLD；不合法退回規則（共用 llm_contract）。
"""
from __future__ import annotations

import json

W_PREF, W_LAT, W_HINT, PEN_UNMEASURED, HYSTERESIS = 2.0, 1.0, 0.5, 0.5, 0.1


def evaluate(domain, rows, alias, current_model=None, class_zh=None):
    zh = class_zh or {}
    rec = domain["recognition"]
    req, pref, max_lat = rec["required_classes"], rec.get("preferred_classes", []), rec["max_latency_ms"]
    cands, rejected = [], []
    for row in rows:
        m = row["manifest"]
        reasons = []
        if not row["installed"]:
            reasons += row["problems"]
        classes = {alias.get(c, c) for c in m.get("classes", [])}
        miss = [c for c in req if c not in classes]
        if miss:
            reasons.append("缺必要類別：" + "、".join(zh.get(c, c) for c in miss))
        lat = row.get("latency_ms")
        if lat is not None and lat > max_lat:
            reasons.append(f"延遲 {lat} ms 超過上限 {max_lat} ms")
        if reasons:
            rejected.append({"id": row["id"], "name_zh": m.get("name_zh", row["id"]), "reasons": reasons})
            continue
        pref_cov = (sum(c in classes for c in pref) / len(pref)) if pref else 1.0
        lat_term = (1 - lat / max_lat) if lat is not None else 0.0
        hint = 1.0 if domain["id"] in m.get("domain_hint", []) else 0.0
        unmeasured = lat is None
        score = W_PREF * pref_cov + W_LAT * lat_term + W_HINT * hint - (PEN_UNMEASURED if unmeasured else 0)
        cands.append({"id": row["id"], "name_zh": m["name_zh"], "runtime": m["runtime"],
                      "classes": sorted(classes), "latency_ms": lat, "unmeasured": unmeasured,
                      "pref_coverage": round(pref_cov, 3), "domain_hint": bool(hint),
                      "score": round(score, 3)})
    cands.sort(key=lambda c: (-c["score"], c["latency_ms"] if c["latency_ms"] is not None else 1e9, c["id"]))
    for i, c in enumerate(cands):
        c["cid"] = f"M{i + 1}"
    if not cands:
        return {"decision": "HOLD", "choice": None, "candidates": [], "rejected": rejected,
                "reason_zh": "沒有已安裝模型符合此場域的必要類別與延遲，維持目前模型。"}
    best = cands[0]
    cur = next((c for c in cands if c["id"] == current_model), None)
    if cur and cur["score"] >= best["score"] - HYSTERESIS:
        return {"decision": "KEEP", "choice": cur["id"], "candidates": cands, "rejected": rejected,
                "reason_zh": f"目前模型已符合此場域（分數 {cur['score']}，最高 {best['score']}），不切換。"}
    return {"decision": "SELECT", "choice": best["id"], "candidates": cands, "rejected": rejected,
            "reason_zh": f"規則選擇：{best['name_zh']} 分數最高（{best['score']}）。"}


SCHEMA = {"required": {"decision": "str", "choice_id": "str", "reason_zh": "str", "evidence_ids": "list"}}


def llm_pick(backend, domain, result):
    """模型只在候選 cid 內選；回傳 (model_id, source, reason, 紀錄)。沒後端或不合法 → 規則。"""
    rule = (result["choice"], "rule", result["reason_zh"], None)
    if result["decision"] != "SELECT" or backend is None or not backend.available():
        return rule
    ids = {c["cid"]: c["id"] for c in result["candidates"]}
    evidence = [{"id": f"E{i + 1}", "text": f"{c['cid']} 分數 {c['score']}，延遲 {c['latency_ms']} ms，"
                 f"選配類別涵蓋 {c['pref_coverage']}"} for i, c in enumerate(result["candidates"])]
    system = ("你是無人機地面站的辨識模型選擇助理。只能從候選 cid 中選一個，或回 HOLD。只輸出 JSON："
              '{"decision":"SELECT|HOLD","choice_id":"<cid>","reason_zh":"一句繁體中文","evidence_ids":["E1"]}')
    user = json.dumps({"domain": domain["name_zh"], "candidates": result["candidates"], "evidence": evidence},
                      ensure_ascii=False)
    res = backend.complete_json(system, user, SCHEMA)
    if not res.get("ok"):
        return rule[:3] + (res,)
    d = res["data"]
    if str(d.get("decision", "")).upper() == "HOLD":
        return None, "llm", d.get("reason_zh", ""), res
    if d.get("choice_id") not in ids:
        return (rule[0], "rule", rule[2] + "（模型回了不存在的候選，已退回規則）", res)
    return ids[d["choice_id"]], "llm", d.get("reason_zh", ""), res
