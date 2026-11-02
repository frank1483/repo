"""模擬一趟測繪任務，產生遙測餵給告警引擎（demo 用，非實機資料）。

模擬的「真實世界」故意和地面站的認知不一樣，讓預測有東西可抓：
- 電池實際容量只有標稱的 CAP_TRUE（老化），飛控電量% 卻照標稱算 → 偏高。
- 實際耗電比模型多 POWER_TRUE 倍（掛載較重）。
- 第 4–10 分鐘風速從 3 m/s 增強到 11 m/s（東北東風）。
- 鏈路品質隨離家距離下降。
之後可換成 PX4 SITL 的 MAVLink 遙測，引擎介面不變。
"""
from __future__ import annotations

import math
import random

from .energy_api import Wind, air_power_w, default_vehicle
from .predict import Config, PredictiveAlertEngine, Telemetry

CAP_TRUE = 0.86
POWER_TRUE = 1.10
CELLS = 6


def survey_route(alt=60.0):
    """家在原點；東北方 1.0–2.4 km 的來回掃描線。"""
    pts = [(0.0, 0.0, alt)]
    xs = [1000 + 200 * i for i in range(7)]
    for i, x in enumerate(xs):
        ys = (300.0, 1150.0) if i % 2 == 0 else (1150.0, 300.0)
        pts += [(x, ys[0], alt), (x, ys[1], alt)]
    return pts


def wind_at(t, scenario):
    if scenario == "calm":
        return Wind(3.0, 270.0)
    s = 3.0 + max(0.0, min(1.0, (t - 240) / 360)) * 8.0
    return Wind(s, 70.0)  # 東北東風：去程順風、回程逆風


def ocv_cell(soc_true):
    """單芯開路電壓對真實剩餘比例（中段近似線性，低於 10% 加速下滑）。"""
    v = 3.55 + 0.6 * soc_true
    if soc_true < 0.1:
        v -= (0.1 - soc_true) * 2.0
    return v


def run(scenario="gusty", policy="ignore", dt=1.0, seed=7, explain_fn=None, max_t=3000):
    """policy: "ignore" 不理告警照飛；"follow" 第一次電量告警時採用它的建議。"""
    rnd = random.Random(seed)
    home = (0.0, 0.0, 0.0)
    route = survey_route()
    veh = default_vehicle()
    eng = PredictiveAlertEngine(route, home, veh, Config(reserve_pct=veh.reserve_pct))

    cap_true = veh.battery_wh * CAP_TRUE
    pos = [0.0, 0.0, 0.0]
    target = list(route)                # 實際要飛的航點（採用建議後會改）
    wp_i = 0
    speed = veh.cruise_mps
    used = 0.0
    t = 0.0
    phase = "climb"
    frames, events, applied = [], [], None

    while t < max_t:
        wind = wind_at(t, scenario)
        wx, wy = wind.vector()
        vel = (0.0, 0.0, 0.0)
        if phase == "climb":
            vz = min(3.0, route[0][2] - pos[2])
            pos[2] += vz * dt
            vel = (0.0, 0.0, vz / dt)
            p = veh.p_hover_w + veh.mass_kg * 9.81 * vel[2] / veh.eta
            if pos[2] >= route[0][2] - 0.01:
                phase, wp_i = "cruise", 1
        elif phase == "cruise":
            tx, ty, _ = target[wp_i]
            dx, dy = tx - pos[0], ty - pos[1]
            d = math.hypot(dx, dy)
            ux, uy = (dx / d, dy / d) if d > 1e-6 else (0.0, 0.0)
            step = min(d, speed * dt)
            pos[0] += ux * step
            pos[1] += uy * step
            vel = (ux * speed, uy * speed, 0.0)
            p = air_power_w(veh, math.hypot(vel[0] - wx, vel[1] - wy))
            if d - step < 1.0:
                wp_i += 1
                if wp_i >= len(target):
                    phase = "home"
        elif phase == "home":
            dx, dy = home[0] - pos[0], home[1] - pos[1]
            d = math.hypot(dx, dy)
            if d < 1.0:
                phase = "land"
                p = veh.p_hover_w
            else:
                ux, uy = dx / d, dy / d
                step = min(d, speed * dt)
                pos[0] += ux * step
                pos[1] += uy * step
                vel = (ux * speed, uy * speed, 0.0)
                p = air_power_w(veh, math.hypot(vel[0] - wx, vel[1] - wy))
        else:  # land
            pos[2] = max(0.0, pos[2] - 2.0 * dt)
            vel = (0.0, 0.0, -2.0)
            p = veh.p_hover_w
            if pos[2] <= 0.0:
                frames.append(_frame(t, pos, used, cap_true, veh, wind, max(0.0, 100 * (1 - used / veh.battery_wh)), eng, "landed", None))
                break

        p *= POWER_TRUE * (1 + rnd.gauss(0, 0.02))
        used += p * dt / 3600.0
        soc_true = max(0.0, 1 - used / cap_true)
        volt_load = ocv_cell(soc_true) * CELLS
        current = p / volt_load
        volt = volt_load - current * 0.004 * CELLS + rnd.gauss(0, 0.02)
        dist = math.hypot(pos[0], pos[1])
        link = max(0.0, min(100.0, 100 - 0.034 * dist + rnd.gauss(0, 3)))
        soc_fc = max(0.0, 100 * (1 - used / veh.battery_wh))   # 飛控照標稱容量算
        wind_est = Wind(max(0.0, wind.speed_mps + rnd.gauss(0, 0.3)), wind.from_deg + rnd.gauss(0, 5))

        # 地面站知道的「下一個航點」（target 是原航線的前段，索引一致）
        orig_next = wp_i if phase == "cruise" else (0 if phase == "climb" else len(target))
        tm = Telemetry(t=t, pos=tuple(pos), vel=vel, soc_pct=soc_fc, voltage=volt, current_a=current,
                       used_wh=used, cell_count=CELLS, next_wp=orig_next, link_pct=link, wind=wind_est)
        if phase in ("cruise", "home"):
            new = eng.update(tm)
            for ev in new:
                if explain_fn and ev["type"] != "resolve":
                    ev["explain"] = explain_fn(ev)
                events.append(ev)
                if (policy == "follow" and ev["type"] in ("raise", "update")
                        and ev["key"] in ("battery_route", "rtl_point")):
                    a = _apply(ev, t, route, target, wp_i)
                    if a and (not applied or (a["action"], a.get("param")) != (applied[-1]["action"], applied[-1].get("param"))):
                        applied = (applied or []) + [a]
                        target, speed, phase = a["target"], a.get("speed", speed), a.get("phase", phase)
                        eng.set_route(target if phase == "cruise" else target[:wp_i])
        frames.append(_frame(t, pos, used, cap_true, veh, wind, soc_fc, eng, phase, link))
        t += dt

    landed_true = max(0.0, 1 - used / cap_true) * 100
    return {
        "scenario": scenario, "policy": policy, "route": route, "home": home, "frames": frames,
        "events": events,
        "applied": [{k: v for k, v in a.items() if k != "target"} for a in (applied or [])],
        "summary": {"flight_s": t, "landed_true_pct": round(landed_true, 1),
                    "landed_true_pct_of_nominal": round((cap_true - used) / veh.battery_wh * 100, 1),
                    "reserve_pct": veh.reserve_pct, "cap_true_ratio": CAP_TRUE, "power_true": POWER_TRUE},
    }


