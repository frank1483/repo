# Opt-in Python P1-P5 atomic measured caller

`alerts.typed_full_orchestration.TypedFullMissionOrchestrator` composes the existing P1/P2/P3 orchestrator with independent P4 link-distance and P5 measured-wind predictors. Existing P1/P2/P3 and all other production files remain byte-for-byte unchanged. This batch does not wire a server, UI, report, planner or JS caller.

Constructor: `(vehicle, capacity_options, link_reference_id, link_options=None, wind_options=None, raise_ticks=3, clear_ticks=10, max_gap_s=30.0, max_samples=601)`. Existing children own option validation/defaults and their distinct reset/window rules. `max_gap_s` and `max_samples` configure the existing P1/P2/P3 caller; P4/P5 gap/window settings remain explicit child options, not silently synchronized. No new numeric integration policy is chosen.

`tick(sequence, measurement, request)`:

- measurement has exactly `mission`, `capacity`, `link`, `wind`. Mission/capacity use the established P1/P2/P3 objects. Link requires measured `t_s`, `distance_m`, `link_pct`; wind requires measured `t_s`, `wind_mps`.
- request has exactly `mission`, `capacity_session_id`, `link`. The first two retain the established P1/P2/P3 request. Link has exactly `reference_id`, `probes`; each explicit probe retains P4's `id`, `distance_m`, `eta_s` schema. The reference must match the constructor. Geometry, distances and ETA are caller inputs; this layer does not derive or verify them.
- All measured timestamps must match, as must P1/P2 and P5 measured wind speed. Existing mission/capacity SOC equality and battery-session/new-mission-version condition remain enforced.
- Child state is deep-copied; all five predictors and final finite JSON serialization must succeed before replacing original state. Any malformed input or late exception consumes no original child state. An unknown/unsupported prediction is a valid sample and commits its own unknown/reset rules.
- Output preserves P1/P2/P3 provenance and every false feasibility/action/verification flag, adds P4/P5 outputs and events with source identities, per-predictor resets, explicit link reference, and lists P1-P5 as evaluated. Empty unassessed list means these five predictors ran; it is not physical feasibility, sensor validity, independent evidence, landing coverage, a continuous return deadline or permission to act.

Tests import only helper functions from the existing test_typed_orchestration module; they do not select or run that module's passed test classes. Run the new module alone. JS parity, candidates/geometry, endpoint/landing, typed UI/report and T6/T7 remain separate pending work. No model, training, device or board execution is included.
