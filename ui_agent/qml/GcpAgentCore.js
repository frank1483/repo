.pragma library
// UI agent 的決策核心（純 JS，不依賴 Qt 物件，可用 node 測試）。
// 流程：使用者意圖 → 規則產生候選動作與證據 → （必要時）模型只挑候選 ID → 驗證 → 由畫面確認／套用。
// 模型永遠不能產生候選以外的動作；agent 只做換頁與版面調整，不送飛行指令、不改任何參數值。

// ---------------------------------------------------------------- 畫面目錄
// page 值對照 GcpMainShell.navigateToPage；section 值對照各頁 selectedSection（飛行日誌為 currentView）
var PAGES = [
    { page: 0,  name: "首頁總覽", aliases: ["首頁", "主頁", "主畫面", "總覽", "home"] },
    { page: 1,  name: "即時飛行", aliases: ["飛行畫面", "飛行頁", "即時畫面", "fly view", "live flight", "飛行監控"] },
    { page: 2,  name: "任務規劃", aliases: ["規劃", "航點", "plan", "任務編輯", "規劃航線", "編輯任務"] },
    { page: 3,  name: "安全設定", aliases: ["安全", "失效保護", "failsafe"] },
    { page: 4,  name: "告警中心", aliases: ["告警", "警報", "警告", "alert", "alarm"] },
    { page: 5,  name: "設備管理", aliases: ["設備", "載具設定", "機體設定", "vehicle setup"] },
    { page: 6,  name: "飛行日誌", aliases: ["日誌", "飛行紀錄", "飛航數據", "log", "遙測紀錄", "遙測資料", "飛航紀錄"] },
    { page: 7,  name: "影像設置", aliases: ["相機", "影像", "攝影機", "camera"] },
    { page: 8,  name: "系統設定", aliases: ["系統", "應用程式設定", "settings"] },
    { page: 9,  name: "航線庫",   aliases: ["航線", "任務庫", "路線庫", "mission library"] },
    { page: 10, name: "用戶管理", aliases: ["用戶", "使用者", "使用者管理", "帳號", "權限管理", "user"] },
    { page: 11, name: "天氣資訊", aliases: ["天氣", "氣象", "weather"] },
    { page: 12, name: "媒體庫",   aliases: ["媒體", "照片", "相簿", "影片庫", "media"] },
    { page: 13, name: "3D 視圖",  aliases: ["3d", "三維", "立體地圖"] }
]

