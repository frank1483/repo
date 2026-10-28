"""Offline QGC dialect parsing. Missing measurements remain explicit.

Legacy canonical columns keep their strict current/voltage validation.
Only QGC battery0.current=-1 and '--.--' denote unknown current.
"""
from __future__ import annotations

import csv
import json
import statistics
from datetime import datetime, timezone


def load_plan(path):
    """Read SimpleItem 16/22 and RTL 20; reject unsupported commands/frames.

    Planner altitudes are relative to planned home. Global (AMSL) items are
    converted using plannedHomePosition[2]. No equipment or implicit execution.
    """
    from .flightlog import _number
    with open(path, encoding='utf-8-sig') as stream:
        document = json.load(stream)
    if not isinstance(document, dict) or document.get('fileType') != 'Plan':
        raise ValueError('expected QGC Plan document')
    m = document.get('mission', {})
    if not isinstance(m, dict):
        raise ValueError('mission must be an object')
    h = m.get('plannedHomePosition')
    if not isinstance(h, list) or len(h) != 3:
        raise ValueError('plannedHomePosition must contain lat, lon, AMSL altitude')
    home = {'id': 'H', 'lat': _number(h[0], 'home.lat', -90, 90),
            'lon': _number(h[1], 'home.lon', -180, 180)}
    home_amsl = _number(h[2], 'home.amsl')
    targets, rtl = [], False
    items = m.get('items')
    if not isinstance(items, list):
        raise ValueError('mission.items must be a list')
    for i, item in enumerate(items):
        if not isinstance(item, dict) or item.get('type') != 'SimpleItem':
            raise ValueError(f'item {i}: only SimpleItem is supported')
        command = item.get('command')
        if command == 20:
            if i != len(items)-1:
                raise ValueError('RTL must be terminal; items after RTL are not supported')
            rtl = True
            continue
        if command not in (16, 22):
            raise ValueError(f'item {i}: unsupported command {command}')
        if item.get('frame') not in (0, 3):
            raise ValueError(f'item {i}: only global/relative-altitude frames 0/3 are supported')
        params = item.get('params')
        if not isinstance(params, list) or len(params) != 7:
            raise ValueError(f'item {i}: expected seven params')
        alt = _number(params[6], f'item {i}.alt')
        if item['frame'] == 0:
            alt -= home_amsl
        targets.append({'id': f'WP{i+1}', 'lat': _number(params[4], f'item {i}.lat', -90, 90),
                        'lon': _number(params[5], f'item {i}.lon', -180, 180),
                        'alt': alt, 'priority': 1, 'source_command': command})
    if not targets:
        raise ValueError('plan contains no waypoint/takeoff targets')
    speed = _number(m.get('hoverSpeed', m.get('cruiseSpeed', 8)), 'plan.speed_mps', 0.001)
    return {'name': 'Imported QGC plan', 'home': home, 'targets': targets, 'no_fly': [],
            'cruise_alt_m': max(t['alt'] for t in targets), 'speed_mps': speed,
            'rtl': rtl, 'source_home_amsl_m': home_amsl,
            'source_format': 'QGC Plan', 'limits': {'max_altitude_m': 120}}


