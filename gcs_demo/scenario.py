"""示範情境：新竹某園區巡檢 6 個點（2 個選配）、一個禁航區，中途風變大。"""
from __future__ import annotations

import copy

HOME = {"id": "H", "lat": 24.7860, "lon": 120.9970}

MISSION = {
    "name": "園區巡檢 A–F",
    "home": HOME,
    "cruise_alt_m": 50,
    "speed_mps": 8.0,
    "targets": [
        {"id": "A", "lat": 24.7895, "lon": 121.0005, "priority": 1},
        {"id": "B", "lat": 24.7930, "lon": 120.9960, "priority": 1},
        {"id": "C", "lat": 24.7915, "lon": 120.9900, "priority": 2},
        {"id": "D", "lat": 24.7860, "lon": 120.9880, "priority": 1},
        {"id": "E", "lat": 24.7815, "lon": 120.9925, "priority": 2},
        {"id": "F", "lat": 24.7830, "lon": 121.0020, "priority": 1},
    ],
    "no_fly": [{"id": "NFZ1", "lat": 24.7880, "lon": 120.9940, "radius_m": 140}],
    "limits": {"max_altitude_m": 120},
}

WIND = {"speed_mps": 4.0, "from_deg": 270.0}

# 「真實」條件：電池老化讓耗電多 15%，第 5 分鐘風增強
TRUE_CALIB = 1.15
WIND_EVENTS = [{"t_s": 300, "speed_mps": 9.0, "from_deg": 240.0}]
EVENT_AT_S = 300


def mission():
    return copy.deepcopy(MISSION)
