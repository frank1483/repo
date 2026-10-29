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
    def __init__(self, home: dict, path: list, vehicle, explain_fn=explain,
                 typed_geographic=False, typed_raise_ticks=3, typed_clear_ticks=10):
        if not isinstance(typed_geographic, bool):
            raise ValueError("typed_geographic must be boolean")
        self._typed_feed = None
        self.latest = None
        if typed_geographic:
            if home is not None or path is not None:
                raise ValueError("typed feed requires home=None and path=None; explicit geographic candidates required")
            from .alerts.typed_feed import TypedGeographicAlertFeed
            self._typed_feed = TypedGeographicAlertFeed(vehicle, typed_raise_ticks, typed_clear_ticks)
            self.vehicle = vehicle
            self.engine = None
            self.explain_fn = None
            self.events = []
            return
        self.home = (home["lat"], home["lon"])
        energy_api.REF_LAT, energy_api.REF_LON = self.home      # 讓引擎的經緯度換算以 home 為原點
        self.vehicle = vehicle
        prio = [p.get("priority", 1) for p in path[1:-1]]     # 繞行點視同必經
        self.engine = PredictiveAlertEngine(self._route(path), (0.0, 0.0, 0.0), vehicle,
                                            Config(reserve_pct=vehicle.reserve_pct, cell_empty_v=3.5),
                                            priorities=prio)
        self.explain_fn = explain_fn
        self.events = []

    def enu(self, lat, lon, alt=0.0):
        return ((lon - self.home[1]) * _M * math.cos(math.radians(self.home[0])),
                (lat - self.home[0]) * _M, alt)

    def _route(self, path):
        return [self.enu(p["lat"], p["lon"], p.get("alt", 0)) for p in path[1:-1]]

    def set_path(self, path):
        if self._typed_feed is not None:
            raise ValueError("typed feed requires a versioned request at tick; set_path is legacy ENU only")
        self.engine.set_route(self._route(path))

    def tick(self, rec: dict, next_idx: int, typed_request=None) -> list:
        if self._typed_feed is not None:
            if next_idx is not None:
                raise ValueError("typed feed requires next_idx=None; use explicit candidate events")
            if not isinstance(typed_request, dict) or set(typed_request) != {"sequence", "candidates", "current_id", "mission_version"}:
                raise ValueError("typed_request requires sequence, candidates, current_id, mission_version")
            result = self._typed_feed.tick(rec=rec, **typed_request)
            import copy
            self.latest = copy.deepcopy(result)
            new = result["events"]
            self.events.extend(copy.deepcopy(new))
            return new
        if typed_request is not None:
            raise ValueError("typed_request requires explicit typed_geographic=True")
        soc = max(0.0, rec["battery_pct"]) / 100.0
        volt = CELLS * (3.5 + 0.7 * soc)
        current = rec["power_w"] / volt
        tm = Telemetry(t=rec["t_s"], pos=self.enu(rec["lat"], rec["lon"], rec["alt"]),
                       vel=(rec.get("vel_e", 0.0), rec.get("vel_n", 0.0), 0.0),
                       soc_pct=rec["battery_pct"], voltage=volt - current * 0.004 * CELLS,
                       current_a=current, used_wh=rec.get("used_wh", 0.0), cell_count=CELLS,
                       next_wp=next_idx, link_pct=95.0, wind=Wind(rec["wind_mps"], rec["wind_from"]))
        # 模擬電壓只是 soc 的線性函數、沒有老化資訊，容量告警在此情境不可信，略過
        new = [e for e in self.engine.update(tm) if e["key"] != "battery_capacity"]
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