var SECTIONS = [
    // 安全設定
    { page: 3, section: 0, name: "返航（RTL）", aliases: ["返航", "rtl", "返航高度"] },
    { page: 3, section: 1, name: "電池失效保護", aliases: ["電池保護", "低電量", "電量失效"] },
    { page: 3, section: 2, name: "通訊與遙控失效保護", aliases: ["失聯", "遙控失效", "通訊失效", "斷訊"] },
    { page: 3, section: 3, name: "GPS／導航", aliases: ["gps", "導航"] },
    { page: 3, section: 4, name: "地理圍欄", aliases: ["圍欄", "geofence", "電子圍籬"] },
    { page: 3, section: 5, name: "飛行限制", aliases: ["限高", "最大高度", "最大距離", "飛行範圍"] },
    { page: 3, section: 6, name: "緊急處置", aliases: ["緊急"] },
    { page: 3, section: 7, name: "解鎖／上鎖安全", aliases: ["解鎖", "上鎖", "arming"] },
    // 設備管理
    { page: 5, section: 0, name: "設備健康", aliases: ["健康", "元件健康狀態"] },
    { page: 5, section: 1, name: "韌體", aliases: ["firmware", "更新韌體"] },
    { page: 5, section: 2, name: "機體／載具", aliases: ["機架", "機體類型", "airframe"] },
    { page: 5, section: 3, name: "感測器", aliases: ["羅盤狀態", "imu", "氣壓計"] },
    { page: 5, section: 4, name: "感測器校正", aliases: ["校正", "校準", "calibration"] },
    { page: 5, section: 5, name: "無線電／RC", aliases: ["遙控器", "rc", "無線電"] },
    { page: 5, section: 6, name: "電源／電池", aliases: ["電池", "電源", "battery"] },
    { page: 5, section: 7, name: "馬達／ESC", aliases: ["馬達", "電調", "esc"] },
    { page: 5, section: 8, name: "馬達測試", aliases: ["測試馬達"] },
    { page: 5, section: 9, name: "飛行控制器", aliases: ["飛控", "flight controller"] },
    { page: 5, section: 10, name: "參數", aliases: ["參數表", "parameters"] },
    { page: 5, section: 11, name: "飛行模式", aliases: ["模式切換", "flight modes"] },
    { page: 5, section: 12, name: "飛行調校／PID", aliases: ["pid", "調校", "autotune"] },
    { page: 5, section: 13, name: "致動器／Servo", aliases: ["servo", "致動器", "伺服"] },
    { page: 5, section: 14, name: "飛行行為（PX4）", aliases: ["操控手感", "速度上限"] },
    // 飛行日誌（currentView）
    { page: 6, section: 0, name: "摘要", aliases: ["日誌摘要"] },
    { page: 6, section: 1, name: "圖表", aliases: ["日誌圖表", "曲線"] },
    { page: 6, section: 2, name: "事件", aliases: ["日誌事件", "事件紀錄"] },
    { page: 6, section: 3, name: "MAVLink 日誌", aliases: ["mavlink log"] },
    { page: 6, section: 4, name: "檢查器", aliases: ["inspector"] },
    { page: 6, section: 5, name: "主控台", aliases: ["console", "終端"] },
    { page: 6, section: 6, name: "Log Viewer", aliases: ["log viewer"] },
    { page: 6, section: 7, name: "振動", aliases: ["震動", "振動分析"] },
    // 影像設置
    { page: 7, section: 0, name: "相機", aliases: ["相機首頁"] },
    { page: 7, section: 1, name: "影片", aliases: ["錄影設定"] },
    { page: 7, section: 2, name: "雲台", aliases: ["gimbal", "雲台設定"] },
    { page: 7, section: 3, name: "影像串流", aliases: ["串流", "rtsp", "stream"] },
    { page: 7, section: 4, name: "OSD", aliases: ["osd", "疊加資訊"] },
    { page: 7, section: 5, name: "儲存／錄影", aliases: ["儲存", "記憶卡", "sd卡"] },
    { page: 7, section: 6, name: "設備資訊", aliases: ["相機資訊"] },
    // 系統設定
    { page: 8, section: 0, name: "一般", aliases: ["語言", "單位", "外觀", "主題"] },
    { page: 8, section: 1, name: "地圖", aliases: ["地圖來源", "離線地圖", "離線地圖下載", "圖資"] },
    { page: 8, section: 2, name: "通訊", aliases: ["連線設定", "自動連線", "通訊連結"] },
    { page: 8, section: 3, name: "MAVLink", aliases: ["mavlink", "系統id", "簽章"] },
    { page: 8, section: 4, name: "定位", aliases: ["rtk", "nmea"] },
    { page: 8, section: 5, name: "交通", aliases: ["ads-b", "adsb"] },
    { page: 8, section: 6, name: "影像", aliases: ["影像來源", "解碼"] },
    { page: 8, section: 7, name: "控制", aliases: ["搖桿", "joystick", "按鍵映射"] },
    { page: 8, section: 8, name: "Remote ID", aliases: ["remote id", "遠端識別"] },
    { page: 8, section: 9, name: "紀錄", aliases: ["日誌儲存", "保留"] },
    { page: 8, section: 10, name: "更新", aliases: ["版本", "更新通道"] },
    { page: 8, section: 11, name: "Fly View", aliases: ["fly view", "飛行畫面設定", "飛行畫面行為"] },
    { page: 8, section: 12, name: "Plan View", aliases: ["plan view", "規劃預設值", "任務規劃預設值"] },
    { page: 8, section: 13, name: "3D View", aliases: ["3d 視圖設定"] },
    { page: 8, section: 14, name: "PX4 Log Transfer", aliases: ["日誌傳送", "log transfer"] }
]

