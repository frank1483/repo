# UI agent v4 acceptance (Claude runs and retains first results)

No comparison button is implemented (user-confirmed item 7).

- Home -> move wind gauge: first Undo restores geometry on flight page; next Undo returns Home. Redo replays each separately.
- Explicit navigation + two layout actions: one navigation step and one layout step. A failure after any substep restores original page, geometry, scale AND both history stacks; no automatic persistence.
- Toast after Undo shows Redo iff available; after Redo shows Undo; repeat clicks and expiry are checked.
- All 251 theme properties scale. Inspect every numeric font.pixelSize in the complete formal GCP source; supplied snapshot only contains one of the requested 84 lines. Never claim the other 83 are patched.
- Verify 0.85/1/1.15/1.3 at 1280x800 and 1920x1200; layout uiScale and appFontPointSize unchanged. Undo and named snapshots include textScale. Validate v2 legacy layouts without textScale.
- Pending request remains without timeout (wait >10 minutes); complete request/cancel/save/close clears it. Model request contains pending original. Cancel during a model request suppresses late callbacks. Scope-free font request offers global + visible current-page modules.
- Save via PANEL button, TOAST button and each of 儲存 / 存起來 / 儲存版面. Pending clears. Only these explicit paths (including named save) write Settings. Panel shows 未儲存 when layout/textScale differs from last saved snapshot; page-only navigation does not make it dirty.
- Restart without saving: unsaved edits disappear. Save then edit then restart: last SAVED layout/textScale return, page does not jump, modules apply on registration. Undo/Redo do not survive restart. Undo, Redo, defaults and reset-all change only memory until another explicit save.
- Corrupt savedLayoutJson is logged, defaults used and the original bytes retained through subsequent edits/restarts. Explicit save reports blocked pending recovery instead of overwriting corrupt data. Named layouts remain separate; invalid named store is not overwritten.
- Run unchanged old fixtures plus added v4 cases once, preserve the FIRST result even on failure. No live model, device or research script execution is part of this delivery.

## Missing formal source / integration handoff
Supply complete GCP QML files containing the remaining numeric font.pixelSize sites (including any nested font { pixelSize: ... } forms), and GCS_開發交接與變更紀錄.md. Existing formal snapshot is read-only. Claude must append the prepared handoff entry to that real root document when integrating. Do not describe the provisional font patch as full-system acceptance.
