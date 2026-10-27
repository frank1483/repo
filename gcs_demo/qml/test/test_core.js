// 0306: default runs only NEW boundaries. Existing nominal body preserved below.
// Claude may opt in to nominal comparison once with --with-nominal after assessing the no-rerun rule.
if (process.argv.includes("--with-nominal")) {
// node gcs_demo/qml/test/test_core.js  —— JS 移植和 Python 版逐候選比對，並測模型驗證與模擬報告
const assert = require("assert"), { execFileSync } = require("child_process"), path = require("path")
const C = require("./load_core")()
const root = path.join(__dirname, "..", "..", "..")
const py = JSON.parse(execFileSync("python3", ["-m", "gcs_demo.qml.test.dump_python"], { cwd: root }).toString())
let n = 0
function same(js, ref, label) {
    js = JSON.parse(JSON.stringify(js))  // vm 內的陣列和外面不是同一個 realm
    assert.strictEqual(js.rule_choice, ref.rule_choice, label + " rule_choice")
    assert.deepStrictEqual(js.candidates.map(c => c.id), ref.candidates.map(c => c.id), label + " ids")
    js.candidates.forEach((c, i) => {
        const r = ref.candidates[i]
        assert.deepStrictEqual(c.order, r.order, label + " " + c.id + " order")
        assert.strictEqual(c.feasible, r.feasible, label + " " + c.id + " feasible")
        for (const k of ["dist_km", "energy_wh", "end_pct", "speed_mps"]) assert(Math.abs(c[k] - r[k]) <= 0.11, `${label} ${c.id} ${k} ${c[k]} vs ${r[k]}`)
        n++
    })
}
const m = py.mission, w = C.wind(py.wind.speed_mps, py.wind.from_deg)
same(C.planMission(m, C.vehicle(), w), py.plan, "plan")
same(C.replan(m, C.vehicle(), w, py.state, py.event), py.replan, "replan")
same(C.planMission(m, C.vehicle({ calib: 1.2 }), C.wind(7, 200)), py.plan2, "plan2")

// 模型輸出驗證
const p = C.planMission(m, C.vehicle(), w)
assert.strictEqual(C.validatePick(p, '{"decision":"SELECT","choice_id":"ZZ","reason_zh":"x","evidence_ids":[]}').source, "rule")
const ok = C.validatePick(p, '```json\n{"decision":"SELECT","choice_id":"C5","reason_zh":"省電","evidence_ids":["E1","E99"]}\n```')
assert.strictEqual(JSON.stringify([ok.choice_id, ok.source, ok.evidence_ids]), JSON.stringify(["C5", "llm", ["E1"]]))
assert.strictEqual(C.validatePick(p, "").source, "rule")
assert.strictEqual(C.validatePick(p, '{"decision":"HOLD","choice_id":"","reason_zh":"不確定","evidence_ids":[]}').decision, "HOLD")

// 模擬：飛到預測告警 → 重規劃 → 報告
const v = C.vehicle(), plan = p.candidates.find(c => c.id === p.rule_choice)
const run = new C.MissionRun(v, w, 1.15, [{ t_s: 300, speed_mps: 9, from_deg: 240 }])
let st = run.fly(plan, 300)
assert(!st.done && st.observed_ratio > 1.05, "observed ratio learned")
const ev = { type: "wind", speed_mps: 9, from_deg: 240, text_zh: "風速增強" }
const rp = C.replan(m, v, w, st, ev)
assert(C.predictiveAlert(v, st, rp), "alert raised")
rp.final_choice = rp.rule_choice
st = run.fly(rp.candidates.find(c => c.id === rp.rule_choice))
assert(st.done && st.battery_pct >= v.reserve_pct - 3, "landed safely " + st.battery_pct)
const rep = C.makeReport(run, m, plan, [rp], [])
assert(rep.next_calib > 1.05 && rep.suggestions.length > 0)
const ids = rep.facts.map(f => f.id)
rep.suggestions.forEach(s => assert(s.evidence_ids.every(e => ids.includes(e))))
const llmRep = C.applyReportLlm(rep, JSON.stringify({ summary_zh: "摘要", suggestions: [{ text_zh: "有據", evidence_ids: ["F3"] }, { text_zh: "捏造", evidence_ids: ["F99"] }] }))
assert.strictEqual(JSON.stringify(llmRep.suggestions.map(s => s.text_zh)), JSON.stringify(["有據"]))
assert.strictEqual(C.applyReportLlm(rep, "垃圾").source, "rule")
console.log(`OK：${n} 個候選與 Python 版一致；模型驗證、模擬、報告測試通過`)

}
require("./test_boundaries_0306")(require("./load_core")())