def _apply(ev, t, route, target, wp_i):
    """把告警選中的建議套到模擬機（操作員按確認後）。"""
    # HOLD 的 rule_choice 只是供顯示的緊急備選，禁止自動跟從。
    if ev.get("rule_decision") == "HOLD" or not any(c.get("feasible") is True for c in ev["candidates"]):
        return None
    text = (ev.get("explain") or {}).get("text", {})
    if text and text.get("decision") != "SELECT":
        return None
    choice = text.get("choice_id") or ev.get("rule_choice")
    c = next((c for c in ev["candidates"] if c["id"] == choice), None)
    if not c or c.get("feasible") is not True:
        return None
    a = c["action"]
    if a not in ("A_RTL_AFTER_WP", "A_REDUCE_SPEED", "A_RTL_NOW"):
        return None                         # 未支援的操作不冒充已套用（含就地降落）
    out = {"t": t, "choice_id": choice, "action": a, "label": c["label"], "param": c.get("param"),
           "key": ev["key"], "target": target}
    if a == "A_RTL_AFTER_WP":
        last = c.get("param_pos", c["param"])
        if not isinstance(last, int) or not 0 <= last < len(target):
            return None
        out["target"] = list(target[: last + 1])
        if wp_i >= len(out["target"]):
            out["phase"] = "home"
    elif a == "A_REDUCE_SPEED":
        out["speed"] = c["param"]
    elif a == "A_RTL_NOW":
        out["phase"] = "home"
    return out


def _frame(t, pos, used, cap_true, veh, wind, soc_fc, eng, phase, link):
    st = eng.last_state
    return {"t": round(t, 1), "x": round(pos[0], 1), "y": round(pos[1], 1), "alt": round(pos[2], 1),
            "soc_fc": None if soc_fc is None else round(soc_fc, 1),
            "soc_true_nom": round((cap_true - used) / veh.battery_wh * 100, 1),
            "pred_end": None if st.get("end_pct") is None else round(st["end_pct"], 1),
            "pnr_wp": st.get("pnr_wp"), "pnr_eta": None if st.get("pnr_eta_s") is None else round(st["pnr_eta_s"]),
            "calib": round(st.get("calib", 1.0), 3), "wind": round(wind.speed_mps, 1),
            "link": round(link, 0) if link else None, "phase": phase,
            "active": sorted(eng.active().keys())}
