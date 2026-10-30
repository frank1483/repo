# miniView host frame adapter — part4

This increment adds GcpAgentHost.js and State.readableHostInput(viewport, goal, candidates). It does not enable Overlay or auto-repair execution.

Host policy must supply kind=readable, minWidth, minHeight, allowMove, allowShrink, allowNavigate. There are no default minimums or repair permissions. Use Loop.goalTemplate candidates as trusted host output; do not accept model-generated expectations, policy or geometry.

After layout settles, call State.readableHostInput with the common viewport. The adapter requires a direct-child miniView in its executor container, a measured translation-only container-to-viewport mapping and target transforms matching State's override. It checks corners/midpoint and unit basis; rotated/scaled containers, extra target transforms, clipped ancestors, layered rendering and oversized geometry fail closed. The existing Snapshot and Catalog remain the source of measured AABB and trusted expectations.

All registered visible current-page obstacles are converted from viewport coordinates into the miniView container. This includes modules in other containers. The later Loop executor must remeasure and use this same obstacle inventory: State.otherRects currently covers only one container. Do not assume the old executor uses the new full inventory. Actual steps and final state still need verification/rollback.

Call Host.prepareReadable(input, Core, Catalog). Display its full summary and permission values in the confirmation card. This helper returns card text, not a rendered or approved card. Minimums are in QML scene units, not physical pixels or a measured reading score. Bounds do not prove text/font legibility.

After explicit operator confirmation, capture again and call Host.assertReadableCurrent(prepared, fresh, Core, Catalog). This compares revision, page/section, geometry, opacity, overrides, candidates and policy, and rebuilds a detached spec. A changed input requires a new card. The State method also rejects a revision/location change during capture. This is a synchronous pre-start guard, not a layout-settled scheduler or persistent transaction lifecycle guard. Never serialize an untrusted model-supplied confirmation object into these host methods.

Only then may a future Overlay bridge create Loop with owned-group ports and start(true). The word true in the new in-memory control is simulated host confirmation, not human_approved or training_release.

Remaining: actual confirmation card wiring and layout, Overlay-to-Loop ports, fresh geometry after each step, model repair feedback, cancellation/destruction/timeouts, install/CMake, text regression, conditional Qt harness waits. This batch has no Qt runtime, real model, native Git apply, QGC renderer or device evidence.
