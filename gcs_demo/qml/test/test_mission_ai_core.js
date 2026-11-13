"use strict";
// node gcs_demo/qml/test/test_mission_ai_core.js
const assert = require("assert"), fs = require("fs"), path = require("path"), vm = require("vm");
const src = fs.readFileSync(path.join(__dirname, "../GcpMissionAiCore.js"), "utf8").replace(/^\.pragma library/m, "");
const ctx = { module: { exports: {} } }; vm.createContext(ctx); vm.runInContext(src, ctx);
const C = ctx.module.exports;
const same = (a, b) => assert.strictEqual(JSON.stringify(a), JSON.stringify(b));
let n = 0; function t(name, f) { f(); n++; console.log("ok " + name); }

const wps = [{ lat: 24.79, lon: 121.0, alt: 50 }, { lat: 24.793, lon: 120.996, alt: 50 }, { lat: 24.7915, lon: 120.99, alt: 60 }];
t("mission body ids, required flags and home", () => {
    const b = C.missionBody(wps, { lat: 24.786, lon: 120.997 }, { WP2: true }, 8, "x");
    same(b.targets.map(x => [x.id, x.required]), [["WP1", true], ["WP2", false], ["WP3", true]]);
    assert.strictEqual(b.cruise_alt_m, 50); assert.strictEqual(b.home.lat, 24.786);
    assert.strictEqual(C.missionBody([], { lat: 0, lon: 0 }), null);
});
t("signature changes when a waypoint moves", () => {
    const a = C.missionBody(wps, wps[0], {}), b = C.missionBody(wps.map((p, i) => i ? p : Object.assign({}, p, { lat: 24.8 })), wps[0], {});
    assert.notStrictEqual(C.signature(a), C.signature(b));
});
t("reorder keeps only existing coordinates and reports dropped optional points", () => {
    const r = C.reorder(wps, { id: "C5", feasible: true, order: ["WP3", "WP1"] });
    same(r.points, [wps[2], wps[0]]); same(r.dropped, ["WP2"]);
});
t("reorder refuses infeasible, two-sortie, unknown or duplicate ids", () => {
    assert.strictEqual(C.reorder(wps, { feasible: false, order: ["WP1"] }), null);
    assert.strictEqual(C.reorder(wps, { feasible: true, sorties: [{}], order: ["WP1"] }), null);
    assert.strictEqual(C.reorder(wps, { feasible: true, order: ["WP9"] }), null);
    assert.strictEqual(C.reorder(wps, { feasible: true, order: ["WP1", "WP1"] }), null);
});
t("source tags say when the model fell back to rules", () => {
    assert.strictEqual(C.sourceTag({ source: "llm" }).zh, "模型選擇");
    assert.strictEqual(C.sourceTag({ source: "rule", llm: { ok: false } }).zh, "規則（模型未成功，已退回）");
    assert.strictEqual(C.sourceTag({ source: "rule", llm: null }).zh, "規則");
    assert.strictEqual(C.reportTag({ source: "rule", llm: { ok: false } }).zh, "規則撰寫（模型未成功，已退回）");
});
t("picked id falls back to the rule choice on HOLD", () => {
    assert.strictEqual(C.pickedId({ pick: { choice_id: "" }, rule_choice: "C3" }), "C3");
    assert.strictEqual(C.pickedId({ pick: { choice_id: "C5" }, rule_choice: "C3" }), "C5");
});
console.log(JSON.stringify({ cases: n }));
