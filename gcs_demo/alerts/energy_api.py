"""告警用的能耗入口：直接用三功能共用的 gcs_demo/energy.py，只做座標轉換。

告警引擎內部用本地 ENU 公尺 (x 東, y 北, alt)，共用模型吃經緯度；這裡把兩者接起來，
數字完全由共用模型算，告警不另養一套。速度參數是「地速指令」（PX4 任務巡航速度）。
"""
from __future__ import annotations

import math
from dataclasses import replace

from gcs_demo import energy as _e
from gcs_demo.energy import Vehicle, Wind  # noqa: F401  (re-export)

SOURCE = "gcs_demo.energy"
REF_LAT, REF_LON = 23.6945, 120.5340        # 本地座標原點（demo 用）
_M_PER_DEG = math.pi * _e.R_EARTH / 180.0


def to_latlon(p):
    lat = REF_LAT + p[1] / _M_PER_DEG
    lon = REF_LON + p[0] / (_M_PER_DEG * math.cos(math.radians(REF_LAT)))
    return lat, lon


def default_vehicle() -> Vehicle:
    """demo 機型：6 kg 測繪多旋翼、6S 22Ah（488 Wh）。電量% 以標稱容量計。"""
    return Vehicle(vehicle_id="UAV-01", mass_kg=6.0, battery_wh=488.0, usable_frac=1.0,
                   p_hover_w=800.0, cda_m2=0.15, eta=0.7, cruise_mps=12.0, max_mps=16.0,
                   reserve_pct=20.0)


def air_power_w(v: Vehicle, v_air: float) -> float:
    return _e.power_w(v, v_air)


def leg_energy(v: Vehicle, p0, p1, wind: Wind, ground_mps: float | None = None) -> dict:
    return _e.leg_estimate(v, to_latlon(p0), to_latlon(p1), p0[2], p1[2],
                           ground_mps or v.cruise_mps, wind)


def rtl_energy(pos, home, v: Vehicle, wind: Wind) -> dict:
    lat, lon = to_latlon(pos)
    hlat, hlon = to_latlon(home)
    return _e.rtl_energy({"lat": lat, "lon": lon, "alt": pos[2]}, {"lat": hlat, "lon": hlon}, v, wind)


def with_calib(v: Vehicle, calib: float) -> Vehicle:
    return replace(v, calib=calib)
