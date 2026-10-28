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
// 0306 新增 46 句：舊20句與3個模型驗證原封保留。
const extraCases = [
    [
        "風數計放大一點",
        "LAY_windGauge_SCALE_125"
    ],
    [
        "小地途縮小一點",
        "LAY_miniView_SCALE_80"
    ],
    [
        "姿太儀放大一點",
        "LAY_attitude_SCALE_125"
    ],
    [
        "任務進渡放大一點",
        "LAY_missionProgress_SCALE_125"
    ],
    [
        "拜託把 wind gauge 放大一點",
        "LAY_windGauge_SCALE_125"
    ],
    [
        "mini map 縮小一點啦",
        "LAY_miniView_SCALE_80"
    ],
    [
        "attitude indicator 放大一點",
        "LAY_attitude_SCALE_125"
    ],
    [
        "高度表縮小一點",
        "LAY_altReadout_SCALE_80"
    ],
    [
        "速度表放大一點",
        "LAY_speedReadout_SCALE_125"
    ],
    [
        "telemetry bar 隱藏",
        "LAY_telemetryBar_HIDE"
    ],
    [
        "heading tape 放大一點",
        "LAY_headingTape_SCALE_125"
    ],
    [
        "compass 縮小一點",
        "LAY_compass_SCALE_80"
    ],
    [
        "action dock 隱藏",
        ""
    ],
    [
        "payload rail 放大一點",
        "LAY_payloadRail_SCALE_125"
    ],
    [
        "home distance 縮小一點",
        "LAY_homeInfo_SCALE_80"
    ],
    [
        "progress bar 放大一點",
        "LAY_missionProgress_SCALE_125"
    ],
    [
        "風速計大一點啦",
        "LAY_windGauge_SCALE_125"
    ],
    [
        "麻煩小地圖小一點",
        "LAY_miniView_SCALE_80"
    ],
    [
        "高度顯示變成兩倍",
        "LAY_altReadout_SCALE_200"
    ],
    [
        "速度顯示減半吧",
        "LAY_speedReadout_SCALE_50"
    ],
    [
        "把姿態儀藏起來好嗎",
        ""
    ],
    [
        "底部遙測列先收起來",
        "LAY_telemetryBar_HIDE"
    ],
    [
        "指令區往右挪一點",
        "LAY_actionDock_NUDGE_R"
    ],
    [
        "風速計往下挪一點",
        "LAY_windGauge_NUDGE_D"
    ],
    [
        "把小地圖擺在右上角啦",
        "LAY_miniView_MOVE_TR"
    ],
    [
        "高度顯示放到左下角",
        "LAY_altReadout_MOVE_BL"
    ],
    [
        "風速計回到原本大小",
        "LAY_windGauge_RESET"
    ],
    [
        "重新顯示速度表",
        "LAY_speedReadout_SHOW"
    ],
    [
        "首頁狀態列放大一點",
        "LAY_homeStatus_SCALE_125"
    ],
    [
        "天氣卡縮小一點",
        "LAY_homeWeather_SCALE_80"
    ],
    [
        "系統詳情捷徑放大一點",
        "LAY_homeDetails_SCALE_125"
    ],
    [
        "即時飛行磚放大一點",
        "LAY_homeLiveTile_SCALE_125"
    ],
    [
        "任務規劃磚縮小一點",
        "LAY_homePlanTile_SCALE_80"
    ],
    [
        "任務庫磚隱藏",
        "LAY_homeLibraryTile_HIDE"
    ],
    [
        "weather card 放大一點",
        "LAY_homeWeather_SCALE_125"
    ],
    [
        "details shortcut 縮小一點",
        "LAY_homeDetails_SCALE_80"
    ],
    [
        "live tile 放大一點",
        "LAY_homeLiveTile_SCALE_125"
    ],
    [
        "plan tile 縮小一點",
        "LAY_homePlanTile_SCALE_80"
    ],
    [
        "library tile 隱藏",
        "LAY_homeLibraryTile_HIDE"
    ],
    [
        "home status 放大一點",
        "LAY_homeStatus_SCALE_125"
    ],
    [
        "這個放大一點",
        "LAY_windGauge_SCALE_125",
        {
            "page": 1,
            "modules": {
                "windGauge": {
                    "registered": true,
                    "visible": true
                }
            }
        }
    ],
    [
        "那個縮小一點",
        "LAY_miniView_SCALE_80",
        {
            "page": 1,
            "modules": {
                "miniView": {
                    "registered": true,
                    "visible": true
                }
            }
        }
    ],
    [
        "這塊藏起來",
        "LAY_homeWeather_HIDE",
        {
            "page": 0,
            "modules": {
                "homeWeather": {
                    "registered": true,
                    "visible": true
                }
            }
        }
    ],
    [
        "那塊放大一點",
        "LAY_homePlanTile_SCALE_125",
        {
            "page": 0,
            "modules": {
                "homePlanTile": {
                    "registered": true,
                    "visible": true
                }
            }
        }
    ],
    [
        "這個往右移",
        "LAY_homeStatus_NUDGE_R",
        {
            "page": 0,
            "modules": {
                "homeStatus": {
                    "registered": true,
                    "visible": true
                }
            }
        }
    ],
    [
        "那個還原大小",
        "LAY_homeDetails_RESET",
        {
            "page": 0,
            "modules": {
                "homeDetails": {
                    "registered": true,
                    "visible": true
                }
            }
        }
    ]
]
let fail = 0
for (const [q, id, extra] of extraCases) {
    const r = C.analyze(q, Object.assign({}, ctx, extra || {}))
    // id 為空字串：v3 鎖定模組（指令區、姿態儀）不可隱藏，預期 HOLD
    const ok = id === "" ? r.rule.decision === "HOLD" : (r.rule.decision === "SELECT" && r.rule.choice_id === id)
    if (!ok) fail++
    console.log((ok ? "PASS " : "FAIL ") + q + " → " + r.rule.decision + " " + r.rule.choice_id)
}
// 不同長度的兩個明確模組名稱，不可因名稱長短自動挑一個。
if (C.analyze("mini map 和 wind gauge 都放大一點", ctx).rule.decision !== "CLARIFY") fail++
// 多個可見模組時只列目前頁面的候選；不可從排序第一筆推斷「這個」。
const many = C.analyze("這個放大一點", {page:1, modules:{
    windGauge:{registered:true,visible:true}, miniView:{registered:true,visible:true},
    homeWeather:{registered:true,visible:true}
}})
if (many.rule.decision !== "CLARIFY" || many.candidates.some(c => c.kind === "layout" && !["windGauge","miniView"].includes(c.module))) fail++
for (const q of ["這個放大", "那個縮小"]) {
    const r = C.analyze(q, {page:1,modules:{windGauge:{registered:true,visible:false}}})
    if (r.rule.decision !== "HOLD" || !r.rule.final || r.candidates.length) fail++
}
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

