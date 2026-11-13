.pragma library
// 告警面板的純邏輯（不碰 QML 物件，可用 node 測）。資料來源：gcs_demo.server 的 GET /api/alerts。
// 規則：等級與規則文字立即顯示；說明 rule_pending→生成中，llm→AI，其餘→規則。
// 「知道了」只收起注意／警告；嚴重（severity<=2）不能收起。同一則告警出新版本時重新出現。

var LEVELS = {
    5: { zh: "注意", color: "#FACC15" },
    4: { zh: "警告", color: "#FB923C" },
    2: { zh: "嚴重", color: "#EF4444" }
}

function levelOf(sev) {
    if (LEVELS[sev]) return LEVELS[sev]
    return sev <= 2 ? LEVELS[2] : (sev <= 4 ? LEVELS[4] : LEVELS[5])
}

function explainBadge(source) {
    if (source === "rule_pending") return { zh: "說明生成中…", kind: "pending" }
    if (source === "llm") return { zh: "AI", kind: "ai" }
    return { zh: "規則", kind: "rule" }
}

function dismissKey(a) {
    return String(a.alert_id || (a.key + "@" + a.t_s)) + "#" + String(a.alert_version === undefined ? 0 : a.alert_version)
}

function canDismiss(a) { return !(a.severity <= 2) }

// alerts: /api/alerts 的 alerts 陣列；dismissed: { key: true }
function cards(alerts, dismissed) {
    var out = []
    var list = alerts || []
    for (var i = 0; i < list.length; i++) {
        var a = list[i]
        if (a.active === false) continue
        var k = dismissKey(a)
        if (dismissed && dismissed[k] && canDismiss(a)) continue
        var lv = levelOf(a.severity)
        out.push({ key: k, severity: a.severity, levelZh: lv.zh, color: lv.color, title: a.title || "",
                   text: a.text_zh || "", badge: explainBadge(a.source), dismissible: canDismiss(a),
                   hold: (a.text_zh || "").indexOf("無符合條件方案") >= 0 })
    }
    out.sort(function (x, y) { return x.severity - y.severity })
    return out
}

// 示範情境：/api/plan 的回覆 → /api/start 的 body；沒有可用方案回 null
function startBody(plan) {
    if (!plan || !plan.candidates) return null
    var ok = function (c) { return c && c.feasible && !c.sorties }
    var pick = null
    for (var i = 0; i < plan.candidates.length; i++) {
        var c = plan.candidates[i]
        if (c.id === plan.rule_choice && ok(c)) pick = c
    }
    for (var j = 0; !pick && j < plan.candidates.length; j++) if (ok(plan.candidates[j])) pick = plan.candidates[j]
    return pick ? { mission_version: plan.mission_version, choice_id: pick.id } : null
}

if (typeof module !== "undefined") module.exports = { levelOf: levelOf, explainBadge: explainBadge, dismissKey: dismissKey,
    canDismiss: canDismiss, cards: cards, startBody: startBody }
