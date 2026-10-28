"""Report data quality, numeric grounding and sample-derived events (offline)."""
from __future__ import annotations

import copy
import math
import re
import statistics
import unicodedata

NUMBER = re.compile(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?')


def quality_for(run):
    if getattr(run, 'data_quality', None):
        return copy.deepcopy(run.data_quality)
    log = run.log
    gaps = [b['t_s']-a['t_s'] for a, b in zip(log, log[1:]) if b['t_s'] > a['t_s']]
    missing_wind = not log or any(r.get('wind_mps') is None or r.get('wind_from') is None for r in log)
    estimated = getattr(run, 'energy_estimated', False)
    return {'source': 'simulation_or_supplied_run', 'missing_wind': missing_wind,
            'missing_current': estimated, 'soc_estimated': estimated,
            'calibration_eligible': not estimated and not missing_wind,
            'sample_count': len(log), 'trimmed_samples': 0,
            'sample_interval_s': ({'min': min(gaps), 'median': statistics.median(gaps), 'max': max(gaps)} if gaps else None)}


def unsupported_numbers(texts, facts):
    """Check decimal tokens against fact text/value, at the output precision.

    This is a numeric presence check, not a check of units, causation or meaning.
    Signed numbers and scientific notation are supported; booleans are not numbers.
    """
    values = []

    def visit(value):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            if math.isfinite(value):
                values.append(float(value))
        elif isinstance(value, str):
            for token in NUMBER.findall(unicodedata.normalize('NFKC', value)):
                n = float(token)
                if math.isfinite(n):
                    values.append(n)
        elif isinstance(value, dict):
            for v in value.values():
                visit(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                visit(v)
    for fact in facts:
        visit(fact.get('text'))
        visit(fact.get('value'))
    bad = []
    for text in texts:
        for token in NUMBER.findall(unicodedata.normalize('NFKC', text)):
            value = float(token)
            mantissa, _, exponent = token.lower().partition('e')
            places = len(mantissa.split('.')[1]) if '.' in mantissa else 0
            try:
                tolerance = 0.5 * 10.0 ** (int(exponent or 0)-places)
            except OverflowError:
                tolerance = 0
            if not math.isfinite(value) or not any(abs(n-value) <= tolerance + 1e-10 for n in values):
                bad.append(token)
    return list(dict.fromkeys(bad))


def events_for(run, mission, replans, alerts):
    events = []
    airborne = False
    for i, row in enumerate(run.log):
        alt = row.get('alt')
        if alt is None:
            continue
        if not airborne and alt > 1:
            events.append({'kind': 'start_in_air' if i == 0 else 'takeoff', 't_s': row['t_s'],
                           'basis': 'altitude_threshold_inference'})
            airborne = True
        elif airborne and abs(alt) <= 1:
            # Avoid declaring a fly-by at low altitude a landing.
            speed = row.get('ground_speed_mps', math.hypot(row.get('vel_e', 0), row.get('vel_n', 0)))
            if speed <= 0.5 and not row.get('armed', False):
                events.append({'kind': 'landing', 't_s': row['t_s'], 'basis': 'stationary_ground_inference'})
                airborne = False
    target_ids = {t['id'] for t in mission['targets']}
    seen = set()
    for leg in run.legs:
        if (not leg.get('partial') and leg.get('to') in target_ids and leg['to'] not in seen
                and leg.get('end_t_s') is not None):
            seen.add(leg['to'])
            events.append({'kind': 'waypoint', 'target_id': leg['to'], 't_s': leg['end_t_s'],
                           'basis': 'sample_arrival_or_supplied_leg'})
    for r in replans:
        t = r.get('state', {}).get('t_s')
        if t is not None:
            events.append({'kind': 'replan', 't_s': t, 'choice_id': r.get('final_choice', r['pick'].get('choice_id', ''))})
    for a in alerts:
        if a.get('t_s') is not None:
            events.append({'kind': 'alert', 't_s': a['t_s'], 'text_zh': a.get('text_zh', '')})
    return sorted(events, key=lambda e: e['t_s'])


def timeline_text(events, limit=5):
    labels = {'takeoff': '起飛（推定）', 'start_in_air': '紀錄起點已在空中',
              'landing': '降落（推定）', 'waypoint': '到達航點', 'alert': '告警', 'replan': '重規劃'}
    parts = [f"{e['t_s']:.1f} 秒 {labels.get(e['kind'], e['kind'])}"
             + (" " + str(e.get('target_id') or e.get('choice_id') or '')) for e in events[:limit]]
    if len(events) > limit:
        parts.append(f"另 {len(events)-limit} 件，詳見結構化時間軸")
    return '事件時間軸（起降為取樣推定，不代表上鎖確認）：' + ('；'.join(p.strip() for p in parts) if parts else '無可推定事件')


def alert_leads(run, alerts):
    """Predict threshold crossing using only samples available at each alert.

    Generic alert.lead_s is intentionally ignored: it can describe PNR or other
    constraints instead of reserve crossing. No alert -> no lead-time field.
    """
    result = []
    for i, a in enumerate(alerts):
        now = a.get('t_s')
        if now is None:
            continue
        breach = a.get('predicted_reserve_breach_t_s')
        basis = 'caller_reserve_prediction'
        if breach is None:
            samples = [r for r in run.log if r['t_s'] <= now]
            if len(samples) < 2:
                continue
            p, q = samples[-2:]
            dt = q['t_s']-p['t_s']
            # No stale extrapolation beyond one observed sampling interval.
            if dt <= 0 or now-q['t_s'] > dt:
                continue
            slope = (q['battery_pct']-p['battery_pct'])/dt
            if slope >= 0:
                continue
            breach = q['t_s']+(run.v.reserve_pct-q['battery_pct'])/slope
            basis = 'linear_soc_at_alert_not_future_observation'
        if isinstance(breach, (int, float)) and math.isfinite(breach):
            result.append({'alert_index': i, 'alert_t_s': now, 'predicted_reserve_breach_t_s': breach,
                           'lead_s': max(0.0, breach-now), 'basis': basis})
    return result
