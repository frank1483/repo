"""把正式 UI 規劃頁送來的航點整理成 planner 用的任務（/api/plan 的 "mission" 欄位）。

輸入（面板從 missionController 讀出）：
  {"name": 選填, "home": {"lat","lon"}, "cruise_alt_m": 選填, "speed_mps": 選填,
   "targets": [{"id","lat","lon","alt"(選填),"required"(布林，預設 true)}],
   "no_fly": 選填 [{"id","lat","lon","radius_m"}]}
不合規格就丟 ValueError（訊息是給操作員看的中文），伺服器回 {"ok": false, "reason_zh": ...}。
距離上限 20 km 對應功能規格「20 km 範圍內」；目標數上限 50 是為了讓候選計算維持在幾秒內。
"""
from __future__ import annotations

import math

from .energy import haversine_m

MAX_TARGETS = 50
MAX_RANGE_M = 20000.0
MAX_ALT_M = 120.0


def _num(v, what, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{what}不合理：{v!r}（應在 {lo}～{hi}）")
    return float(v)


def _point(p, what):
    if not isinstance(p, dict):
        raise ValueError(f"{what}格式錯誤")
    return _num(p.get("lat"), what + "緯度", -90, 90), _num(p.get("lon"), what + "經度", -180, 180)


def mission_from_body(m) -> dict:
    if not isinstance(m, dict):
        raise ValueError("任務格式錯誤")
    hlat, hlon = _point(m.get("home"), "起降點")
    tg = m.get("targets")
    if not isinstance(tg, list) or not 1 <= len(tg) <= MAX_TARGETS:
        raise ValueError(f"航點數要在 1～{MAX_TARGETS} 個之間")
    alt = _num(m.get("cruise_alt_m", 50), "巡航高度", 5, MAX_ALT_M)
    speed = _num(m.get("speed_mps", 8.0), "巡航速度", 1, 30)
    seen, targets = set(), []
    for i, t in enumerate(tg, start=1):
        what = f"第 {i} 個航點"
        lat, lon = _point(t, what)
        tid = t.get("id")
        if not isinstance(tid, str) or not tid or len(tid) > 16 or tid == "H" or tid in seen:
            raise ValueError(f"{what}的編號不合法或重複：{tid!r}")
        seen.add(tid)
        d = haversine_m((hlat, hlon), (lat, lon))
        if d > MAX_RANGE_M:
            raise ValueError(f"{what}（{tid}）離起降點 {d / 1000:.1f} km，超過 20 km")
        req = t.get("required", True)
        if not isinstance(req, bool):
            raise ValueError(f"{what}的必要／選配設定錯誤")
        out = {"id": tid, "lat": lat, "lon": lon, "priority": 1 if req else 2}
        if t.get("alt") is not None:
            out["alt"] = _num(t["alt"], what + "高度", 0, MAX_ALT_M)
        targets.append(out)
    no_fly = []
    for j, z in enumerate(m.get("no_fly") or [], start=1):
        lat, lon = _point(z, f"第 {j} 個禁航區")
        no_fly.append({"id": str(z.get("id") or f"NFZ{j}"), "lat": lat, "lon": lon,
                       "radius_m": _num(z.get("radius_m"), f"第 {j} 個禁航區半徑", 1, MAX_RANGE_M)})
    name = m.get("name") if isinstance(m.get("name"), str) else "目前任務"
    return {"name": name[:60], "home": {"id": "H", "lat": hlat, "lon": hlon}, "cruise_alt_m": alt,
            "speed_mps": speed, "targets": targets, "no_fly": no_fly, "limits": {"max_altitude_m": MAX_ALT_M},
            "source": "ui"}
