// node test/test_core.js：決策核心的意圖→候選／決策檢查（不需 Qt）
const C = require("./load_core.js")
const ctx = { page: 0, section: -1, modules: {}, canUndo: true, canRedo: true }
const cases = [
    ["我想查看飛行設定", "CLARIFY", ""],
    ["打開系統設定的 Fly View", "SELECT", "NAV_8_11"],
    ["去告警中心", "SELECT", "NAV_4"],
    ["首頁", "HOLD", ""],                       // 已在首頁 → 降分，不重複切換
    ["帶我去看電池失效保護", "SELECT", "NAV_3_1"],
    ["我要校正羅盤", "SELECT", "NAV_5_4"],
    ["把風速計移到左上角", "SELECT", "LAY_windGauge_MOVE_TL"],
    ["小地圖放大一點", "SELECT", "LAY_miniView_SCALE_125"],
    ["把高度顯示放大兩倍", "SELECT", "LAY_altReadout_SCALE_200"],
    ["隱藏底部遙測列", "SELECT", "LAY_telemetryBar_HIDE"],
    ["重新顯示高度顯示", "SELECT", "LAY_altReadout_SHOW"],
    ["風速計還原大小", "SELECT", "LAY_windGauge_RESET"],
    ["把指令區往左移", "SELECT", "LAY_actionDock_NUDGE_L"],
    ["復原", "SELECT", "UNDO"],
    ["復原兩步", "SELECT", "UNDO_2"],
    ["全部復原", "SELECT", "RESET_ALL"],
    ["重做", "SELECT", "REDO"],
    ["起飛", "HOLD", ""],
    ["返航", "HOLD", ""],
    ["帶我去返航設定", "SELECT", "NAV_3_0"],
]
let fail = 0
for (const [q, d, id] of cases) {
    const r = C.analyze(q, ctx)
    const ok = r.rule.decision === d && (!id || r.rule.choice_id === id)
    if (!ok) fail++
    console.log((ok ? "PASS " : "FAIL ") + q + " → " + r.rule.decision + " " + r.rule.choice_id)
}
// 模型輸出驗證：不在候選內的 ID、引用不存在的證據都要擋下
const r = C.analyze("我想查看飛行設定", ctx)
const v1 = C.validateModelDecision({ decision: "SELECT", choice_id: "NAV_99", evidence_ids: [] }, r)
const v2 = C.validateModelDecision({ decision: "SELECT", choice_id: "NAV_8_11", evidence_ids: ["E9"] }, r)
const v3 = C.validateModelDecision(C.extractJson('好的 {"decision":"SELECT","choice_id":"NAV_8_11","reason_zh":"x","evidence_ids":["E1"]}'), r)
for (const [name, ok] of [["擋下不存在的 ID", !v1.ok], ["擋下不存在的證據", !v2.ok], ["接受合法回覆（含前後雜字）", v3.ok]]) {
    if (!ok) fail++
    console.log((ok ? "PASS " : "FAIL ") + name)
}
console.log(fail ? fail + " 項失敗" : "全部通過")
process.exit(fail ? 1 : 0)
