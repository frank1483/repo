"""Explicit geographic P1 caller, not a flight-action or legacy ENU engine."""
from __future__ import annotations

import copy
import re

from .typed_geographic import GeographicEnergyAlertPredictor, _integer
from ..airframe_route import number
from ..geographic_alerts import _snapshot
from ..energy import Wind


class TypedGeographicAlertFeed:
    """Caller supplies a complete route snapshot at each measured entry pose.

    mission_version is a caller-owned structural version, not a certified hash.
    A changed version resets hysteresis explicitly. Unknown energy emits an
    'unknown' event, never 'resolve'; recovery emits 'known' when not active.
    Consumers must support reset/unknown/known before displaying this feed.
    Only P1 is evaluated: P2--P5 are explicitly unassessed, not clear.
    """
    def __init__(self, vehicle, raise_ticks=3, clear_ticks=10):
        if not vehicle.airframe_profile or vehicle.type not in ("fixed_wing", "vtol_hybrid"):
            raise ValueError("typed feed requires an explicit FW/hybrid profile")
        self._raise_ticks = _integer(raise_ticks, "raise_ticks", 1, 10000)
        self._clear_ticks = _integer(clear_ticks, "clear_ticks", 1, 10000)
        self._vehicle = copy.deepcopy(vehicle)
        self._predictor = None
        self._version = self._current = None
        self._sequence = -1
        self._time = -1.0
        self._active = None
        self._severity = None

    def tick(self, sequence, rec, candidates, current_id, mission_version):
        _integer(sequence, "sequence", 0, 9007199254740991)
        if sequence <= self._sequence:
            raise ValueError("sequence must increase strictly")
        if not isinstance(mission_version, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", mission_version):
            raise ValueError("mission_version requires 1..128 ASCII version characters")
        if not isinstance(rec, dict):
            raise ValueError("typed feed requires measured geographic telemetry")
        required = ("t_s", "lat", "lon", "alt", "air_heading_deg", "battery_pct", "wind_mps", "wind_from")
        if any(k not in rec for k in required):
            raise ValueError("typed feed missing measured telemetry field")
        # Do not use ENU conversion, synthetic voltage/current, zero wind,
        # assumed heading or the legacy wind/capacity calibration path.
        tm = {k: rec[k] for k in required}
        for k in required:
            number(tm[k], k)
        number(tm["t_s"], "t_s", 0)
        if tm["t_s"] <= self._time:
            raise ValueError("t_s must increase strictly")
        number(tm["lat"], "lat", -75, 75)
        number(tm["lon"], "lon", -180, 180)
        number(tm["alt"], "alt", 0)
        number(tm["battery_pct"], "battery_pct", 0, 100)
        number(tm["wind_mps"], "wind_mps", 0)
        items = _snapshot(candidates)
        if not isinstance(items, list) or not 1 <= len(items) <= 16:
            raise ValueError("typed feed requires 1..16 explicit alternatives")
        pose = {k: tm[k] for k in ("lat", "lon", "alt", "air_heading_deg")}
        if any(not isinstance(c, dict) or c.get("entry") != pose for c in items):
            raise ValueError("every candidate entry must equal measured geographic pose")
        changed = self._version is not None and mission_version != self._version
        if self._version == mission_version and current_id != self._current:
            raise ValueError("current_id change requires a new mission_version")
        predictor = (GeographicEnergyAlertPredictor(self._vehicle, self._raise_ticks, self._clear_ticks)
                     if self._predictor is None or changed else self._predictor)
        result = predictor.tick(sequence, items, current_id,
                                Wind(tm["wind_mps"], tm["wind_from"]), tm["battery_pct"])
        # No state commits on schema/evaluation errors. Unknown geometry is
        # a valid consumed sample and must break the previous alert latch.
        previous = None if changed else self._active
        events = []

        def event(kind, finding=None):
            f = finding or {"key": "typed_geographic_energy", "active": None,
                            "severity": 5, "title": "Typed geographic energy status",
                            "value": "unassessed energy status", "evidence": [],
                            "candidates": [], "rule_choice": None, "lead_s": None}
            events.append({**f, "t": tm["t_s"], "type": kind,
                           "status": result["status"], "sequence": sequence,
                           "mission_version": mission_version, "executable": False})

        if changed:
            event("reset")
        if result["active"] is None:
            # Repeat unknown samples remain observable in the snapshot.
            if previous is not None or self._version is None or changed:
                event("unknown")
        elif result["active"]:
            if previous is not True:
                event("raise", result["finding"])
            elif result["finding"]["severity"] < self._severity:
                event("update", result["finding"])
        elif previous is True:
            event("resolve", result["finding"])
        elif previous is None:
            event("known", result["finding"])
        result.update({"mission_version": mission_version, "t_s": tm["t_s"],
                       "events": events, "unassessed_predictors": ["P2", "P3", "P4", "P5"],
                       "caller_scope": "explicit_geographic_P1_feed_only"})
        self._predictor = predictor
        self._version, self._current = mission_version, current_id
        self._sequence, self._time = sequence, tm["t_s"]
        self._active = result["active"]
        self._severity = result["finding"]["severity"] if result["finding"] else None
        return _snapshot(result)
