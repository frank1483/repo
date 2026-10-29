"""Bounded geographic adapter for explicit FW wind energy events.

This is an entry-anchored equirectangular approximation, not WGS84 ENU,
geodesic navigation, a MAVLink parser, a waypoint fillet or a landing model.
"""
from __future__ import annotations

import math

from .airframe_route import number, position

MAX_PATH_M = 10000.0
MAX_ORIGIN_LAT = 75.0


def geographic_wind_route_estimate(v, entry, events, wind, start_pct=100.0, mode=None):
    """Bridge explicit normalized lat/lon events into one fixed local plane.

    entry: exactly lat, lon, alt, air_heading_deg. straight events require
    lat, lon, alt, ground_mps. arc/loiter fields match wind_route_estimate;
    only id is optional metadata. All flight is level at entry.alt. Entry
    latitude is limited to +/-75 degrees; cumulative air path plus wind
    travel is limited to 10 km, conservatively bounding intermediate poses.
    Longitude differences use the shortest wrapped interval across the date
    line. Curved-event geography is calculated from its drifted local exit.
    No angle, heading, connector, transition or speed is inferred.
    """
    from .energy import R_EARTH
    from .wind_route import wind_route_estimate

    if not isinstance(entry, dict) or set(entry) != {"lat", "lon", "alt", "air_heading_deg"}:
        raise ValueError("geographic entry requires only lat, lon, alt, air_heading_deg")
    position([entry["lat"], entry["lon"]])
    lat0 = number(entry["lat"], "origin lat", -MAX_ORIGIN_LAT, MAX_ORIGIN_LAT)
    lon0 = entry["lon"]
    alt = number(entry["alt"], "alt", 0)
    heading = number(entry["air_heading_deg"], "air_heading_deg")
    if not isinstance(events, list) or not 1 <= len(events) <= 1000:
        raise ValueError("geographic route requires 1..1000 events")
    metres = math.pi * R_EARTH / 180
    scale = metres * math.cos(math.radians(lat0))
    allowed = {"straight": {"kind", "id", "lat", "lon", "alt", "ground_mps"},
               "arc": {"kind", "id", "v_air", "angle_deg", "clockwise", "bank_deg", "radius_m"},
               "loiter": {"kind", "id", "v_air", "duration_s", "clockwise", "radius_m"}}
    local = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
            raise ValueError("geographic event requires a kind")
        kind = event["kind"]
        if kind not in allowed or set(event) - allowed[kind]:
            raise ValueError("unsupported geographic event fields")
        if "id" in event and (not isinstance(event["id"], str) or not 1 <= len(event["id"]) <= 128):
            raise ValueError("id requires a nonempty string of at most 128 characters")
        if kind == "straight":
            position([event.get("lat"), event.get("lon")])
            if number(event.get("alt"), "straight alt", 0) != alt:
                raise ValueError("geographic wind route requires constant altitude")
            east = ((event["lon"] - lon0 + 180) % 360 - 180) * scale
            north = (event["lat"] - lat0) * metres
            if math.hypot(east, north) > MAX_PATH_M:
                raise ValueError("geographic target exceeds 10 km local frame")
            item = {"kind": kind, "east_m": east, "north_m": north,
                    "ground_mps": event.get("ground_mps")}
            if "id" in event:
                item["id"] = event["id"]
            local.append(item)
        else:
            local.append(dict(event))
    result = wind_route_estimate(v, {"east_m": 0.0, "north_m": 0.0,
                                    "air_heading_deg": heading}, local, wind, start_pct, mode)
    # Endpoint-only checks miss a large full-circle excursion. This bound
    # includes every intermediate displacement, but may reject small loops.
    reach = number(result["air_dist_m"] + wind.speed_mps * result["time_s"], "path budget", 0)
    if reach > MAX_PATH_M:
        raise ValueError("geographic route exceeds 10 km cumulative path budget")

    def geographic(p):
        return {"lat": lat0 + p["north_m"] / metres,
                "lon": (lon0 + p["east_m"] / scale + 180) % 360 - 180,
                "alt": alt}

    legs = [{**leg, "entry_geographic": geographic(leg["entry_local_m"]),
             "exit_geographic": geographic(leg["exit_local_m"])} for leg in result["legs"]]
    return {**result, "legs": legs, "exit_geographic": geographic(result["exit_local_m"]),
            "projection": {"kind": "entry_anchored_equirectangular_approximation",
                           "origin": {"lat": lat0, "lon": lon0, "alt": alt},
                           "earth_radius_m": R_EARTH, "max_path_m": MAX_PATH_M,
                           "max_origin_lat_deg": MAX_ORIGIN_LAT, "path_budget_m": reach},
            "scope": "geographic_explicit_tangent_energy_approximation_not_executable_route"}
