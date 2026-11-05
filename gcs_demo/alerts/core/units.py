"""Explicit current units and distinct battery quantities (contract sections 1/2)."""
from dataclasses import dataclass
import math
from collections.abc import Mapping


def finite(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def parse_current(raw_ca, source):
    """MAVLink centiamperes -> A. Only the integer sentinel -1 is missing."""
    if source not in ("SYS_STATUS", "BATTERY_STATUS"):
        raise ValueError("source must be SYS_STATUS or BATTERY_STATUS")
    if not isinstance(raw_ca, int) or isinstance(raw_ca, bool):
        raise ValueError("MAVLink current_battery must be an integer")
    return None if raw_ca == -1 else raw_ca / 100.0


def parse_current_csv(value, unit):
    """CSV values have no MAVLink sentinel: -1 A is a measurement, not missing."""
    scales = {"A": 1.0, "mA": 0.001, "10mA": 0.01, "cA": 0.01}
    if unit not in scales:
        raise ValueError("explicit supported current unit required")
    if value is None or (isinstance(value, str) and value.strip() == "--.--"):
        return None
    if isinstance(value, bool):
        raise ValueError("boolean current")
    try:
        amps = float(value) * scales[unit]
    except (TypeError, ValueError):
        raise ValueError("invalid CSV current") from None
    if not math.isfinite(amps):
        raise ValueError("nonfinite CSV current")
    return amps


@dataclass(frozen=True)
class CurrentLimits:
    min_current_a: float
    max_current_a: float


def check_current_range(amps, airframe):
    """No guessed physical limits. Missing current is invalid for P3 readiness."""
    if isinstance(airframe, Mapping):
        lo, hi = airframe["min_current_a"], airframe["max_current_a"]
    else:
        lo, hi = airframe.min_current_a, airframe.max_current_a
    if not finite(lo) or not finite(hi) or lo > hi:
        raise ValueError("invalid airframe current limits")
    return "valid" if finite(amps) and lo <= amps <= hi else "invalid"


@dataclass(frozen=True)
class BatteryQuantities:
    """fc_pct has its own denominator; never infer nominal_ratio from it."""
    fc_pct: float | None
    nominal_ratio: float
    usable_wh: float


def energy_from_nominal(nominal_wh, nominal_ratio, usable_fraction, *, fc_pct=None):
    """Apply usable fraction once to nominal Wh, never to an existing estimate.

    Passing BatteryQuantities back as nominal_wh is rejected. Recomputations
    must retain the original nominal capacity and independently calibrated SOC.
    """
    if (not finite(nominal_wh) or nominal_wh <= 0
            or not finite(nominal_ratio) or not 0 <= nominal_ratio <= 1
            or not finite(usable_fraction) or not 0 < usable_fraction <= 1
            or (fc_pct is not None and (not finite(fc_pct) or not 0 <= fc_pct <= 100))):
        raise ValueError("explicit nominal capacity, ratio and usable fraction required")
    return BatteryQuantities(fc_pct, nominal_ratio,
                             nominal_wh * nominal_ratio * usable_fraction)
