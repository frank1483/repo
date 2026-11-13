// node gcs_demo/alerts/qml/test/test_alerts_core.js
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert")
const src = fs.readFileSync(path.join(__dirname, "..", "GcpAiAlertsCore.js"), "utf8").replace(/^\.pragma library/, "")
const m = { exports: {} }; vm.runInNewContext(src, { module: m, String, Number }); const C = m.exports
const A = (o) => Object.assign({ key: "battery", t_s: 10, severity: 4, title: "電量", text_zh: "警告：電量", source: "rule",
                                 alert_id: "a1", alert_version: 1, active: true }, o)
let n = 0; const t = (name, f) => { f(); n++; console.log("ok", name) }
t("levels", () => { assert.equal(C.levelOf(5).zh, "注意"); assert.equal(C.levelOf(4).zh, "警告"); assert.equal(C.levelOf(2).zh, "嚴重") })
t("badges", () => { assert.equal(C.explainBadge("rule_pending").kind, "pending"); assert.equal(C.explainBadge("llm").kind, "ai"); assert.equal(C.explainBadge("rule").kind, "rule") })
t("inactive hidden", () => assert.equal(C.cards([A({ active: false })], {}).length, 0))
t("dismiss warn", () => { const a = A(); assert.equal(C.cards([a], { [C.dismissKey(a)]: true }).length, 0) })
t("critical cannot be dismissed", () => { const a = A({ severity: 2 }); const c = C.cards([a], { [C.dismissKey(a)]: true }); assert.equal(c.length, 1); assert.equal(c[0].dismissible, false) })
t("new version reappears", () => { const a = A(); const d = { [C.dismissKey(a)]: true }; assert.equal(C.cards([A({ alert_version: 2 })], d).length, 1) })
t("sorted by severity, hold flag", () => { const c = C.cards([A({ alert_id: "x", severity: 5 }), A({ alert_id: "y", severity: 2, text_zh: "無符合條件方案，請人工決策" })], {}); assert.equal(c[0].severity, 2); assert.ok(c[0].hold) })
t("startBody prefers rule_choice", () => {
  const p = { mission_version: "v", rule_choice: "C2", candidates: [{ id: "C1", feasible: true }, { id: "C2", feasible: true }] }
  assert.deepEqual(C.startBody(p), { mission_version: "v", choice_id: "C2" })
  assert.equal(C.startBody({ candidates: [{ id: "S1", feasible: true, sorties: [1] }] }), null)
  assert.equal(C.startBody({ rule_choice: "C1", mission_version: "v", candidates: [{ id: "C1", feasible: false }, { id: "C3", feasible: true }] }).choice_id, "C3")
})
console.log(n + " tests OK")
