# Source-backed palette increment (partial)

AI 共同決定（使用者委任）。Recipes and illustrative contrast pairs are AI drafts. No human approval or training release.

This payload adds `qml/GcpAgentThemePalette.js` after theme_batch1. It consumes the byte-identical `GcpAgentThemeColorMath.js`. It does not install either file, change GcpThemeColor bindings, invoke a model or mutate State. Do not describe this as the completed free-color UI.

## Source identity

Theme SHA256: `0c7ee3ca010b8a029d38e3d5d4d22d9b884d2b091fdbdc224cdc0ef6aeec0f85`. Theme and CMake were copied by Claude from local ELAN_GCP_ui, no Git commit supplied. Integrated UI parity remains pending. All 177 original color expressions were parsed locally as hex, Qt.rgba or an alias, resolving aliases before overrides. Exact real RGBA alpha is retained (e.g.0.05 rather than rounded 13/255).

The nine accent tokens, ten background tokens and four text tokens are explicit in GROUP_TOKENS. Every other token remains at its original resolved RGBA. GPS/status/telemetry/map/video/danger/alert colors are excluded, including gpsFixed and statusInfo which originally alias primary. A later QML binding patch MUST break these two mutable dependencies while retaining their original resolved cyan; leaving their original `primary` expressions would violate the protection requirement. videoSignalBackground aliases the immutable neutral600 and remains unchanged.

## Host interfaces

`materialize(groups)` accepts only `{accent?,background?,text?}` with opaque #RRGGBB values and returns the full RGBA palette. Empty groups returns exact original values. Recipes keep source HSL offsets within each family, adopt requested background hue/saturation and preserve source alpha. This is a source-derived draft recipe, not a perceptual or brand-design equivalence claim. Explicitly choosing the original base may quantize other derived RGB values; reset must use empty groups to obtain exact defaults.

`preview(currentGroups,{group,color},policy)` accepts structured values from user/program/model and returns `confirm` or `unavailable`. `fromInput` also parses the prior module's Chinese names, hex, rgb and relative phrases. Unresolved input such as 海洋風 returns CLARIFY. No model call occurs. Relative input requires explicit policy.relativeAmount.

Policy is a TRUSTED HOST object, never model output:

```
{
  sourceThemeSha256: <the exact hash above>,
  scope: "host-declared-static-pairs",
  minimumHueDistance: <required host number; NO default>,
  pairs: [{id, foreground:<token>, backgrounds:[<opaque bottom token>,...], role:"normal"|"secondary"}],
  relativeAmount: <required only for relative input>
}
```

No shipped runtime policy is supplied. `candidate_contrast_draft.json` uses 20 degrees solely as a synthetic test fixture. Neither that number nor the illustrative pair roles are approved integration values. Ratios use exact real-alpha compositing; normal>=4.5 and explicitly secondary>=3. The coverage claim is always declared-static-pairs-only; a passing partial table cannot certify all UI references. Hue/lightness fit uses the earlier bounded discrete search and quantized RGB checks, not a continuous optimum or perceptual-confusion guarantee.

`validatedCommit(currentGroups,proposal,policy,true)` is a pure pre-commit recheck. It rejects stale group maps, changed host pair/hue policy, tampered groups/swatches, unconfirmed calls and newly failing palettes; returns a detached group map. The next increment must call it immediately before State.beginGroup, set the group map inside that transaction, then State.commitGroup. It must recheck at the real second-layer action boundary. This function itself performs neither the State transaction nor the full requested two-layer safety feature.

## Remaining integration

State must own theme group values, include them in snapshot/restore/undo/redo/layoutFingerprint/checkedLayout/named and current layout persistence, and clear them on default/reset. Backward layouts without theme fields keep original defaults. Load saved layouts only after trusted policy/identity is ready; do not mark an otherwise valid saved theme corrupt merely because policy arrives later. Preserve source/settings and rollback on failure.

Then bind the 23 formal GcpThemeColor tokens to materialized RGBA while leaving untouched fallback expressions verbatim, pin gpsFixed/statusInfo to their resolved original value, and register both JS files in the real installer/CMake assets. Build host pair inventory for all affected render paths before activation. GcpPanel blurSource and fillOverride mean a guessed bgBase behind every panel is unsound. Map/video/photo backdrops require measured/worst-case evidence, independently from their protected token values. Primary button normal/hover/pressed pair with textOnPrimary; disabled and Danger paths have distinct semantics. Do not substitute the eight illustrative test pairs for this inventory.

Finally connect model-values-only channel, all named shortcuts/high contrast/reset, picker, requested/actual swatches, explicit confirmation, unsaved undo/save/dismiss row, and full new Qt interaction controls. Separate safety patch, then text regression; mission part_u source f1fa869 pending per0387; model feedback remains on hold.
