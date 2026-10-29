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

    airframe_profile: dict | None = None  # T5a: optional; old positional arguments unchanged

    @property
    def type(self):
        return self.airframe_profile["type"] if self.airframe_profile else "multirotor"

    def to_dict(self):
        result = asdict(self)
        if self.airframe_profile is None:
            del result["airframe_profile"]  # preserve legacy version/hash payloads
        return result


# T5a: public helpers, inserted before Wind in energy.py by prepare.cjs.
def load_airframe(path_or_id) -> Vehicle:
    """Load local JSON or an id under gcs_demo/airframes; no network access."""
    from .airframe_profile import read_profile
    p = read_profile(path_or_id)
    mc = (p["power"] if p["type"] == "multirotor" else p["power"]["mc"]
          if p["type"] == "vtol_hybrid" else {"p_hover_w": 0.0, "cda_m2": 0.0, "eta": 1.0})
    return Vehicle(vehicle_id=p["id"], mass_kg=p["mass_kg"], battery_wh=p["battery"]["wh"],
                   usable_frac=p["battery"]["usable_frac"], p_hover_w=mc["p_hover_w"],
                   cda_m2=mc["cda_m2"], eta=mc["eta"], cruise_mps=p["limits"]["cruise_mps"],
                   max_mps=p["limits"]["max_airspeed_mps"], reserve_pct=p["limits"]["reserve_pct"],
                   calib=p["calib"], airframe_profile=p)


def speed_range(vehicle: Vehicle, bank_deg=0.0):
    """Airspeed envelope in m/s; not a ground-speed interval in wind."""
    from .airframe_profile import profile_speed_range
    if vehicle.airframe_profile is None:
        return 0.0, vehicle.max_mps
    return profile_speed_range(vehicle.airframe_profile, bank_deg)


def turn_geometry(vehicle: Vehicle, v_air, bank_deg=None, radius_m=None):
    from .airframe_profile import profile_turn_geometry
    if vehicle.airframe_profile is None:
        raise ValueError("turn geometry is defined only for fixed-wing flight")
    return profile_turn_geometry(vehicle.airframe_profile, v_air, bank_deg, radius_m)


def _require_legacy_route(vehicle):
    if vehicle.type != "multirotor":
        raise NotImplementedError("T5b route/transition/bounds integration pending; fixed-wing/hybrid routes unavailable")


@dataclass
class Wind:
    speed_mps: float = 0.0
    from_deg: float = 0.0           # 風從哪個方向吹來（氣象慣例，北=0）

    def vector(self):
        # 吹向的方向 = from + 180
        to = math.radians(self.from_deg + 180.0)
        return (self.speed_mps * math.sin(to), self.speed_mps * math.cos(to))  # (east, north)


def power_w(v: Vehicle, v_air: float, mode=None, bank_deg=0.0,
            climb_mps=0.0, advance_ratio=None) -> float:
    if v.airframe_profile is None and mode is None and bank_deg == 0 and climb_mps == 0 and advance_ratio is None:
        return v.p_hover_w + 0.5 * RHO * v.cda_m2 * v_air ** 3 / v.eta
    from .airframe_profile import profile_power_w
    p = v.airframe_profile or {"type": "multirotor", "power": {}}
    if v.type == "multirotor":
        p = {**p, "power": {**p["power"], "p_hover_w": v.p_hover_w, "cda_m2": v.cda_m2, "eta": v.eta}}
    return profile_power_w(p, v_air, mode, bank_deg, climb_mps, advance_ratio, v.mass_kg)


def leg_estimate(v: Vehicle, a, b, alt_a: float, alt_b: float, ground_mps: float, wind: Wind, mode=None):
    """Straight leg only; hybrid requires explicit mode, no transition inferred."""
    if v.type != "multirotor":
        from .airframe_route import straight_leg
        return straight_leg(v, a, b, alt_a, alt_b, ground_mps, wind, mode)
    if mode not in (None, "mc"):
        raise ValueError("mode is incompatible with airframe type")
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
                   start_pct: float = 100.0, hover_s_per_wp: float = 5.0, mode=None):
    """points：[{id, lat, lon, alt}]，第一個是起點。回傳整條航線估算與每段明細。"""
    if v.type != "multirotor":
        from .airframe_mission import typed_route
        return typed_route(v, points, ground_mps, wind, start_pct, hover_s_per_wp, mode)
    if mode not in (None, "mc"):
        raise ValueError("mode is incompatible with airframe type")
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