// V4: new source fixtures only. Legacy fixture contents above are unchanged.
const v4Rows = require('fs').readFileSync(require('path').join(__dirname,'regression_ui_agent.jsonl'),'utf8')
    .split(/\r?\n/).filter(Boolean).map(JSON.parse).filter(row=>row.id.startsWith('UIV4-'))
for(const row of v4Rows) {
    let pending='', turnCtx={...row.ctx}
    for(const turn of row.turns||[{intent:row.intent,expect:row.expect}]) {
        const result=C.analyzeTurn(turn.intent,turnCtx,pending), d=result.rule
        const ids=d.decision==='SELECT'?(d.steps?d.steps.map(s=>s.choice_id):[d.choice_id]):[]
        const nextPending=d.decision==='SELECT'?'':result.pending_text||''
        const ex=turn.expect
        const ok=d.decision===ex.decision&&JSON.stringify(ids)===JSON.stringify(ex.ids)&&
            (ex.pending===undefined||nextPending===ex.pending)&&
            (ex.pending_original===undefined||(result.pending_intent||'')===ex.pending_original)&&
            (!ex.contains||ex.contains.every(id=>result.candidates.some(c=>c.id===id)))
        if(!ok)fail++
        console.log((ok?'PASS ':'FAIL ')+row.id+' '+turn.intent+' -> '+d.decision+' '+ids.join(','))
        for(const id of ids)turnCtx=C.afterCandidate(turnCtx,C.candidateById(result,id))
        pending=nextPending
    }
}
for(const q of ['小地圖放大','小地圖放到最大','小地圖縮到最小']) {
    if(C.analyze(q,{page:1,modules:{}}).candidates.some(c=>/^NAV_8_/.test(c.id)))fail++
}
// One navigation plus two layout actions remains executable; history behavior is in test_state_v4.js.
const compoundV4=C.analyze('切到即時飛行然後風速計放到最大然後小地圖放到最大',ctx)
if(compoundV4.rule.decision!=='SELECT'||compoundV4.rule.steps.length!==3)fail++
const noScope=C.analyze('將字縮小',{page:1,modules:{windGauge:{registered:true,visible:true},homeWeather:{registered:true,visible:true}}})
if(noScope.rule.decision!=='CLARIFY'||noScope.candidates.some(c=>c.kind==='layout'&&c.module!=='windGauge'))fail++
const pendingForModel=C.analyzeTurn('風速計',ctx,'放大一點')
const pendingMessage=JSON.parse(C.buildUserMessage(pendingForModel,ctx))
if(pendingMessage.pending_intent!=='放大一點'||pendingMessage.input_intent!=='風速計')fail++

console.log(fail ? fail + " 項失敗" : "全部通過")
process.exit(fail ? 1 : 0)
