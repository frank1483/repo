"use strict";
// New arithmetic controls only. This does not invoke any prior research script.
const fs = require("fs"), path = require("path"), vm = require("vm"), assert = require("assert");
const file = path.join(__dirname, "../qml/GcpAgentThemeColorMath.js");
const M = vm.createContext({});
vm.runInContext(fs.readFileSync(file, "utf8").replace(/^\.pragma library\r?\n/, ""), M, {filename: file});
const rows = [];
function test(name, f) { try { f(); rows.push({name, pass: true}); } catch (e) { rows.push({name, pass: false, error: e.stack}); } }
function close(a, b, eps = 1e-10) { assert(Math.abs(a - b) <= eps, `${a} != ${b}`); }
test("hex/rgb/Chinese color inputs remain opaque and canonical", () => {
    assert.equal(M.parseInput(" #ab01cd ").color, "#AB01CD");
    assert.equal(M.parseInput("RGB(0, 128,255)").color, "#0080FF");
    assert.equal(M.parseInput("青色").color, "#00FFFF");
});
test("invalid, alpha, code-like and ambiguous requests clarify", () => {
    for (const value of ["#FFF", "#80FFFFFF", "#GG0000", "rgb(256,0,0)", "rgb(-1,0,0)", "rgba(0,0,0,1)",
        "海洋風", "eval('x')", "red", "藍色又紫色", "x".repeat(257), null]) assert.equal(M.parseInput(value).kind, "clarify");
});
test("relative requests do not invent host adjustment values", () => {
    assert.equal(M.parseInput("亮一點").direction, "lighter");
    assert.throws(() => M.relativeColor("#123456", "lighter"));
    assert(M.hsl(M.relativeColor("#123456", "lighter", 0.1)).l > M.hsl("#123456").l);
    assert(M.hsl(M.relativeColor("#123456", "darker", 0.1)).l < M.hsl("#123456").l);
    assert.equal(M.relativeColor("#808080", "warmer", 0.1), "#9A8067");
    assert.equal(M.relativeColor("#808080", "cooler", 0.1), "#67809A");
    assert.throws(() => M.relativeColor("#123456", "unknown", 0.1));
});
test("WCAG black/white ratio and identical colors", () => {
    close(M.contrast("#FFFFFF", ["#000000"]), 21);
    close(M.contrast("#000000", ["#FFFFFF"]), 21);
    close(M.contrast("#345678", ["#345678"]), 1);
    close(M.luminance(M.rgba("#FF0000")), 0.2126);
});
test("QML alpha is ARGB; foreground and nested panels composite before luminance", () => {
    const c = M.backdrop(["#000000", "#80FFFFFF"]); close(c.r, 128 / 255); close(c.a, 1);
    close(M.contrast("#FFFFFF", ["#000000", "#80FFFFFF"]), M.contrast("#FFFFFF", ["#808080"]));
    close(M.contrast("#00FFFFFF", ["#000000", "#80FFFFFF", "#40000000"]), 1);
    const nested = M.backdrop(["#000000", "#80FFFFFF", "#80000000"]);
    close(nested.r, (128 / 255) * (127 / 255));
    assert.throws(() => M.backdrop(["#80000000"]));
    assert.throws(() => M.luminance(M.rgba("#80000000")));
    assert.throws(() => M.backdrop([]));
});
test("source-over transparent and opaque endpoints", () => {
    const bg = M.rgba("#223344");
    close(M.composite(M.rgba("#00FFFFFF"), bg).r, bg.r);
    close(M.composite(M.rgba("#FFFFFFFF"), bg).r, 1);
    close(M.composite(M.rgba("#00000000"), M.rgba("#00000000")).a, 0);
    assert.throws(() => M.composite({r: 2, g: 0, b: 0, a: 1}, bg));
});
test("contrast roles use unrounded task thresholds for every supplied pair", () => {
    const colors = {fg: "#777777", secondary: "#949494", bg: "#FFFFFF", panel: "#00FFFFFF"};
    const pairs = [{id: "label", foreground: "fg", backgrounds: ["bg", "panel"], role: "normal"},
        {id: "icon", foreground: "secondary", backgrounds: ["bg"], role: "secondary"}];
    const result = M.checkPairs(colors, pairs);
    assert(!result.pass); assert(result.rows[0].ratio < 4.5); assert(result.rows[1].ratio > 3);
    assert.equal(result.rows[0].minimum, 4.5); assert.equal(result.rows[1].minimum, 3);
    assert.throws(() => M.checkPairs(colors, []));
    assert.throws(() => M.checkPairs(colors, [{...pairs[0], role: "guessed"}]));
    assert.throws(() => M.checkPairs(colors, [{...pairs[0], foreground: "missing"}]));
    assert.throws(() => M.checkPairs(colors, [pairs[0], pairs[0]]));
});
test("host recipes preserve alpha and reject undefined/nonfinite mix", () => {
    assert.equal(M.derive("#123456", 0, 1), "#123456");
    assert.equal(M.derive("#000000", 0.5, 0.5), "#80808080");
    assert.equal(M.derive("#FFFFFF", -1, 1), "#000000");
    assert.throws(() => M.derive("#123456", NaN, 1));
    assert.throws(() => M.derive("#123456", 0, 2));
});
test("HSL conversion roundtrips 216 RGB colors and wraps hue", () => {
    for (const r of [0, 51, 102, 153, 204, 255]) for (const g of [0, 51, 102, 153, 204, 255])
        for (const b of [0, 51, 102, 153, 204, 255]) {
            const value = "#" + [r, g, b].map(n => n.toString(16).padStart(2, "0")).join("").toUpperCase();
            const c = M.hsl(value); assert.equal(M.fromHsl(c.h, c.s, c.l), value);
        }
    assert.equal(M.fromHsl(360, 1, 0.5), "#FF0000");
    assert.equal(M.fromHsl(-120, 1, 0.5), "#0000FF");
});
test("lightness correction checks the final quantized color and requires confirmation", () => {
    const original = "#777777", pass = c => M.contrast(c, ["#FFFFFF"]) >= 4.5;
    const result = M.fitLightness(original, pass);
    assert(result.ok && result.confirmation && pass(result.color));
    assert.equal(result.requested, original); assert.notEqual(result.color, original);
    assert(result.checks <= 1026);
    const accepted = M.fitLightness("#000000", pass);
    assert(accepted.ok && !accepted.confirmation); assert.equal(accepted.checks, 1);
});
test("lightness repair checks mixed surfaces together; no partial success", () => {
    const pairs = [{id: "light", foreground: "fg", backgrounds: ["light"], role: "normal"},
        {id: "dark", foreground: "fg", backgrounds: ["dark"], role: "normal"}];
    const r = M.fitLightness("#00FFFF", fg => M.checkPairs({fg, light: "#FFFFFF", dark: "#000000"}, pairs).pass);
    assert(r.ok); assert(M.checkPairs({fg: r.color, light: "#FFFFFF", dark: "#000000"}, pairs).pass);
    const impossible = M.fitLightness("#112233", () => false);
    assert(!impossible.ok); assert.equal(impossible.color, null); assert(impossible.checks <= 1026);
    assert.throws(() => M.fitLightness("#112233", () => ({pass: true})));
});
test("status guard requires actual palette and explicit policy; hues wrap", () => {
    assert(!M.safeAccent("#FF0000", ["#FF0000"], 20));
    assert(M.safeAccent("#0000FF", ["#FF0000", "#FFFF00", "#00FF00"], 20));
    assert(M.safeAccent("#FFFFFF", ["#FF0000"], 20));
    close(M.hueDistance(359, 1), 2);
    assert.throws(() => M.safeAccent("#0000FF", [], 20));
    assert.throws(() => M.safeAccent("#0000FF", ["#FF0000"]));
});
test("accent suggestion is safe after quantization and never silently applies", () => {
    const statuses = ["#FF0000", "#FFFF00", "#00FF00"];
    const result = M.fitAccent("#FF0000", statuses, 20, c => M.contrast(c, ["#000000"]) >= 4.5);
    assert(result.ok && result.confirmation); assert.equal(result.requested, "#FF0000");
    assert(M.safeAccent(result.color, statuses, 20)); assert(M.contrast(result.color, ["#000000"]) >= 4.5);
    assert.equal(result.reason, "status-hue-conflict");
    const unchanged = M.fitAccent("#00FFFF", statuses, 20, () => true);
    assert(unchanged.ok && !unchanged.confirmation && unchanged.color === "#00FFFF");
});
test("contradictory hue policy yields no candidate", () => {
    const result = M.fitAccent("#FF0000", ["#FF0000", "#00FF00", "#0000FF"], 180, () => true);
    assert(!result.ok); assert.equal(result.color, null);
});
test("input palettes, background pairs and original status colors remain unchanged", () => {
    const colors = {statusWarning: "#FF0000", label: "#FFFFFF", bg: "#000000"};
    const pairs = [{id: "label", foreground: "label", backgrounds: ["bg"], role: "normal"}];
    const statuses = ["#FF0000"], before = JSON.stringify({colors, pairs, statuses});
    M.checkPairs(colors, pairs); M.fitAccent("#FF0000", statuses, 20, () => true);
    assert.equal(JSON.stringify({colors, pairs, statuses}), before);
});
const report = {scope: "new pure color arithmetic controls; synthetic palettes, not UI defaults/runtime", cases: rows.length,
    passed: rows.filter(r => r.pass).length, rows};
console.log(JSON.stringify(report, null, 2));
if (report.passed !== report.cases) process.exitCode = 1;