// 可調整的版面模組（目前在即時飛行畫面）。實際是否存在、是否可見，以執行時登記的 GcpAgentModule 為準。
var MODULES = [
    { id: "missionProgress", page: 1, name: "任務進度", aliases: ["任務進度條", "進度"] },
    { id: "payloadRail",     page: 1, name: "酬載快捷列", aliases: ["酬載", "快捷列", "拍照按鈕"] },
    { id: "attitude",        page: 1, name: "姿態儀", aliases: ["姿態", "水平儀", "人工地平儀"] },
    { id: "headingTape",     page: 1, name: "航向帶", aliases: ["航向", "方位帶"] },
    { id: "speedReadout",    page: 1, name: "速度顯示", aliases: ["速度", "空速", "地速"] },
    { id: "altReadout",      page: 1, name: "高度顯示", aliases: ["高度"] },
    { id: "compass",         page: 1, name: "羅盤", aliases: ["指南針", "半圓羅盤"] },
    { id: "windGauge",       page: 1, name: "風速計", aliases: ["風速", "風向", "風力"] },
    { id: "homeInfo",        page: 1, name: "返航距離與飛行時間", aliases: ["返航距離", "飛行時間", "距離"] },
    { id: "miniView",        page: 1, name: "小地圖", aliases: ["子畫面", "迷你地圖", "小視窗", "pip"] },
    { id: "actionDock",      page: 1, name: "指令區", aliases: ["指令按鈕", "起飛按鈕", "操作區", "dock"] },
    { id: "telemetryBar",    page: 1, name: "底部遙測列", aliases: ["遙測列", "遙測", "狀態列"] }
]

var REGIONS = [
    { key: "TL", name: "左上角", words: ["左上"] },
    { key: "TR", name: "右上角", words: ["右上"] },
    { key: "BL", name: "左下角", words: ["左下"] },
    { key: "BR", name: "右下角", words: ["右下"] },
    { key: "TC", name: "上方中間", words: ["上方", "上面", "頂部", "最上"] },
    { key: "BC", name: "下方中間", words: ["下方", "下面", "底部", "最下"] },
    { key: "ML", name: "左側中間", words: ["左邊", "左側", "最左"] },
    { key: "MR", name: "右側中間", words: ["右邊", "右側", "最右"] },
    { key: "C",  name: "畫面中央", words: ["中間", "中央", "正中"] }
]

var NUDGES = [
    { key: "L", name: "往左", words: ["往左", "向左", "左移"] },
    { key: "R", name: "往右", words: ["往右", "向右", "右移"] },
    { key: "U", name: "往上", words: ["往上", "向上", "上移"] },
    { key: "D", name: "往下", words: ["往下", "向下", "下移"] }
]

var FILLER = ["我想要", "我想", "我要", "幫我", "麻煩", "請", "可以", "查看", "看一下", "看看", "檢查",
              "切換到", "切到", "切去", "跳到", "打開", "開啟", "進入", "前往", "帶我去", "去",
              "畫面", "頁面", "頁", "一下", "的", "給我", "嗎", "吧", "呢", "。", "，", ",", "?", "？", "!", "！"]

// ---------------------------------------------------------------- 文字比對
function norm(s) {
    return String(s || "").toLowerCase().replace(/[\s　]+/g, " ").trim()
}

function stripFiller(s) {
    var out = norm(s)
    for (var i = 0; i < FILLER.length; ++i) out = out.split(FILLER[i]).join(" ")
    return out.replace(/\s+/g, " ").trim()
}

function bigrams(s) {
    var t = norm(s).replace(/\s+/g, "")
    var out = {}
    if (t.length === 1) out[t] = true
    for (var i = 0; i + 1 < t.length; ++i) out[t.substr(i, 2)] = true
    return out
}

// 0..1+：別名完整出現在意圖中 = 1 + 長度加分；否則別名的雙字覆蓋率
function aliasScore(text, alias) {
    var t = norm(text).replace(/\s+/g, ""), a = norm(alias).replace(/\s+/g, "")
    if (!a) return 0
    if (t.indexOf(a) >= 0) return 1 + Math.min(a.length, 8) * 0.02
    var ab = bigrams(a), tb = bigrams(t), n = 0, hit = 0
    for (var k in ab) { ++n; if (tb[k]) ++hit }
    return n ? hit / n * 0.8 : 0
}

var GENERIC = ["設定", "設置", "功能", "選項", "資訊", "狀態"]

// 去掉「設定」這類泛稱後剩下的核心詞（例：「飛行設定」→「飛行」），用來找名稱裡含這個詞的項目
function coreWord(text) {
    var t = norm(text).replace(/\s+/g, "")
    for (var i = 0; i < GENERIC.length; ++i) t = t.split(GENERIC[i]).join("")
    return t
}

