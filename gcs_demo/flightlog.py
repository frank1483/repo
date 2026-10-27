"""Strict, offline CSV adapter. Real QGC export dialect remains unverified.

load_csv accepts a planner envelope (vehicle/candidates/pick), or a selected
candidate carrying vehicle. Configure aliases/units in mission['flightlog'].
No backend, equipment, or model calls are made by this module.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field, replace

from .energy import Vehicle, Wind, G, bearing_rad, haversine_m, power_w


COLUMNS = {
    't_s': ('t_s', 'time_s', 'timestamp_s'),
    'lat': ('lat', 'latitude', 'latitude_deg'),
    'lon': ('lon', 'longitude', 'longitude_deg'),
    'alt': ('alt', 'altitude_m', 'alt_m'),
    'battery_pct': ('battery_pct', 'soc_pct', 'battery_percent'),
    'voltage': ('voltage', 'voltage_v', 'battery_voltage'),
    'current_a': ('current_a', 'current', 'battery_current'),
    'wind_mps': ('wind_mps', 'wind_speed_mps'),
    'wind_from': ('wind_from', 'wind_from_deg', 'wind_direction_deg'),
}


@dataclass
class RunLike:
    v: Vehicle
    plan: dict
    t: float = 0.0
    pct: float = 0.0
    log: list = field(default_factory=list)
    legs: list = field(default_factory=list)
    completed: list = field(default_factory=list)
    energy_source: str = 'voltage_current_trapezoid'
    energy_estimated: bool = False
    provenance: dict = field(default_factory=dict)


def _number(value, label, lo=None, hi=None):
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label}: expected a number') from exc
    if not math.isfinite(x) or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(f'{label}: invalid/out-of-range value')
    return x


def _point(p, label, default_alt):
    if not isinstance(p, dict) or not isinstance(p.get('id'), str) or not p['id']:
        raise ValueError(f'{label}: nonempty string id required')
    return dict(p, lat=_number(p.get('lat'), label+'.lat', -90, 90),
                lon=_number(p.get('lon'), label+'.lon', -180, 180),
                alt=_number(p.get('alt', default_alt), label+'.alt'))


def _inputs(mission, supplied):
    plan = supplied
    if 'candidates' in supplied:
        choice = supplied.get('pick', {}).get('choice_id')
        matches = [c for c in supplied['candidates'] if c.get('id') == choice]
        if len(matches) != 1:
            raise ValueError('plan: unique selected candidate required; HOLD is not a route')
        plan = matches[0]
    vehicle = supplied.get('vehicle', mission.get('vehicle'))
    if isinstance(vehicle, Vehicle):
        v = replace(vehicle)
    elif isinstance(vehicle, dict):
        # Reject absent capacity rather than silently assuming a default battery.
        if 'battery_wh' not in vehicle or 'usable_frac' not in vehicle:
            raise ValueError('vehicle: battery_wh and usable_frac required')
        v = Vehicle(**vehicle)
    else:
        raise ValueError('plan/mission.vehicle required (planner envelope is supported)')
    for name in ('battery_wh', 'mass_kg', 'eta', 'calib', 'p_hover_w'):
        if _number(getattr(v, name), 'vehicle.'+name) <= 0:
            raise ValueError('vehicle.'+name+': must be positive')
    _number(v.usable_frac, 'vehicle.usable_frac', 0.000001, 1)
    _number(v.cda_m2, 'vehicle.cda_m2', 0)
    _number(v.reserve_pct, 'vehicle.reserve_pct', 0, 100)
    if _number(plan.get('speed_mps'), 'plan.speed_mps') <= 0:
        raise ValueError('plan.speed_mps must be positive')
    _number(plan.get('end_pct'), 'plan.end_pct')
    raw_path = plan.get('path')
    if not isinstance(raw_path, list) or len(raw_path) < 2:
        raise ValueError('plan.path: at least two points required')
    alt = _number(mission.get('cruise_alt_m', 0), 'mission.cruise_alt_m')
    route = [_point(p, f'plan.path[{i}]', alt) for i, p in enumerate(raw_path)]
    ids = [t['id'] for t in mission['targets']]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('mission targets must have unique nonempty string ids')
    return v, dict(plan, path=route), set(ids)


def load_csv(path, mission, plan) -> RunLike:
    """CSV times must be strictly increasing, finite numeric seconds by default.

    Defaults: metres/deg/V/A, meteorological wind FROM degrees, altitude in the
    same datum as plan.path, 10 m 3D arrival radius, max 30 s sample gap.
    mission['flightlog'] can set columns, time_scale, arrival_radius_m,
    max_gap_s, and soc_capacity_basis ('usable' default, or 'nominal').
    Missing current *column* selects SOC fallback; blank current cells fail.
    """
    v, selected, targets = _inputs(mission, plan)
    cfg = mission.get('flightlog', {})
    aliases = dict(COLUMNS)
    override = cfg.get('columns', {})
    if set(override) - set(COLUMNS):
        raise ValueError('unknown canonical column mapping')
    aliases.update(override)
    scale = _number(cfg.get('time_scale', 1), 'time_scale')
    radius = _number(cfg.get('arrival_radius_m', 10), 'arrival_radius_m')
    max_gap = _number(cfg.get('max_gap_s', 30), 'max_gap_s')
    if min(scale, radius, max_gap) <= 0:
        raise ValueError('time_scale, arrival_radius_m, max_gap_s must be positive')
    basis = cfg.get('soc_capacity_basis', 'usable')
    if basis not in ('nominal', 'usable'):
        raise ValueError('soc_capacity_basis must be nominal or usable')
    cap = v.battery_wh * (v.usable_frac if basis == 'usable' else 1)
    run = RunLike(v=v, plan=selected)
    rows = []
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError('duplicate CSV headers')
        mapping = {}
        for name, choices in aliases.items():
            choices = [choices] if isinstance(choices, str) else choices
            if not isinstance(choices, (tuple, list)) or not all(isinstance(c, str) for c in choices):
                raise ValueError(f'{name}: column aliases must be strings')
            found = [h for h in headers if h in choices]
            if len(found) > 1:
                raise ValueError(f'{name}: ambiguous CSV columns {found}')
            if not found and name != 'current_a':
                raise ValueError(f'{name}: required column missing (aliases {choices})')
            if found:
                mapping[name] = found[0]
        if len(set(mapping.values())) != len(mapping):
            raise ValueError('one CSV column cannot supply multiple canonical fields')
        run.energy_estimated = 'current_a' not in mapping
        if run.energy_estimated:
            run.energy_source = 'soc_delta_' + basis + '_wh_estimate'
        for line, raw in enumerate(reader, 2):
            if None in raw:
                raise ValueError(f'row {line}: extra CSV fields')
            rec = {k: _number(raw.get(h), f'row {line}.{k}') for k, h in mapping.items()}
            rec['t_s'] = _number(rec['t_s'] * scale, f'row {line}.scaled_time')
            for k, lo, hi in [('lat', -90, 90), ('lon', -180, 180),
                              ('battery_pct', 0, 100), ('wind_mps', 0, None),
                              ('wind_from', 0, 360), ('voltage', 0.000001, None)]:
                _number(rec[k], f'row {line}.{k}', lo, hi)
            if not run.energy_estimated:
                _number(rec['current_a'], f'row {line}.current_a', 0)
                rec['power_w'] = rec['voltage'] * rec['current_a']
                if not math.isfinite(rec['power_w']):
                    raise ValueError(f'row {line}: nonfinite power')
            if rows:
                dt = rec['t_s'] - rows[-1]['t_s']
                if dt <= 0 or dt > max_gap:
                    raise ValueError(f'row {line}: timestamps must increase; gap <= {max_gap} s')
                if run.energy_estimated and rec['battery_pct'] > rows[-1]['battery_pct']:
                    raise ValueError(f'row {line}: SOC increase invalidates fallback integration')
            rows.append(rec)
    if len(rows) < 2:
        raise ValueError('at least two telemetry rows required')
    origin = rows[0]['t_s']
    for rec in rows:
        rec['t_s'] -= origin
    route, next_index, used = selected['path'], 1, 0.0
    accumulator = None

    def new_leg():
        if next_index < len(route):
            a, b = route[next_index-1]['id'], route[next_index]['id']
        else:
            a = b = 'POST_ROUTE'
        return {'from': a, 'to': b, 'actual_wh': 0.0, 'pred_wh': 0.0,
                'headwind_mps': 0.0, 'partial': True, 'end_t_s': 0.0, '_dt': 0.0}

    def finish(leg, partial):
        seconds = leg.pop('_dt')
        leg['headwind_mps'] = leg['headwind_mps'] / seconds if seconds else 0.0
        leg['partial'] = partial
        run.legs.append(leg)

    physical = replace(v, calib=1.0)
    accumulator = new_leg()
    for i, rec in enumerate(rows):
        if i:
            prev = rows[i-1]
            dt = rec['t_s'] - prev['t_s']
            dist = haversine_m((prev['lat'], prev['lon']), (rec['lat'], rec['lon']))
            heading = bearing_rad((prev['lat'], prev['lon']), (rec['lat'], rec['lon']))
            ground = dist / dt
            ve, vn = ground * math.sin(heading), ground * math.cos(heading)
            w0 = Wind(prev['wind_mps'], prev['wind_from']).vector()
            w1 = Wind(rec['wind_mps'], rec['wind_from']).vector()
            we, wn = (w0[0]+w1[0])/2, (w0[1]+w1[1])/2
            pred = power_w(physical, math.hypot(ve-we, vn-wn)) * dt / 3600
            pred += physical.mass_kg * G * max(0, rec['alt']-prev['alt']) / physical.eta / 3600
            if run.energy_estimated:
                actual = (prev['battery_pct']-rec['battery_pct']) * cap / 100
                rec['power_w'] = actual * 3600 / dt
            else:
                actual = (prev['power_w']+rec['power_w']) * 0.5 * dt / 3600
            if not all(math.isfinite(x) for x in (pred, actual, used+actual)):
                raise ValueError('nonfinite interval energy')
            used += actual
            accumulator['actual_wh'] += actual
            accumulator['pred_wh'] += pred
            accumulator['headwind_mps'] += -(we*math.sin(heading)+wn*math.cos(heading))*dt if dist else 0
            accumulator['_dt'] += dt
            rec['vel_e'], rec['vel_n'] = ve, vn
        else:
            rec['vel_e'] = rec['vel_n'] = 0.0
            if run.energy_estimated:
                rec['power_w'] = None  # no preceding interval; unknown, not zero
        rec['used_wh'] = used
        rec['leg'] = accumulator['from'] + '→' + accumulator['to']
        accumulator['end_t_s'] = rec['t_s']
        # Samples only: do not infer arrival between two distant GNSS fixes.
        while next_index < len(route):
            target = route[next_index]
            horizontal = haversine_m((rec['lat'], rec['lon']), (target['lat'], target['lon']))
            if math.hypot(horizontal, rec['alt']-target['alt']) >= radius:
                break
            if target.get('kind') == 'target' and target['id'] in targets and target['id'] not in run.completed:
                run.completed.append(target['id'])
            finish(accumulator, False)
            next_index += 1
            accumulator = new_leg()
            accumulator['end_t_s'] = rec['t_s']
        run.log.append(rec)
    if accumulator['_dt'] > 0:
        finish(accumulator, True)
    run.t, run.pct = rows[-1]['t_s'], rows[-1]['battery_pct']
    run.provenance = {
        'kind': 'csv_telemetry', 'real_qgc_format_verified': False,
        'energy_source': run.energy_source, 'energy_estimated': run.energy_estimated,
        'calibration_eligible': not run.energy_estimated,
        'column_map': mapping, 'time_scale': scale, 'sample_count': len(rows),
        'observed_wh': used, 'arrival_radius_m_3d': radius,
        'route_completed': next_index == len(route),
        'prediction_basis': 'uncalibrated physical model of sampled flown trajectory; not original planned legs',
        'altitude_assumption': 'CSV metres share plan.path altitude datum; caller must verify',
        'limits': 'No inferred takeoff/landing, waypoint dwell or action completion; GNSS sampling may miss arrivals.',
    }
    return run
