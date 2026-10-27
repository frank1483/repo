"""簡易飛行模擬：沿航線飛、依真實風與真實耗電係數扣電，產生遙測紀錄。

「真實」條件故意和規劃時不同（例如電池老化使耗電多 15%、中途風變大），
讓任務報告有東西可以分析，也讓重規劃有理由被觸發。
"""
from __future__ import annotations

import math
import random

from .energy import Vehicle, Wind, power_w, haversine_m, bearing_rad, G


class MissionRun:
    def __init__(self, vehicle: Vehicle, wind: Wind, true_calib: float = 1.15,
                 wind_events=None, seed: int = 7, dt: float = 2.0):
        self.v = vehicle
        self.wind = wind
        self.true_calib = true_calib
        self.wind_events = sorted(wind_events or [], key=lambda e: e["t_s"])
        self.rng = random.Random(seed)
        self.dt = dt
        self.t = 0.0
        self.pct = 100.0
        self.log = []          # 遙測
        self.legs = []         # 每段實際 vs 預估
        self.events = []       # 事件／重規劃／告警
        self.completed = []
        self.pos = None

    def _wind_now(self):
        w = self.wind
        for e in self.wind_events:
            if self.t >= e["t_s"]:
                w = Wind(e["speed_mps"], e["from_deg"])
        return w

    def fly(self, plan: dict, stop_at_s: float = None) -> dict:
        """依候選 plan（含 path、legs、speed_mps）飛，到 stop_at_s 或飛完為止。"""
        cap = self.v.battery_wh * self.v.usable_frac
        path = plan["path"]
        speed = plan["speed_mps"]
        pred_legs = {(l["from"], l["to"]): l for l in plan["legs"]}
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            if self.pos is None:
                self.pos = (a["lat"], a["lon"], a.get("alt", 0))
            start = self.pos
            dist = haversine_m(start[:2], (b["lat"], b["lon"]))
            brg = bearing_rad(start[:2], (b["lat"], b["lon"]))
            climb = b.get("alt", 0) - start[2]
            t_leg = dist / speed + abs(climb) / (3.0 if climb > 0 else 2.0)
            hover = 5.0 if b.get("kind") == "target" else 0.0
            t_leg += hover
            used = 0.0
            heads = []
            n = max(1, int(math.ceil(t_leg / self.dt)))
            for k in range(1, n + 1):
                w = self._wind_now()
                gust = 1.0 + self.rng.uniform(-0.25, 0.25)
                we, wn = w.vector()
                we, wn = we * gust, wn * gust
                frac = k / n
                if hover and k * self.dt > t_leg - hover:
                    v_air = math.hypot(we, wn)
                else:
                    ge, gn = speed * math.sin(brg), speed * math.cos(brg)
                    v_air = math.hypot(ge - we, gn - wn)
                heads.append(-(we * math.sin(brg) + wn * math.cos(brg)))
                p = power_w(self.v, v_air)
                if climb > 0:
                    p += self.v.mass_kg * G * 3.0 / self.v.eta * min(1.0, climb / 3.0 / max(t_leg, 1))
                p *= self.true_calib * (1.0 + self.rng.uniform(-0.03, 0.03))
                wh = p * self.dt / 3600.0
                used += wh
                self.pct -= wh / cap * 100.0
                self.t += self.dt
                lat = start[0] + (b["lat"] - start[0]) * frac
                lon = start[1] + (b["lon"] - start[1]) * frac
                alt = start[2] + climb * frac
                self.pos = (lat, lon, alt)
                self.log.append({"t_s": round(self.t, 1), "lat": round(lat, 6), "lon": round(lon, 6),
                                 "alt": round(alt, 1), "battery_pct": round(self.pct, 2),
                                 "power_w": round(p, 1), "wind_mps": w.speed_mps,
                                 "wind_from": w.from_deg, "leg": f"{a['id']}→{b['id']}"})
                if stop_at_s is not None and self.t >= stop_at_s and k < n:
                    self.legs.append(self._leg_rec(a, b, pred_legs, used, heads, plan.get("calib", 1.0),
                                                   partial=frac))
                    return self.state(plan, i, partial=True)
            self.pos = (b["lat"], b["lon"], b.get("alt", 0))
            self.legs.append(self._leg_rec(a, b, pred_legs, used, heads, plan.get("calib", 1.0)))
            if b.get("kind") == "target":
                self.completed.append(b["id"])
            if stop_at_s is not None and self.t >= stop_at_s and i < len(path) - 2:
                return self.state(plan, i + 1, partial=False)
        return self.state(plan, len(path) - 1, partial=False, done=True)

    def _leg_rec(self, a, b, pred_legs, used, heads, calib, partial=1.0):
        pred = pred_legs.get((a["id"], b["id"]))
        # pred_wh 一律換回「未修正」的物理模型預估，方便算學到的修正係數
        return {"from": a["id"], "to": b["id"], "actual_wh": round(used, 2),
                "pred_wh": round(pred["energy_wh"] * partial / calib, 2) if pred else None,
                "headwind_mps": round(sum(heads) / len(heads), 2) if heads else 0.0,
                "partial": partial < 1.0, "end_t_s": round(self.t, 1)}

    def state(self, plan, idx, partial, done=False):
        remaining = [p["id"] for p in plan["path"][idx + 1:] if p.get("kind") == "target"]
        if partial:
            nxt = plan["path"][idx + 1]
            if nxt.get("kind") == "target" and nxt["id"] not in remaining:
                remaining.insert(0, nxt["id"])
        pred = sum(l["pred_wh"] for l in self.legs if l["pred_wh"])
        act = sum(l["actual_wh"] for l in self.legs if l["pred_wh"])
        return {"observed_ratio": round(act / pred, 3) if pred else 1.0,
                "t_s": round(self.t, 1), "lat": self.pos[0], "lon": self.pos[1], "alt": self.pos[2],
                "battery_pct": round(self.pct, 1), "completed": list(self.completed),
                "remaining": remaining, "done": done}
