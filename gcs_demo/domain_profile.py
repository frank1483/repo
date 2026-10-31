"""共用場域設定檔（功能3 辨識模型切換與功能4 情境式 UI 共用同一份）。草案 v0。

一個場域一個 JSON：gcs_demo/domains/<id>.json。只用標準庫。
文字指令 → 場域：程式用關鍵字比對決定；平手或沒對到就反問（CLARIFY），不交給模型猜。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

DOMAIN_DIR = Path(__file__).parent / "domains"
CLASSES_FILE = DOMAIN_DIR / "classes.json"


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_classes(path=CLASSES_FILE):
    """回傳 {alias或標準id: 標準id} 與 {標準id: 中文名}。"""
    data = _load_json(path)["classes"]
    alias, zh = {}, {}
    for cid, info in data.items():
        alias[cid] = cid
        zh[cid] = info.get("zh", cid)
        for a in info.get("aliases", []):
            if a in alias and alias[a] != cid:
                raise ValueError(f"classes: alias {a} 對到兩個類別")
            alias[a] = cid
    return alias, zh


def validate_domain(d, alias):
    if not isinstance(d, dict):
        raise ValueError("domain: object required")
    for key in ("id", "name_zh", "ui_template"):
        if not isinstance(d.get(key), str) or not d[key].strip():
            raise ValueError(f"domain.{key}: 非空字串")
    kws = d.get("keywords_zh")
    if not isinstance(kws, list) or not kws or not all(isinstance(k, str) and k for k in kws):
        raise ValueError(f"domain {d['id']}.keywords_zh: 至少一個關鍵字")
    r = d.get("recognition")
    if not isinstance(r, dict):
        raise ValueError(f"domain {d['id']}.recognition: object required")
    req = r.get("required_classes")
    if not isinstance(req, list) or not req:
        raise ValueError(f"domain {d['id']}: required_classes 至少一個")
    for c in req + list(r.get("preferred_classes", [])):
        if c not in alias or alias[c] != c:
            raise ValueError(f"domain {d['id']}: 類別 {c} 不在 classes.json 的標準類別")
    lat = r.get("max_latency_ms")
    if isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(lat) or lat <= 0:
        raise ValueError(f"domain {d['id']}.max_latency_ms: 正數")
    th = r.get("conf_threshold")
    if isinstance(th, bool) or not isinstance(th, (int, float)) or not 0 < th < 1:
        raise ValueError(f"domain {d['id']}.conf_threshold: 0 到 1 之間")
    return d


def load_domains(directory=DOMAIN_DIR):
    alias, _ = load_classes(Path(directory) / "classes.json")
    out = {}
    for p in sorted(Path(directory).glob("*.json")):
        if p.name == "classes.json":
            continue
        d = validate_domain(_load_json(p), alias)
        if d["id"] in out:
            raise ValueError(f"domain id 重複：{d['id']}")
        out[d["id"]] = d
    if not out:
        raise ValueError("沒有任何場域設定檔")
    return out


def resolve_domain(text, domains):
    """文字指令 → 場域。

    分數 = 指令中出現的關鍵字長度總和（同一段文字不重複計分：較長的關鍵字先比對並遮掉）。
    場域中文名完全出現時另加 10 分（明講場域名最可信）。
    最高分唯一且 > 0 → SELECT；全為 0 或最高分平手 → CLARIFY，列出可選場域。
    """
    text = text or ""
    scores, evidence = {}, {}
    for did, d in domains.items():
        masked = text
        hits = []
        for kw in sorted(set(d["keywords_zh"]), key=len, reverse=True):
            if kw in masked:
                hits.append(kw)
                masked = masked.replace(kw, "\0" * len(kw))
        s = sum(len(k) for k in hits)
        if d["name_zh"] in text:
            s += 10
        scores[did] = s
        evidence[did] = hits
    best = max(scores.values())
    top = sorted(did for did, s in scores.items() if s == best)
    options = [{"id": did, "name_zh": domains[did]["name_zh"]} for did in sorted(domains)]
    if best <= 0:
        return {"decision": "CLARIFY", "domain_id": None, "scores": scores, "hits": evidence,
                "question_zh": "請問這次任務屬於哪個場域？", "options": options}
    if len(top) > 1:
        names = "、".join(domains[t]["name_zh"] for t in top)
        return {"decision": "CLARIFY", "domain_id": None, "scores": scores, "hits": evidence,
                "question_zh": f"指令同時像「{names}」，請指定一個場域。",
                "options": [o for o in options if o["id"] in top]}
    return {"decision": "SELECT", "domain_id": top[0], "scores": scores, "hits": evidence}