def best_speed(v: Vehicle, wind: Wind, heading_deg: float = 0.0, lo=4.0, hi=None, mode=None):
    """Straight-flight optimum; new FW/hybrid search uses the airspeed envelope."""
    if v.type != "multirotor":
        from .airframe_route import typed_best_speed
        return typed_best_speed(v, wind, heading_deg, lo, hi, mode)
    if mode not in (None, "mc"):
        raise ValueError("mode is incompatible with airframe type")
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
                          start_pct: float = 100.0, mode=None) -> dict:
    """route：[{id?, lat, lon, alt}]。回傳總和與每段 {from,to,dist_m,time_s,energy_wh,pct_after}。"""
    pts = [dict(p, id=p.get("id", f"P{i}")) for i, p in enumerate(route)]
    return route_estimate(vehicle, pts, ground_mps or vehicle.cruise_mps, wind, start_pct,
                          hover_s_per_wp=0.0, mode=mode)


def rtl_energy(pos: dict, home: dict, vehicle: Vehicle, wind: Wind, ground_mps: float = None, mode=None) -> dict:
    """RTL energy only. FW arrival remains airborne; hybrid defaults to fw."""
    if vehicle.type != "multirotor":
        from .airframe_route import typed_rtl
        return typed_rtl(pos, home, vehicle, wind, ground_mps, mode)
    if mode not in (None, "mc"):
        raise ValueError("mode is incompatible with airframe type")
    p = dict(pos, id="here")
    h = dict(home, id="home", alt=0)
    return estimate_route_energy([p, h], vehicle, wind, ground_mps)


def transition_estimate(vehicle: Vehicle, from_mode, to_mode):
    """Standalone allowance; not a mode tracker or cmd3000 route executor."""
    from .airframe_route import transition_estimate as _transition
    return _transition(vehicle, from_mode, to_mode)


def turn_estimate(vehicle, v_air, angle_deg, wind, bank_deg=None, radius_m=None):
    """Calm-air coordinated additive arc; no flown geometry."""
    from .airframe_mission import turn_estimate as _turn
    return _turn(vehicle, v_air, angle_deg, wind, bank_deg, radius_m)


def loiter_estimate(vehicle, v_air, duration_s, wind, radius_m=None, mode=None):
    from .airframe_mission import loiter_estimate as _loiter
    return _loiter(vehicle, v_air, duration_s, wind, radius_m, mode)


def estimate_for_bounds(vehicle, points, ground_mps, wind, start_pct=100.0,
                        hover_s_per_wp=0.0, mode=None):
    """Detached context for explicit full-route scenario replay; no RTL inferred."""
    from .airframe_bounds import estimate_for_bounds as _estimate
    return _estimate(vehicle, points, ground_mps, wind, start_pct, hover_s_per_wp, mode)


def bounds(estimate, vehicle):
    """Finite scenario extrema and evidence, or unavailable on any unsupported scenario."""
    from .airframe_bounds import bounds as _bounds
    return _bounds(estimate, vehicle)


def wind_arc_estimate(vehicle, v_air, angle_deg, wind, entry_heading_deg,
                      clockwise=True, bank_deg=None, radius_m=None):
    """Explicit FW air-relative allowance, not a ground-fixed/executable arc."""
    from .wind_arc import wind_arc_estimate as _arc
    return _arc(vehicle, v_air, angle_deg, wind, entry_heading_deg,
                clockwise, bank_deg, radius_m)


def wind_loiter_estimate(vehicle, v_air, duration_s, wind, entry_heading_deg,
                         clockwise=True, radius_m=None):
    """Explicit FW air-relative orbit; does not update normalized route pose."""
    from .wind_arc import wind_loiter_estimate as _loiter
    return _loiter(vehicle, v_air, duration_s, wind, entry_heading_deg,
                   clockwise, radius_m)


def wind_route_estimate(vehicle, entry, events, wind, start_pct=100.0, mode=None):
    """Explicit local-plane tangent energy route; not an executable mission."""
    from .wind_route import wind_route_estimate as _route
    return _route(vehicle, entry, events, wind, start_pct, mode)


def geographic_wind_route_estimate(vehicle, entry, events, wind, start_pct=100.0, mode=None):
    """Bounded approximate lat/lon bridge for explicit level FW energy events."""
    from .geographic_wind_route import geographic_wind_route_estimate as _route
    return _route(vehicle, entry, events, wind, start_pct, mode)
