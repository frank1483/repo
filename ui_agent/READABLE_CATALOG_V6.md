# Readable miniView catalog: engineering increment 0362

This adds `qml/GcpAgentCatalog.js` and a new focused Node control suite. It does
not change Overlay, State, Core, Loop, the installer, CMake or a running UI.
Base: Claude's 40-file archive claiming commit
`6b526781b91326aadcad1a4922e6f56f0ef07056`. Commit identity is not locally verified.

`Catalog.buildReadableSpec(choiceId, host, Core)` builds a detached spec accepted
by the existing `Loop.create(spec, ports)`. Only the existing
`GOAL_MINIVIEW_READABLE` template is supported. General action plans, other maps,
text scale, hidden or off-page target geometry are outside this increment.

## Host interface

`choiceId` is an ID selected from the host-owned result of `Loop.goalTemplate`.
`host.candidates` is that trusted candidate list, not a model response.
The function requires:

- `revision`: current nonnegative integer State revision.
- `snapshot`: settled output compatible with `State.verificationSnapshot`.
- `goal`: `{kind: "readable", minWidth, minHeight, allowMove, allowShrink,
  allowNavigate}`. The host must show the minimums and all three repair
  permissions on its confirmation card. Do not infer permission from model text.
- `frame`: `{mapping: "translation-only", base, area, origin, override, others}`.
  `base` is the untransformed module rectangle in its container coordinates;
  `area` is the container size; `origin` is the container origin in the common
  verification viewport; `override` and `others` use the same container units
  as Core/State. The host must attest there is no inherited scale, rotation,
  clipping or unsupported transform. Current projected AABB must match the
  measured snapshot within 0.01 units. Each container axis is at most 32768;
  obstacles and host candidates are each at most 128.

The builder accepts only the current visible unlocked miniView on its Core page.
It strips the initial action down to known fields and constructs expectations
from host minimums and policy. A candidate that supplies `expected`, `before` or
`repairFor` is rejected. No supplied baseline can replace Loop's own snapshot.

## Repairs and semantics

The goal is semantic readability, visibility, viewport bounds and no prohibited
overlap, not an exact final scale or location. Minimum readable dimensions must
come from the host's confirmed product policy. No default dimensions are invented.
If the user requires an exact position or scale, use a different goal contract.

Move previews call existing `Core.layoutTarget`/`freeSpot`, check container and
common viewport bounds, minimum readable size and obstacle clearance, then remove
duplicate placements. A freeSpot no-space fallback is never advertised as clear.
A shrink candidate uses the existing relative factor 0.8, only when its preview
actually reduces size and stays above the unchanged minimum. Navigation targets
only the Core-declared miniView page; it does not authorize flight or parameter
changes. Repairs are marked `repairFor` this goal and scoped to failure codes.
Shrink is not offered for `TEXT_TRUNCATED`, since reducing size cannot prove a fix.

Previews describe the intake frame. Execution re-evaluates standard actions on
current host geometry; each action, logical goal and final goal must be verified
by the production Loop/Verifier. Shrink may still require a subsequent move.
Navigation's own expectation checks only its page, followed by the logical goal.
Repairs never lower the confirmed readable minimum or disable collision checks.

## Remaining integration

The returned `guard` is metadata; Loop does not enforce it. The future Overlay
adapter must check revision/page/section immediately before `Loop.start(true)`,
rebuild and reconfirm if stale, measure after layout changes, bind execution and
rollback to owned State groups, and provide a settled Qt snapshot after every
step. Closing/cancelling/destruction/timeout must invalidate callbacks and roll
back the owned group. Model feedback may select only offered IDs. Install/CMake
registration, host frame capture, lifecycle wiring and real Qt validation remain
pending. Importing this file alone does not enable a new UI execution path.

The current adapter only verifies registered-module AABBs and the existing
verifier's renderer coverage. It does not prove native video, popup, shader,
clipping or unregistered component visibility or typography correctness.

## Evidence

The new suite uses actual production Core, Loop and Verifier with in-memory
ports. First run failed because the test phrase did not match the existing goal
parser; its raw logs are preserved. After fixing only that fixture, 26 controls
passed. A subsequent bounded-coordinate guard and its new control brought the
final suite to 27/27. No old successful suite or research script was rerun.
There were no model calls, Qt execution, device actions or native Git/apply here.
