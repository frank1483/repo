"""把任務規劃 demo 的模擬遙測餵給告警串的 PredictiveAlertEngine（gcs_demo/alerts/）。

告警引擎用本地 ENU 公尺；這裡以任務 home 為原點換算，並補齊引擎需要的電壓、電流等欄位。
"""
from __future__ import annotations

import math
from copy import deepcopy

from .alerts.core.log import AlertLog

from .alerts import energy_api
from .alerts.typed_explain import LegacyAlertExplainer, legacy_version
from .alerts.predict import Config, PredictiveAlertEngine, Telemetry
from .energy import Wind

CELLS = 4
_DEFAULT_EXPLAIN = object()   # 預設：非同步說明（分級先出、模型說明後補）；傳 None 表示不要說明
_M = math.pi * 6371000.0 / 180.0


class AlertFeed:
    def __init__(self, home: dict, path: list, vehicle, explain_fn=_DEFAULT_EXPLAIN,
                 typed_geographic=False, typed_raise_ticks=3, typed_clear_ticks=10,
                 log_path=None):
        if not isinstance(typed_geographic, bool):
            raise ValueError("typed_geographic must be boolean")
        if typed_geographic and log_path is not None:
            raise ValueError("v5 logging currently requires the legacy engine")
        self.alert_log = AlertLog(log_path)
        self.engine_events = []  # unfiltered denominator, including hidden capacity events
        self._pending_explanations = {}  # request snapshots + private returned-result references
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
        self.explain_fn = (LegacyAlertExplainer(current_state=self.engine.current_state)
                           if explain_fn is _DEFAULT_EXPLAIN else explain_fn)
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
        emitted = self.engine.update(tm)
        # Retain every engine output BEFORE the demo-only capacity display filter.
        for ev in emitted:
            self.engine_events.append(deepcopy(ev))
            self.alert_log.append(ev)
        new = [deepcopy(e) for e in emitted if e["key"] != "battery_capacity"]
        for ev in new:
            if ev["type"] == "resolve":
                retire = getattr(self.explain_fn, "retire", None)
                if retire is not None:
                    retire(ev["key"])
            if ev["type"] != "resolve" and self.explain_fn:
                returned = self.explain_fn(deepcopy(ev))
                ev["explain"] = deepcopy(returned)
                if isinstance(returned, dict) and returned.get("source") == "rule_pending":
                    self._pending_explanations[(ev["key"], legacy_version(ev))] = {
                        "event": deepcopy(ev), "returned": returned}
            self.events.append(ev)
        self._settle_explanations()
        if self.alert_log.last_snapshot_t is None or tm.t >= self.alert_log.last_snapshot_t:
            self.alert_log.snapshot(tm.t, {"last_state": deepcopy(self.engine.last_state),
                                          "alerts": self.engine._states.snapshot()})
        return new

    def _append_explanation(self, event):
        self.engine_events.append(deepcopy(event))
        self.alert_log.append(event)
        self.events.append(deepcopy(event))

    def _close_pending(self, request, reason):
        pending = self._pending_explanations.pop(request, None)
        if pending is not None:
            # Rejected model content must not retire a still-live rule alert.
            fallback = None
            if reason == "result_rejected":
                fallback = self.engine.apply_explanation(*request, {
                    "source": "rule", "text": {}, "fallback_reason": reason})
            self._append_explanation(fallback if fallback is not None else
                                     self.engine.close_explanation(pending["event"], reason))

    def _invalid_reason(self, request):
        key, version = request
        current = self.engine.current_state(key)
        if current is None:
            return "state_unavailable"
        if current["alert_version"] != version:
            return "version_superseded"
        if current["active"] is not True:
            state = self.engine._states.states.get(key)
            if state and state.prediction_expired:
                return "prediction_expired"
            if state and state.facts.get("route_version") != self.engine._route_revision:
                return "route_superseded"
            return "alert_retired"
        return None

    def _settle_explanations(self):
        # LegacyAlertExplainer may drop a completion before returning poll rows.
        # Its private returned-result object settles to rule on retire/rejection;
        # retain that reference separately, never share it with stored history.
        for request, pending in list(self._pending_explanations.items()):
            reason = self._invalid_reason(request)
            if reason:
                self._close_pending(request, reason)
            elif pending["returned"].get("source") == "rule":
                event = self.engine.apply_explanation(*request, pending["returned"])
                if event is None:
                    self._close_pending(request, "result_rejected")
                else:
                    self._pending_explanations.pop(request)
                    self._append_explanation(event)

    def poll_explanations(self) -> list:
        """Append completions/closures; old request and event rows stay immutable."""
        if self._typed_feed is not None:
            return []
        poll = getattr(self.explain_fn, "poll", None)
        accepted = []
        for item in (poll() if poll is not None else []):
            request = (item["key"], item["version"])
            # Retired/settled/duplicate results can no longer affect the engine.
            if request not in self._pending_explanations:
                continue
            reason = self._invalid_reason(request)
            event = None if reason else self.engine.apply_explanation(*request, item["result"])
            if event is None:
                self._close_pending(request, reason or "result_rejected")
                continue
            self._pending_explanations.pop(request)
            self._append_explanation(event)
            accepted.append({**deepcopy(item), "result": deepcopy(event["explain"]),
                             "event": deepcopy(event)})
        self._settle_explanations()
        return accepted



def battery_raise(events) -> dict | None:
    for ev in events:
        if ev["type"] == "raise" and ev["key"] in ("battery_route", "rtl_point"):
            return ev
    return None