function bestScore(text, entry) {
    var best = aliasScore(text, entry.name)
    for (var i = 0; i < (entry.aliases || []).length; ++i)
        best = Math.max(best, aliasScore(text, entry.aliases[i]))
    var core = coreWord(text)
    if (best < 0.6 && core.length >= 2 && core.length <= 4) {
        var names = [entry.name].concat(entry.aliases || [])
        for (i = 0; i < names.length; ++i)
            if (norm(names[i]).replace(/\s+/g, "").indexOf(core) >= 0) { best = 0.6; break }
    }
    return best
}

function hasAny(text, words) {
    for (var i = 0; i < words.length; ++i) if (text.indexOf(words[i]) >= 0) return words[i]
    return ""
}

function pageName(page) {
    for (var i = 0; i < PAGES.length; ++i) if (PAGES[i].page === page) return PAGES[i].name
    return "第 " + page + " 頁"
}

function moduleById(id) {
    for (var i = 0; i < MODULES.length; ++i) if (MODULES[i].id === id) return MODULES[i]
    return null
}

// ---------------------------------------------------------------- 意圖 → 候選
// ctx: { page, section, modules: { id: { visible: bool, registered: bool } }, canUndo, canRedo }
// 回傳 { candidates: [...], evidence: [...], rule: { decision, choice_id, reason_zh } }
function analyze(intent, ctx) {
    ctx = ctx || {}
    var raw = norm(intent)
    var text = stripFiller(intent)
    var evidence = [{ id: "E1", text: "目前畫面：" + pageName(ctx.page) }]
    var cands = []
    function add(c) { cands.push(c) }

    var CMD_WORDS = ["起飛", "降落", "返航", "解鎖", "上鎖", "懸停", "開始任務", "執行任務", "暫停任務", "拍照", "錄影", "takeoff", "land"]
    var NAV_HINTS = ["設定", "設置", "頁", "畫面", "切", "去", "打開", "開啟", "看", "查看", "進入", "前往", "參數", "保護"]
    if (hasAny(raw, CMD_WORDS) && !hasAny(raw, NAV_HINTS)) {
        evidence.push({ id: "E2", text: "意圖像是飛行或相機指令；介面助理只換頁與調整版面，不送指令" })
        return { intent: String(intent || ""), candidates: [], evidence: evidence,
                 rule: { decision: "HOLD", choice_id: "", final: true, reason_zh: "我不會送飛行或相機指令，請用畫面上的指令區（需滑動確認）" } }
    }

    var wantRedo = hasAny(raw, ["重做", "redo", "取消復原", "取消還原"])
    var wantResetAll = hasAny(raw, ["全部復原", "全部還原", "恢復預設", "回到最初", "重置版面", "版面重置", "恢復原始", "全部重置"])
    var undoWord = hasAny(raw, ["復原", "還原", "上一步", "撤銷", "undo", "取消剛剛", "回到剛才", "回上一個", "恢復原狀", "改回來", "回復"])

    // 模組比對
    function score(entry) { return Math.max(bestScore(text, entry), bestScore(raw, entry)) }
    var mods = []
    for (var i = 0; i < MODULES.length; ++i) {
        var s = score(MODULES[i])
        if (s >= 0.5) mods.push({ m: MODULES[i], s: s })
    }
    mods.sort(function (a, b) { return b.s - a.s })
    if (mods.length > 1 && mods[1].s < mods[0].s - 0.15) mods = [mods[0]]   // 明確點名的模組優先

    // 動作字詞只在「去掉模組名稱」後的文字裡找，避免「底部遙測列」的「底部」被當成位置
    var opText = raw
    for (i = 0; i < mods.length; ++i) {
        var names = [mods[i].m.name].concat(mods[i].m.aliases).sort(function (a, b) { return b.length - a.length })
        for (var j = 0; j < names.length; ++j) opText = opText.split(norm(names[j])).join(" ")
    }
    var region = null
    for (i = 0; i < REGIONS.length && !region; ++i) if (hasAny(opText, REGIONS[i].words)) region = REGIONS[i]
    var nudge = null
    for (i = 0; i < NUDGES.length && !nudge; ++i) if (hasAny(opText, NUDGES[i].words)) nudge = NUDGES[i]
    var scale = 0
    if (hasAny(opText, ["兩倍", "2倍", "二倍"])) scale = 2.0
    else if (hasAny(opText, ["一半", "減半"])) scale = 0.5
    else if (hasAny(opText, ["放大", "變大", "大一點", "大一些", "加大", "大點"])) scale = 1.25
    else if (hasAny(opText, ["縮小", "變小", "小一點", "小一些", "小點"])) scale = 0.8
    var wantHide = hasAny(opText, ["隱藏", "關掉", "藏起來", "不要顯示", "拿掉", "先收起", "收起來", "關閉"])
    var wantShow = !wantHide && hasAny(opText, ["顯示", "叫出", "打開", "恢復顯示", "放回來"])
    var wantModuleReset = hasAny(opText, ["原本大小", "原來大小", "原位", "原本位置", "原來的位置", "預設位置", "恢復原樣", "還原大小", "還原位置"])
    var moveVerb = hasAny(opText, ["移", "搬", "放到", "放在", "挪", "擺到", "擺在", "拉到"])
    var layoutIntent = region || nudge || scale || wantHide || wantModuleReset || (moveVerb && mods.length)

    // 1) 復原／重做／全部復原（單純復原意圖，不是針對某模組的「還原大小」）
    if (wantRedo) {
        add({ id: "REDO", kind: "redo", label_zh: "重做剛剛復原的變更", score: ctx.canRedo ? 1.2 : 0.2 })
        if (!ctx.canRedo) evidence.push({ id: "E" + (evidence.length + 1), text: "沒有可重做的變更" })
    } else if (wantResetAll) {
        add({ id: "RESET_ALL", kind: "reset_all", label_zh: "版面與畫面全部回到 agent 介入前", score: 1.2 })
    } else if (undoWord && !(mods.length && wantModuleReset)) {
        var steps = /([2-9二兩三四五])\s*步/.exec(raw)
        var n = steps ? ({ "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5 }[steps[1]] || parseInt(steps[1], 10)) : 1
        add({ id: n > 1 ? "UNDO_" + n : "UNDO", kind: "undo", steps: n,
              label_zh: n > 1 ? "復原前 " + n + " 步變更" : "復原上一步變更", score: ctx.canUndo ? 1.2 : 0.2 })
        if (!ctx.canUndo) evidence.push({ id: "E" + (evidence.length + 1), text: "目前沒有可復原的變更" })
    }

    // 2) 版面調整
    if (layoutIntent && !wantRedo && !wantResetAll) {
        var targets = mods.length ? mods : MODULES.map(function (m) { return { m: m, s: 0.3 } })
        for (i = 0; i < targets.length; ++i) {
            var m = targets[i].m, base = targets[i].s >= 0.5 ? 0.9 : 0.3
            var info = (ctx.modules || {})[m.id]
            if (info && info.registered && !info.visible && targets[i].s >= 0.5)
                evidence.push({ id: "E" + (evidence.length + 1), text: m.name + " 目前未顯示（多半是尚未連上載具）；調整會在顯示後生效" })
            if (region) add({ id: "LAY_" + m.id + "_MOVE_" + region.key, kind: "layout", module: m.id, op: "move", region: region.key,
                              label_zh: "把" + m.name + "移到" + region.name, score: base + 0.1 })
            if (nudge) add({ id: "LAY_" + m.id + "_NUDGE_" + nudge.key, kind: "layout", module: m.id, op: "nudge", dir: nudge.key,
                             label_zh: "把" + m.name + nudge.name + "移一點", score: base + 0.05 })
            if (scale) add({ id: "LAY_" + m.id + "_SCALE_" + Math.round(scale * 100), kind: "layout", module: m.id, op: "scale", factor: scale,
                             label_zh: (scale > 1 ? "放大" : "縮小") + m.name + "（×" + scale + "）", score: base + 0.1 })
            if (wantHide) add({ id: "LAY_" + m.id + "_HIDE", kind: "layout", module: m.id, op: "hide",
                                label_zh: "隱藏" + m.name, score: base + 0.1 })
            if (wantModuleReset) add({ id: "LAY_" + m.id + "_RESET", kind: "layout", module: m.id, op: "reset",
                                       label_zh: m.name + "回到原本位置與大小", score: base + 0.1 })
            if (!region && !nudge && !scale && !wantHide && !wantModuleReset && moveVerb && targets[i].s >= 0.5) {
                // 只說「移一下風速計」沒說位置：列出常用位置讓使用者挑
                var common = ["TL", "TR", "BL", "BR"]
                for (var r = 0; r < common.length; ++r) {
                    var reg = REGIONS.filter(function (x) { return x.key === common[r] })[0]
                    add({ id: "LAY_" + m.id + "_MOVE_" + reg.key, kind: "layout", module: m.id, op: "move", region: reg.key,
                          label_zh: "把" + m.name + "移到" + reg.name, score: 0.5 })
                }
            }
        }
    } else if (wantShow && mods.length) {
        add({ id: "LAY_" + mods[0].m.id + "_SHOW", kind: "layout", module: mods[0].m.id, op: "show",
              label_zh: "重新顯示" + mods[0].m.name, score: 1.0 })
    }

    // 3) 換頁（沒有版面或復原意圖時才主導；有的話仍放低分候選，交給使用者／模型判斷）
    var navWeight = (layoutIntent || undoWord || wantRedo || wantResetAll) ? 0.5 : 1.0
    var pageScores = {}
    for (i = 0; i < PAGES.length; ++i) pageScores[PAGES[i].page] = score(PAGES[i])
    var nav = []
    for (i = 0; i < SECTIONS.length; ++i) {
        var sec = SECTIONS[i]
        var ss = score(sec)
        if (ss < 0.3) continue
        var sc = ss + 0.3 * Math.min(pageScores[sec.page], 1)
        if (ss < 1 && hasAny(raw, ["設定", "設置"]) && [3, 5, 7, 8].indexOf(sec.page) >= 0) sc += 0.1
        nav.push({ id: "NAV_" + sec.page + "_" + sec.section, kind: "nav", page: sec.page, section: sec.section,
                   label_zh: "切到「" + pageName(sec.page) + " › " + sec.name + "」", score: sc * navWeight })
    }
    for (i = 0; i < PAGES.length; ++i) {
        var ps = pageScores[PAGES[i].page]
        if (ps < 0.3) continue
        nav.push({ id: "NAV_" + PAGES[i].page, kind: "nav", page: PAGES[i].page, section: -1,
                   label_zh: "切到「" + PAGES[i].name + "」", score: ps * 0.95 * navWeight })
    }
    for (i = 0; i < nav.length; ++i) add(nav[i])

    // 已經在目標畫面的換頁候選降分
    for (i = 0; i < cands.length; ++i) {
        var c = cands[i]
        if (c.kind === "nav" && c.page === ctx.page && (c.section < 0 || c.section === ctx.section)) {
            c.here = true
            c.score -= 0.3
            c.label_zh += "（已在此畫面）"
        }
    }
    // 不扣分時最明確的就是目前畫面 → 直接告訴使用者已經在這裡
    var hereBest = null, otherBest = 0
    for (i = 0; i < cands.length; ++i) {
        if (cands[i].here) { if (!hereBest || cands[i].score > hereBest.score) hereBest = cands[i] }
        else otherBest = Math.max(otherBest, cands[i].score)
    }
    if (hereBest && hereBest.score + 0.3 >= 0.75 && hereBest.score + 0.3 - otherBest >= 0.15)
        return { intent: String(intent || ""), candidates: [], evidence: evidence,
                 rule: { decision: "HOLD", choice_id: "", final: true, reason_zh: "已經在" + hereBest.label_zh.replace("（已在此畫面）", "").replace("切到", "") + "了" } }

    cands.sort(function (a, b) { return b.score - a.score })
    // 去重、取前 6
    var seen = {}, top = []
    for (i = 0; i < cands.length && top.length < 6; ++i) {
        if (seen[cands[i].id]) continue
        seen[cands[i].id] = true
        top.push(cands[i])
    }
    if (top.length) evidence.push({ id: "E" + (evidence.length + 1),
        text: "規則比對最高：" + top[0].label_zh + "（" + top[0].score.toFixed(2) + "）" +
              (top.length > 1 ? "；次高：" + top[1].label_zh + "（" + top[1].score.toFixed(2) + "）" : "") })

    return { intent: String(intent || ""), candidates: top, evidence: evidence, rule: ruleDecide(top, evidence) }
}

// 規則決策：分數夠高且明顯領先才直接選，否則請使用者挑
function ruleDecide(top, evidence) {
    if (!top.length || top[0].score < 0.3) {
        var why = "規則找不到對應的畫面或模組"
        for (var i = 0; evidence && i < evidence.length; ++i)
            if (evidence[i].text.indexOf("沒有可") === 0 || evidence[i].text.indexOf("目前沒有可") === 0) why = evidence[i].text
        return { decision: "HOLD", choice_id: "", reason_zh: why }
    }
    var gap = top.length > 1 ? top[0].score - top[1].score : 9
    if (top[0].score >= 0.75 && gap >= 0.15)
        return { decision: "SELECT", choice_id: top[0].id, reason_zh: "規則比對：" + top[0].label_zh }
    return { decision: "CLARIFY", choice_id: "", reason_zh: "有多個可能" }
}

// 模型只在規則不確定時參與（GCS_AGENT_LLM_ALWAYS=1 時每次都問）
// rule.final：安全界線或「已經在這個畫面」這類規則已確定的結果，不交給模型
function needsModel(result, always) {
    if (result.rule.final) return false
    if (always) return result.candidates.length > 0
    return result.rule.decision !== "SELECT"
}

// 規則什麼都沒找到時，給模型的備用候選：全部頁面與子頁（讓模型用語意挑）
function catalogCandidates(ctx) {
    var out = []
    for (var i = 0; i < PAGES.length; ++i)
        out.push({ id: "NAV_" + PAGES[i].page, kind: "nav", page: PAGES[i].page, section: -1,
                   label_zh: "切到「" + PAGES[i].name + "」", score: 0 })
    for (i = 0; i < SECTIONS.length; ++i)
        out.push({ id: "NAV_" + SECTIONS[i].page + "_" + SECTIONS[i].section, kind: "nav",
                   page: SECTIONS[i].page, section: SECTIONS[i].section,
                   label_zh: "切到「" + pageName(SECTIONS[i].page) + " › " + SECTIONS[i].name + "」", score: 0 })
    return out
}

// ---------------------------------------------------------------- 模型提示與驗證（共用決策格式）
var SYSTEM_PROMPT =
    "你是無人機地面站的介面助理。你只能從 candidates 中挑一個動作的 id，不能自創動作。\n" +
    "規則：意圖明確對應某個候選就 SELECT；有兩個以上都說得通、或意圖太模糊就 CLARIFY；" +
    "沒有任何候選符合、或要求控制飛機／修改參數就 HOLD。\n" +
    "只輸出 JSON：{\"decision\":\"SELECT|HOLD|CLARIFY\",\"choice_id\":\"候選id或空字串\"," +
    "\"reason_zh\":\"一句繁體中文理由\",\"evidence_ids\":[\"E1\"]}"

function buildUserMessage(result, ctx) {
    return JSON.stringify({
        intent: result.intent,
        current_page: pageName(ctx.page),
        candidates: result.candidates.map(function (c) { return { id: c.id, label: c.label_zh } }),
        evidence: result.evidence.map(function (e) { return { id: e.id, text: e.text } })
    })
}

function extractJson(text) {
    if (text && typeof text === "object") return text
    var s = String(text || "")
    var a = s.indexOf("{"), b = s.lastIndexOf("}")
    if (a < 0 || b <= a) return null
    try { return JSON.parse(s.substring(a, b + 1)) } catch (e) { return null }
}

// 回傳 { ok, decision, choice_id, reason_zh, evidence_ids, error }
function validateModelDecision(obj, result) {
    if (!obj) return { ok: false, error: "回覆不是 JSON" }
    var d = String(obj.decision || "").toUpperCase()
    if (["SELECT", "HOLD", "CLARIFY"].indexOf(d) < 0) return { ok: false, error: "decision 無效：" + obj.decision }
    var ids = result.candidates.map(function (c) { return c.id })
    var choice = String(obj.choice_id || "")
    if (d === "SELECT" && ids.indexOf(choice) < 0) return { ok: false, error: "choice_id 不在候選內：" + choice }
    var evIds = result.evidence.map(function (e) { return e.id })
    var ev = Array.isArray(obj.evidence_ids) ? obj.evidence_ids.map(String) : []
    for (var i = 0; i < ev.length; ++i)
        if (evIds.indexOf(ev[i]) < 0) return { ok: false, error: "引用不存在的證據：" + ev[i] }
    return { ok: true, decision: d, choice_id: d === "SELECT" ? choice : "",
             reason_zh: String(obj.reason_zh || "").substring(0, 80), evidence_ids: ev }
}

function candidateById(result, id) {
    for (var i = 0; i < result.candidates.length; ++i) if (result.candidates[i].id === id) return result.candidates[i]
    return null
}

// ---------------------------------------------------------------- 版面幾何（純計算）
// box: 模組未加 agent 變換時在容器內的位置 {x,y,w,h}；area: 容器 {w,h}；cur: 目前覆寫 {dx,dy,scale,hidden}
// others: 其他可見模組目前的矩形（移動時避開）
function layoutTarget(op, box, area, cur, arg, others) {
    var next = { dx: cur.dx || 0, dy: cur.dy || 0, scale: cur.scale || 1, hidden: !!cur.hidden }
    var margin = 24
    if (op === "scale") {
        var before = next.scale
        next.scale = Math.max(0.5, Math.min(2.0, next.scale * arg))
        if (arg === 2.0 || arg === 0.5) next.scale = Math.max(0.5, Math.min(2.0, arg))
        // 以模組中心為基準縮放，靠邊的模組不會長出畫面
        next.dx -= box.w * (next.scale - before) / 2
        next.dy -= box.h * (next.scale - before) / 2
    } else if (op === "hide") {
        next.hidden = true
    } else if (op === "show") {
        next.hidden = false
    } else if (op === "reset") {
        next = { dx: 0, dy: 0, scale: 1, hidden: false }
    } else if (op === "nudge") {
        var step = 80
        if (arg === "L") next.dx -= step
        if (arg === "R") next.dx += step
        if (arg === "U") next.dy -= step
        if (arg === "D") next.dy += step
    } else if (op === "move") {
        var w = box.w * next.scale, h = box.h * next.scale
        var col = arg.length === 2 ? arg[1] : (arg === "C" ? "C" : "C")
        var row = arg.length === 2 ? arg[0] : "M"
        if (arg === "TC") { row = "T"; col = "C" }
        if (arg === "BC") { row = "B"; col = "C" }
        if (arg === "ML") { row = "M"; col = "L" }
        if (arg === "MR") { row = "M"; col = "R" }
        if (arg === "C")  { row = "M"; col = "C" }
        var tx = col === "L" ? margin : col === "R" ? area.w - w - margin : (area.w - w) / 2
        var ty = row === "T" ? margin : row === "B" ? area.h - h - margin : (area.h - h) / 2
        next.dx = tx - box.x
        next.dy = ty - box.y
    }
    // 不讓模組整個跑出畫面
    var sw = box.w * next.scale, sh = box.h * next.scale
    var nx = Math.max(0, Math.min(area.w - Math.min(sw, area.w), box.x + next.dx))
    var ny = Math.max(0, Math.min(area.h - Math.min(sh, area.h), box.y + next.dy))
    // 移動時避開其他可見模組：沿著遠離邊緣的方向一步步找空位
    if ((op === "move" || op === "nudge") && others && others.length) {
        var spot = freeSpot({ x: nx, y: ny, w: sw, h: sh }, others, area)
        nx = spot.x; ny = spot.y
    }
    next.dx = Math.round(nx - box.x)
    next.dy = Math.round(ny - box.y)
    return next
}

function overlaps(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
}

// rect 與 others 都是容器座標；找不到空位就維持原位置（允許重疊）
function freeSpot(rect, others, area) {
    function clear(r) {
        for (var i = 0; i < others.length; ++i) if (overlaps(r, others[i])) return false
        return true
    }
    if (clear(rect)) return rect
    var dirY = rect.y + rect.h / 2 < area.h / 2 ? 1 : -1
    var dirX = rect.x + rect.w / 2 < area.w / 2 ? 1 : -1
    for (var step = 16; step < Math.max(area.w, area.h); step += 16) {
        var tries = [{ x: rect.x, y: rect.y + dirY * step }, { x: rect.x + dirX * step, y: rect.y }]
        for (var k = 0; k < tries.length; ++k) {
            var r = { x: tries[k].x, y: tries[k].y, w: rect.w, h: rect.h }
            if (r.x < 0 || r.y < 0 || r.x + r.w > area.w || r.y + r.h > area.h) continue
            if (clear(r)) return r
        }
    }
    return rect
}
