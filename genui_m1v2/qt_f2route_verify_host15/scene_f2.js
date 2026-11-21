.pragma library
// host15：F2 接進問答流程的情境（gate-m1-0.5、tools-m1-0.6、claims-m1-0.6）。QML 與 node 共用同一份；模組由呼叫端傳入。
// 說明 f2_deviation_v1/F2_接進問答流程_說明_v2 §4，使用者 11/21 12:51、13:11 裁決。
var F2_Q = ["上一趟偏離航線多遠？", "最近一次有沒有偏移？", "離規劃航線最遠多少？", "離規劃航線多遠", "上一趟偏了多遠？", "這趟偏離任務多少", "上一趟偏多少",
            "最近一次偏離航點多遠", "上一趟偏離路線了嗎", "GPS 正常嗎，上一趟偏離航線多遠", "拿上一趟和目前載入的航線比較，偏離多遠？"]
var GENERAL_Q = ["GPS 為什麼偏移？", "上一趟 GPS 偏移多少？", "位置偏移了嗎？", "偏移是什麼意思？", "航線上的 GPS 偏移多少", "上一趟定位偏移多少", "羅盤偏移怎麼校正",
                 "磁力計偏移是什麼意思", "訊號偏移了嗎", "上一趟為什麼偏離航線？", "偏移量", "雲台偏移了", "高度偏移多少", "上一趟飛了多久？", "現在電量多少",
                 "規劃一條巡檢航線", "航線怎麼設定", "最近一次告警", "圖表偏移了", "位置是否偏移", "GPS 偏移多少公尺", "定位偏移太大"]
var R = 6371008.8
function deg(m) { return m / R * 180 / Math.PI }
function route5(northM) { var w = []; for (var i = 0; i < 5; ++i) w.push({ seq: i, lat: deg(northM), lon: deg(100 * i) }); return w }
function samples() { var s = []; for (var t = 0; t <= 60; ++t) s.push({ t: t, lat: deg(3 + 8 * Math.sin(Math.PI * t / 60)), lon: deg(400 * t / 60) }); return s }
var SCENES = [
    { name: "ok_record", q: "上一趟偏離航線多遠？", loadedNorth: 0.8 },
    { name: "explicit", q: "拿上一趟和目前載入的航線比較，偏離多遠？", loadedNorth: 5 },
    { name: "deferred", q: "上一趟偏離航線多遠、飛了多久？", loadedNorth: 0 },
    { name: "mismatch", q: "上一趟偏離航線多遠？", loadedNorth: 1.2 }
]
function intents(G) {
    var out = []
    function one(q) { var r = G.route(q); return { q: q, cls: r.gate["class"], rule: r.gate.rule_no, tools: r.tools, op: r.flightlog_op, basis: r.route_basis, deferred: r.deferred_asks } }
    for (var i = 0; i < F2_Q.length; ++i) out.push(one(F2_Q[i]))
    for (i = 0; i < GENERAL_Q.length; ++i) out.push(one(GENERAL_Q[i]))
    return out
}
// 每個情境：路由 → 工具（航線核對）→ 回答 → 排版計畫
function build(G, T, C, L, sc) {
    var r = G.route(sc.q), rec = { samples: samples(), t0: 0, t1: 60, gaps: [], mission_waypoints: route5(0) }
    var res = [T.deviationForRecord(rec, route5(sc.loadedNorth), r.route_basis)]
    var a = C.answer(res, { deferred_asks: r.deferred_asks, tool_order: r.tools }), p = L.plan("r_" + sc.name, a, res)
    return { name: sc.name, route: { cls: r.gate["class"], tools: r.tools, op: r.flightlog_op, basis: r.route_basis, deferred: r.deferred_asks },
             status: res[0].status, reason: res[0].detail ? (res[0].detail.unavailable_reason || null) : null,
             max: res[0].facts[1] ? res[0].facts[1].value : null, mean: res[0].facts[2] ? res[0].facts[2].value : null,
             lines: a.lines.map(function (l) { return l.template_id + "|" + l.text }), comps: p.nodes.map(function (n) { return n.component_id }),
             sd: { res: res, answer: a, plan: p } }
}
