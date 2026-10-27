"""多旋翼能耗估算（任務規劃、智慧告警、任務報告共用同一套數字）。

模型：P(v_air) = P_hover + 0.5·rho·CdA·v_air^3 / eta，爬升另加 m·g·Δh / eta。
v_air 是對空速度：地速向量減掉風向量。calib 是從過去任務學到的修正係數（實際/預估）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict

R_EARTH = 6371000.0
RHO = 1.225
G = 9.81


def haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * R_EARTH * math.asin(math.sqrt(h))


def bearing_rad(a, b) -> float:
    """由 a 到 b 的航向（北=0，順時針）。"""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.atan2(y, x)


@dataclass
class Vehicle:
    vehicle_id: str = "UAV-01"
    mass_kg: float = 2.0
    battery_wh: float = 90.0
    usable_frac: float = 0.9        # 電池可用比例
    p_hover_w: float = 190.0
    cda_m2: float = 0.12
    eta: float = 0.7
    cruise_mps: float = 8.0
    max_mps: float = 15.0
    reserve_pct: float = 20.0       # 落地時至少要剩的電量
    calib: float = 1.0              # 歷史任務學到的「實際/預估」係數

    def to_dict(self):
        return asdict(self)


@dataclass
class Wind:
    speed_mps: float = 0.0
    from_deg: float = 0.0           # 風從哪個方向吹來（氣象慣例，北=0）

    def vector(self):
        # 吹向的方向 = from + 180
        to = math.radians(self.from_deg + 180.0)
        return (self.speed_mps * math.sin(to), self.speed_mps * math.cos(to))  # (east, north)


def power_w(v: Vehicle, v_air: float) -> float:
    return v.p_hover_w + 0.5 * RHO * v.cda_m2 * v_air ** 3 / v.eta


def leg_estimate(v: Vehicle, a, b, alt_a: float, alt_b: float, ground_mps: float, wind: Wind):
    """回傳一段航線的距離、時間、能耗 Wh、逆風分量。"""
    dist = haversine_m(a, b)
    if dist < 0.5:
        t = 0.0
        v_air = 0.0
        head = 0.0
    else:
        brg = bearing_rad(a, b)
        ge, gn = ground_mps * math.sin(brg), ground_mps * math.cos(brg)
        we, wn = wind.vector()
        ae, an = ge - we, gn - wn
        v_air = math.hypot(ae, an)
        head = -(we * math.sin(brg) + wn * math.cos(brg))  # 正值 = 逆風
        t = dist / ground_mps
    e_j = power_w(v, v_air) * t
    climb = max(0.0, alt_b - alt_a)
    e_j += v.mass_kg * G * climb / v.eta
    t += climb / 3.0 if climb > 0 else max(0.0, alt_a - alt_b) / 2.0
    e_j += v.p_hover_w * (climb / 3.0 if climb > 0 else max(0.0, alt_a - alt_b) / 2.0)
    wh = e_j / 3600.0 * v.calib
    return {"dist_m": dist, "time_s": t, "energy_wh": wh, "v_air": v_air, "headwind_mps": head}


def route_estimate(v: Vehicle, points: list, ground_mps: float, wind: Wind,
                   start_pct: float = 100.0, hover_s_per_wp: float = 5.0):
    """points：[{id, lat, lon, alt}]，第一個是起點。回傳整條航線估算與每段明細。"""
    legs = []
    total_wh = 0.0
    total_t = 0.0
    total_d = 0.0
    cap = v.battery_wh * v.usable_frac
    pct = start_pct
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        est = leg_estimate(v, (a["lat"], a["lon"]), (b["lat"], b["lon"]),
                           a.get("alt", 0), b.get("alt", 0), ground_mps, wind)
        hover = hover_s_per_wp if b.get("kind") == "target" else 0.0
        est["energy_wh"] += v.p_hover_w * hover / 3600.0 * v.calib
        est["time_s"] += hover
        pct -= est["energy_wh"] / cap * 100.0
        est.update({"from": a["id"], "to": b["id"], "pct_after": pct})
        legs.append(est)
        total_wh += est["energy_wh"]
        total_t += est["time_s"]
        total_d += est["dist_m"]
    return {"dist_m": total_d, "time_s": total_t, "energy_wh": total_wh,
            "end_pct": pct, "used_pct": start_pct - pct,
            "margin_pct": pct - v.reserve_pct, "feasible": pct >= v.reserve_pct, "legs": legs}


def best_speed(v: Vehicle, wind: Wind, heading_deg: float = 0.0, lo=4.0, hi=None):
    """單位距離能耗最低的地速（給報告建議用）。"""
    hi = hi or v.max_mps
    a = (0.0, 0.0)
    b = (0.001 * math.cos(math.radians(heading_deg)), 0.001 * math.sin(math.radians(heading_deg)))
    best = None
    s = lo
    while s <= hi + 1e-9:
        e = leg_estimate(v, a, b, 0, 0, s, wind)
        per_km = e["energy_wh"] / max(e["dist_m"], 1) * 1000
        if best is None or per_km < best[1]:
            best = (round(s, 1), per_km)
        s += 0.5
    return {"speed_mps": best[0], "wh_per_km": round(best[1], 2)}


# ---- 給智慧告警串的共用入口（單位 Wh、m、s；風向＝風吹來的方向，度） ----

def estimate_route_energy(route: list, vehicle: Vehicle, wind: Wind, ground_mps: float = None,
                          start_pct: float = 100.0) -> dict:
    """route：[{id?, lat, lon, alt}]。回傳總和與每段 {from,to,dist_m,time_s,energy_wh,pct_after}。"""
    pts = [dict(p, id=p.get("id", f"P{i}")) for i, p in enumerate(route)]
    return route_estimate(vehicle, pts, ground_mps or vehicle.cruise_mps, wind, start_pct,
                          hover_s_per_wp=0.0)


def rtl_energy(pos: dict, home: dict, vehicle: Vehicle, wind: Wind, ground_mps: float = None) -> dict:
    """從任意點直飛回 home 並下降落地的能耗。"""
    p = dict(pos, id="here")
    h = dict(home, id="home", alt=0)
    return estimate_route_energy([p, h], vehicle, wind, ground_mps)
