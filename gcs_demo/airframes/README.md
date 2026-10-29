# T5a airframe profiles (engineering draft)

This batch provides profile files, validation, instantaneous electrical power,
airspeed range and a coordinated-turn primitive in Python and pure QML JS.
It does **not** enable fixed-wing/hybrid mission planning, best-speed search,
route energy, loiter, transition integration, RTL or uncertainty bounds yet.
Those legacy route functions deliberately reject fixed-wing/hybrid profiles.
Multirotor calculations and the no-profile serialized Vehicle payload retain
their previous behavior. No fitted data, SITL or aircraft validation is claimed.

- `x500.json`: legacy 2 kg, 90 Wh multirotor parameters, `source="assumed"`.
- `fw_example.json`, `vtol_example.json`: invented engineering placeholders,
  `source="placeholder"`. Their transition/capacity values are not measurements.
- SI units; percentages use 0–100. `limits` airspeeds are not ground speeds.
- `calib` is not included in instantaneous W; the legacy route caller multiplies
  energy by it. Applying learned calibration or changing profiles is not done here.

Python:

```python
from gcs_demo.energy import load_airframe, power_w, speed_range, turn_geometry
v = load_airframe("fw_example")   # or a local JSON path
watts = power_w(v, 16, bank_deg=20, climb_mps=2)
airspeed_limits = speed_range(v)  # includes 1.2 * stall margin
geometry = turn_geometry(v, 16)   # configured minimum radius, no path arc yet
```

Existing `Vehicle(...)` positional arguments remain valid. One optional trailing
`airframe_profile` field is appended. Use `load_airframe` to obtain a validated
profile. Python `v.type` and JS `airframeType(v)` read the profile's type. Profile
metadata is independent of the input and survives `to_dict()` / JSON export;
the old no-profile payload has no added key, preserving legacy version inputs.
Directly mutating a validated profile is outside this API; reload to validate it.

JS `loadAirframe(jsonContentsOrObject)` accepts the **same JSON**, not a file
path/id; QML performs the local read. This batch does not change QML wiring.
`powerW(v, vAir, mode, bankDeg, climbMps, advanceRatio)`, `speedRange(v, bankDeg)`
and `turnGeometry(v, vAir, bankDeg, radiusM)` mirror the Python optional arguments.
For VTOL, `power_w` / `powerW` require explicit `"mc"` or `"fw"`; this estimates
instantaneous power only and does not include transition energy.

Fixed-wing drag uses n = 1/cos(bank); only induced drag is multiplied by n².
Turn radius is V²/(g*abs(tan(bank))). A zero-bank turn reports `radius_m=null`
(straight flight), and min-radius and bank-adjusted stall limits are checked.
The turn stall floor is 1.2 * v_stall * sqrt(n). Positive climb adds mechanical
mass*g*vertical_speed divided by active propulsion efficiency in all three types;
negative climb has no energy recovery. Aerodynamic and climb efficiency are
engineering assumptions, not fitted results.

Optional propeller lookup lives at the JSON top level:

```json
{
  "prop_model": {"id":"user-supplied-id", "rpm":6000, "diameter_m":0.4},
  "eta_table": [[0.0, 0.4], [1.0, 0.8]]
}
```

The numbers above are **synthetic API examples**, not UIUC data. No efficiency
table is shipped in the three profiles. J is dimensionless: V/(rpm/60*diameter).
`prop_model` can also be an identifier string if the caller supplies measured J
as `advance_ratio`/`advanceRatio`. Explicit J overrides nominal RPM. Without a
table or without enough J context, use constant eta_prop. Linear interpolation
clamps outside table endpoints (no extrapolation); this is not validation of
performance outside the measured domain. The metadata identifier is never fetched
or resolved online. RPM and diameter are both optional but must appear together.

This draft rejects malformed tables, duplicate/unordered J, nonpositive efficiency,
unknown types/schemas, missing fixed-wing/transition fields and nonfinite numbers.
Unknown JSON fields survive for provenance. Reserved prototype keys are rejected
consistently in both languages. All persisted profile values are ordinary JSON.

Next integration must account for the same wind on outbound and RTL in bounds,
waypoint turn arc length, loiter, cmd 3000/launch/landing mode transitions, RTL
to_mc, ground-versus-air speed search, and profile-backed alert limits. Alert-only
link/freshness/urgent-RTL/hysteresis settings must remain outside these profiles.