def read_samples(path, aliases, scale, max_gap, number):
    rows, mapping = [], {}
    optional = {'current_a', 'wind_mps', 'wind_from'}
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError('duplicate CSV headers')
        for name, choices in aliases.items():
            choices = [choices] if isinstance(choices, str) else choices
            if not isinstance(choices, (tuple, list)) or not all(isinstance(c, str) for c in choices):
                raise ValueError(f'{name}: column aliases must be strings')
            found = [h for h in headers if h in choices]
            if len(found) > 1:
                raise ValueError(f'{name}: ambiguous CSV columns {found}')
            if not found and name not in optional:
                raise ValueError(f'{name}: required column missing (aliases {choices})')
            if found:
                mapping[name] = found[0]
        if len(set(mapping.values())) != len(mapping):
            raise ValueError('one CSV column cannot supply multiple canonical fields')
        for line, raw in enumerate(reader, 2):
            if None in raw:
                raise ValueError(f'row {line}: extra CSV fields')
            rec = {}
            for name in aliases:
                col = mapping.get(name)
                value = raw.get(col) if col else None
                qgc_current = col == 'battery0.current'
                if name in ('wind_mps', 'wind_from') and (col is None or value == '--.--'):
                    rec[name] = None
                elif name == 'current_a' and (col is None or value == '--.--' or
                        (qgc_current and value is not None and value.strip() and float(value) == -1)):
                    rec[name] = None
                elif name == 't_s' and col == 'Timestamp':
                    try:
                        rec[name] = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=timezone.utc).timestamp() * scale
                    except (ValueError, TypeError) as exc:
                        raise ValueError(f'row {line}: invalid QGC Timestamp') from exc
                else:
                    rec[name] = number(value, f'row {line}.{name}')
                    if name == 't_s':
                        rec[name] *= scale
            number(rec['t_s'], f'row {line}.scaled_time')
            for name, lo, hi in [('lat', -90, 90), ('lon', -180, 180), ('battery_pct', 0, 100),
                                 ('wind_mps', 0, None), ('wind_from', 0, 360),
                                 ('voltage', 0.000001, None), ('current_a', 0, None)]:
                if rec[name] is not None:
                    number(rec[name], f'row {line}.{name}', lo, hi)
            if 'groundSpeed' in raw and raw['groundSpeed'] != '--.--':
                rec['ground_speed_mps'] = number(raw['groundSpeed'], f'row {line}.groundSpeed', 0)
            # Armed is not present in the supplied QGC CSV. Never claim it was observed.
            for col in ('armed', 'vehicle.armed'):
                if col in raw and raw[col] in ('0', '1', 'false', 'true', 'False', 'True'):
                    rec['armed'] = raw[col] in ('1', 'true', 'True')
            if rows:
                dt = rec['t_s'] - rows[-1]['t_s']
                if dt <= 0 or dt > max_gap:
                    raise ValueError(f'row {line}: timestamps must increase; gap <= {max_gap} s')
            rows.append(rec)
    if len(rows) < 2:
        raise ValueError('at least two telemetry rows required')
    original_count, trim_reason = len(rows), None
    # Reset inference needs a prior airborne sample and stationary ground samples.
    # The low-altitude sample at landing is retained; later ground/reset rows are cut.
    def ground(r):
        return (abs(r['alt']) <= 1 and r.get('ground_speed_mps', float('inf')) <= 0.5
                and r.get('armed') is not True)
    landing = None
    airborne = False
    for i, rec in enumerate(rows):
        if rec['alt'] > 2:
            airborne, landing = True, None
        if airborne and ground(rec):
            if landing is None:
                landing = i
            if i > landing and rec['battery_pct'] > rows[i-1]['battery_pct'] + 0.5:
                if landing < 1:
                    raise ValueError('insufficient pre-reset telemetry')
                trim_reason = 'stationary_ground_then_soc_reset; disarm_inferred' if 'armed' not in rec else 'disarmed_ground_then_soc_reset'
                rows = rows[:landing+1]
                break
        else:
            landing = None
    current_missing = sum(r['current_a'] is None for r in rows)
    wind_missing = sum(r['wind_mps'] is None or r['wind_from'] is None for r in rows)
    estimated = current_missing > 0
    if estimated and any(b['battery_pct'] > a['battery_pct'] for a, b in zip(rows, rows[1:])):
        raise ValueError('SOC increase invalidates fallback integration before landing reset')
    intervals = [b['t_s']-a['t_s'] for a, b in zip(rows, rows[1:])]
    quality = {'missing_wind': wind_missing > 0, 'missing_current': estimated,
               'wind_missing_samples': wind_missing, 'current_missing_samples': current_missing,
               'soc_estimated': estimated, 'sample_count': len(rows), 'input_sample_count': original_count,
               'trimmed_samples': original_count-len(rows), 'trim_reason': trim_reason,
               'disarm_observed': any(r.get('armed') is False for r in rows),
               'sample_interval_s': {'min': min(intervals), 'median': statistics.median(intervals), 'max': max(intervals)},
               'calibration_eligible': not estimated and not wind_missing,
               'prediction_wind_assumption': 'zero_wind_for_missing_samples_only' if wind_missing else 'measured'}
    return rows, mapping, quality
