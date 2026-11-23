.pragma library
// AiAgent 面板的純函式（說明 v3，2026-11-23）：不碰畫面，node 可直接測。
// 面板把 Agent 服務回來的提案翻成按鈕；真正改畫面時一律再過 UI agent 的 gateSelection。

var ROUTE_MAX_POINTS = 60
var PLANNER_PAGE = 2
var TELEMETRY_PAGE = 6
var REPORT_SECTION = 8           // GcpTelemetrySubNav.View.MissionReport（MVP 插槽加的第 9 項）
// 淺色主題：UI agent 沒有內建淺色捷徑，這裡固定三組顏色，套用前仍逐組走 UI agent 的 preview 與對比檢查
var LIGHT_ACTIONS = [{ group: "background", color: "#F3F4F6" }, { group: "text", color: "#111827" }, { group: "accent", color: "#0E7490" }]

var STATE_ZH = { PROPOSED: "待套用", PREVIEW: "預覽", APPLIED: "已套用", UNDONE: "已復原", APPLY_FAILED: "套用失敗" }
var DIR_ZH = { plan: "規劃", ui: "介面", manual: "手冊", qa: "問答", report: "報告", model: "模型", flight: "飛控" }
var POLISH_REASON_ZH = { format: "格式不對", slots: "佔位符不符", own_number: "自己寫了數字", forbidden_claim: "宣稱已執行",
    too_long: "太長", charset: "有不允許的字元", timeout: "超過 20 秒", model_error: "模型錯誤", no_model: "規則模式不潤飾",
    alert_active: "告警處理中讓出" }
var SOURCE_ZH = { model: "模型", rule: "規則退回", plan: "計畫" }

function planTitle(plan) {
    return plan === "B" ? "方案 B（結構化計畫）" : "方案 A（逐步迴圈）"
}

function stateZh(s) { return STATE_ZH[s] || (s ? String(s) : "") }
function dirZh(d) { return DIR_ZH[d] || (d ? String(d) : "") }

// 只接受有限數字、合理範圍的航點；任何一點不合格就整條拒絕
function checkedPoints(points) {
    if (!points || typeof points.length !== "number" || points.length < 1 || points.length > ROUTE_MAX_POINTS) return null
    var out = []
    for (var i = 0; i < points.length; ++i) {
        var p = points[i] || {}
        var lat = Number(p.lat), lon = Number(p.lon), alt = p.alt === undefined ? 50 : Number(p.alt)
        if (!isFinite(lat) || !isFinite(lon) || !isFinite(alt) || Math.abs(lat) > 90 || Math.abs(lon) > 180 || alt < 0 || alt > 500)
            return null
        out.push({ lat: lat, lon: lon, alt: alt })
    }
    return out
}

// 面板能套用的種類：route / text_scale / layout / theme / model；其他只顯示
function applyKind(p) {
    if (!p || !p.supported || !p.ui) return ""
    var k = p.ui.kind
    return ["route", "text_scale", "layout", "theme", "model"].indexOf(k) >= 0 ? k : ""
}

// 提案目前能不能按「套用」
function canApply(p, applied) {
    return applyKind(p) !== "" && !applied &&
        (p.state === "PROPOSED" || p.state === "PREVIEW" || p.state === "UNDONE" || p.state === "APPLY_FAILED")
}

// 送進 UI agent 檢查用的候選（只取 Core 認得的欄位，不帶服務端多給的鍵）
function agentCandidate(ui) {
    if (!ui || (ui.kind !== "layout" && ui.kind !== "text_scale")) return null
    var c = { id: String(ui.id || ""), kind: ui.kind, label_zh: String(ui.label_zh || "") }
    if (ui.kind === "text_scale") c.value = ui.value
    else {
        c.module = ui.module
        c.op = ui.op
        if (ui.op === "move") c.region = ui.region
        if (ui.op === "scale") c.factor = ui.factor
    }
    return c
}

// 步驟列（A：逐步；B：計畫）；來源 model＝模型選的、rule＝模型不合格改用規則、plan＝B 的計畫步驟
function stepLines(steps) {
    var out = []
    for (var i = 0; i < (steps || []).length; ++i) {
        var s = steps[i] || {}
        var src = SOURCE_ZH[s.source] || (s.source ? String(s.source) : "")
        out.push((i + 1) + ". [" + dirZh(s.direction) + "] " + (s.action || "") +
                 ((s.ids || []).length ? " " + s.ids.join("、") : "") + (src ? "（" + src + "）" : ""))
    }
    return out
}

function timing(v) {
    if (!v) return ""
    var parts = []
    if (v.t_pre_summary_s !== undefined && v.t_pre_summary_s !== null) parts.push("提案就緒 " + Number(v.t_pre_summary_s).toFixed(1) + " 秒")
    if (v.elapsed_s !== undefined && v.elapsed_s !== null) parts.push("含潤飾總時間 " + Number(v.elapsed_s).toFixed(1) + " 秒")
    parts.push("LLM 呼叫 " + (v.model_calls || 0) + " 次（含潤飾 " + (v.polish_calls || 0) + " 次）")
    parts.push("embedding " + (v.embed_calls || 0) + " 次")
    return parts.join("，")
}

function replySourceZh(v) {
    if (!v) return ""
    if (v.reply_source === "polished") return "模型潤飾"
    var src = String(v.reply_source || "")
    var reason = src.indexOf("fallback:") === 0 ? src.slice(9) : (v.polish && v.polish.reason ? v.polish.reason : "")
    return "模板" + (reason ? "（潤飾退回：" + (POLISH_REASON_ZH[reason] || reason) + "）" : "")
}

function outcomeLines(outcomes) {
    var out = []
    for (var k in (outcomes || {})) out.push(k + "：" + outcomes[k])
    return out
}
