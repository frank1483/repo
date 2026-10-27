"""把任務規劃 demo 的模擬遙測餵給告警串的 PredictiveAlertEngine（gcs_demo/alerts/）。

告警引擎用本地 ENU 公尺；這裡以任務 home 為原點換算，並補齊引擎需要的電壓、電流等欄位。
"""
from __future__ import annotations

import math

from .alerts import energy_api
from .alerts.explain import explain
from .alerts.predict import Config, PredictiveAlertEngine, Telemetry
from .energy import Wind

CELLS = 4
_M = math.pi * 6371000.0 / 180.0


class AlertFeed:
    def __init__(self, home: dict, path: list, vehicle, explain_fn=explain):
        self.home = (home["lat"], home["lon"])
        energy_api.REF_LAT, energy_api.REF_LON = self.home      # 讓引擎的經緯度換算以 home 為原點
        self.vehicle = vehicle
        self.engine = PredictiveAlertEngine(self._route(path), (0.0, 0.0, 0.0), vehicle,
                                            Config(reserve_pct=vehicle.reserve_pct))
        self.explain_fn = explain_fn
        self.events = []

    def enu(self, lat, lon, alt=0.0):
        return ((lon - self.home[1]) * _M * math.cos(math.radians(self.home[0])),
                (lat - self.home[0]) * _M, alt)

    def _route(self, path):
        return [self.enu(p["lat"], p["lon"], p.get("alt", 0)) for p in path[1:-1]]

    def set_path(self, path):
        self.engine.set_route(self._route(path))

    def tick(self, rec: dict, next_idx: int) -> list:
        soc = max(0.0, rec["battery_pct"]) / 100.0
        volt = CELLS * (3.5 + 0.7 * soc)
        current = rec["power_w"] / volt
        tm = Telemetry(t=rec["t_s"], pos=self.enu(rec["lat"], rec["lon"], rec["alt"]),
                       vel=(rec.get("vel_e", 0.0), rec.get("vel_n", 0.0), 0.0),
                       soc_pct=rec["battery_pct"], voltage=volt - current * 0.004 * CELLS,
                       current_a=current, used_wh=rec.get("used_wh", 0.0), cell_count=CELLS,
                       next_wp=next_idx, link_pct=95.0, wind=Wind(rec["wind_mps"], rec["wind_from"]))
        new = self.engine.update(tm)
        for ev in new:
            if ev["type"] != "resolve" and self.explain_fn:
                ev["explain"] = self.explain_fn(ev)
            self.events.append(ev)
        return new


def battery_raise(events) -> dict | None:
    for ev in events:
        if ev["type"] == "raise" and ev["key"] in ("battery_route", "rtl_point"):
            return ev
    return None
