pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import QtPositioning

import "GcpMissionCore.js" as Core

// 任務規劃頁的「AI 任務建議」面板：讀目前任務的航點 → 演算法產生候選航線（含風的能耗、禁航區、電量）
// → 規則先選、模型（可有可無）在候選內選 → 地圖預覽 → 操作員按「套用」才改航點順序，可「復原」。
// 另有「模擬飛行與報告」：模擬風變大 → 預測告警 → LOCAL/FULL 重規劃 → 智慧任務報告（每條建議附事實編號）。
// 不送任何飛行指令；套用只改規劃頁的航點座標順序。
Item {
    id: root

    property var missionController: null      // PlanMasterController.missionController
    property var map: null                    // GcpMissionMapCanvas.map（預覽線畫在這裡；null 時不畫）
    property var activeVehicle: null          // 有連線時讀飛控估測風
    property var envValue: function (name, fallback) { return fallback }

    // 外觀（預設值取自 GcpThemeColor，獨立宣告方便在沒有 GCP 模組的測試架裡載入）
    property color cPrimary: "#00D3F2"
    property color cPanel: Qt.rgba(0.04, 0.05, 0.07, 0.96)
    property color cBorder: Qt.rgba(1, 1, 1, 0.1)
    property color cText: "white"
    property color cMuted: Qt.rgba(1, 1, 1, 0.55)
    property color cOk: "#4ADE80"
    property color cWarn: "#FBBF24"
    property color cCrit: "#EF4444"
    property color cLlm: "#C4B5FD"
    property real fs: 14

    Settings {
        id: modelSettings
        category: "GCP/Agent"            // 和 UI agent 共用同一組模型設定
        property string backend: ""
        property string llmUrl: ""
        property string llmModel: ""
    }
    Settings {
        id: missionSettings
        category: "GCP/Mission"
        property real calib: 1.0          // 任務報告學到的耗電修正係數
        property real batteryWh: 90
        property real reservePct: 20
    }
    readonly property string backend: modelSettings.backend || envValue("GCS_LLM_BACKEND", "openai")
    readonly property string modelUrl: modelSettings.llmUrl || envValue("GCS_LLM_URL", "")
    readonly property string modelName: modelSettings.llmModel || envValue("GCS_LLM_MODEL", "")
    readonly property bool modelEnabled: backend !== "none" && modelUrl !== ""
    readonly property int modelTimeoutMs: parseInt(envValue("GCS_LLM_TIMEOUT_MS", "180000"), 10)

    property bool open: false
    property bool busy: false
    property string stage: "plan"          // plan | replan | report
    property var mission: null
    property var optional: ({})             // 航點 id → true 表示選配
    property var result: null               // 規劃或重規劃結果
    property string selected: ""
    property var undoStack: []              // 每次套用前的航點座標
    property var run: null
    property var flown: null
    property var alertInfo: null
    property var report: null
    property string status: ""

    signal decisionLogged(var entry)

    // ------------------------------------------------------------ 讀任務
    function waypointItems() {
        const out = []
        const vis = missionController ? missionController.visualItems : null
        if (!vis) return out
        for (let i = 0; i < vis.count; i++) {
            const it = vis.get(i)
            if (it && it.isSimpleItem && it.specifiesCoordinate && it.command === 16 && it.coordinate && it.coordinate.isValid)
                out.push(it)
        }
        return out
    }

    function readMission() {
        const items = waypointItems()
        if (items.length < 2) return null
        let h = missionController.plannedHomePosition
        if (!h || !h.isValid) h = items[0].coordinate
        const tg = items.map((it, i) => ({ id: "WP" + (i + 1), lat: it.coordinate.latitude, lon: it.coordinate.longitude,
                                            alt: it.altitude ? it.altitude.rawValue : 50, priority: optional["WP" + (i + 1)] ? 2 : 1 }))
        return { name: qsTr("目前任務"), home: { id: "H", lat: h.latitude, lon: h.longitude }, targets: tg, no_fly: [],
                 speed_mps: 8, limits: { max_altitude_m: 120 } }
    }

    function vehicleParams() {
        return Core.vehicle({ battery_wh: missionSettings.batteryWh, reserve_pct: missionSettings.reservePct, calib: missionSettings.calib })
    }

    function currentWind() {
        return Core.wind(parseFloat(windSpeed.text) || 0, parseFloat(windFrom.text) || 0)
    }

    // ------------------------------------------------------------ 規劃
    function makePlan() {
        mission = readMission()
        if (!mission) { status = qsTr("請先在地圖上放至少 2 個航點"); return }
        stage = "plan"; report = null; alertInfo = null; run = null
        result = Core.planMission(mission, vehicleParams(), currentWind())
        selected = result.pick.choice_id || result.rule_choice
        status = ""
        drawPreview()
        askModel(result)
    }

    function askModel(res) {
        if (!modelEnabled || !res.rule_choice) { log(res, null); return }
        busy = true
        const pr = Core.pickPrompt(res)
        callModel(pr.system, pr.user, function (r) {
            busy = false
            if (res !== result) return
            const pick = r.ok ? Core.validatePick(res, r.content)
                              : Object.assign(Core.validatePick(res, ""), { reason_zh: qsTr("規則選擇（模型無回應：%1）").arg(r.error) })
            res.pick = pick
            if (pick.choice_id) selected = pick.choice_id
            result = res; resultChanged()
            drawPreview()
            log(res, r)
        })
    }

    function log(res, r) {
        const entry = { kind: res.kind, rule: res.rule_choice, pick: res.pick.choice_id, source: res.pick.source,
                        latency_ms: r ? r.latency_ms : 0, error: r && !r.ok ? r.error : "" }
        console.log("[GcpMission] " + JSON.stringify(entry))
        decisionLogged(entry)
    }

    function cand(id) { return result ? result.candidates.find(c => c.id === id) : null }

    // ------------------------------------------------------------ 套用與復原（只改航點座標順序）
    function snapshot() {
        return waypointItems().map(it => ({ lat: it.coordinate.latitude, lon: it.coordinate.longitude,
                                             alt: it.altitude ? it.altitude.rawValue : 50 }))
    }
    function restore(snap) {
        const items = waypointItems()
        for (let i = 0; i < items.length && i < snap.length; i++) {
            items[i].coordinate = QtPositioning.coordinate(snap[i].lat, snap[i].lon)
            if (items[i].altitude) items[i].altitude.rawValue = snap[i].alt
        }
    }
    function applySelected() {
        const c = cand(selected)
        if (!c || stage !== "plan") return
        const before = snapshot()
        const byId = {}
        mission.targets.forEach((t, i) => byId[t.id] = before[i])
        const order = c.order.concat(mission.targets.map(t => t.id).filter(id => c.order.indexOf(id) < 0))  // 刪掉的目標排到最後
        restore(order.map(id => byId[id]))
        undoStack = undoStack.concat([before])
        status = qsTr("已套用 %1 的航點順序%2；可按「復原」").arg(c.id)
                 .arg(c.order.length < mission.targets.length ? qsTr("（略過的目標排在最後，請自行刪除）") : "")
                 + (c.speed_mps !== mission.speed_mps ? qsTr("。建議速度 %1 m/s 請在任務設定中調整").arg(c.speed_mps) : "")
        makePlanKeepStatus()
    }
    function undo() {
        if (!undoStack.length) return
        restore(undoStack[undoStack.length - 1])
        undoStack = undoStack.slice(0, -1)
        status = qsTr("已復原到套用前的航點順序")
        makePlanKeepStatus()
    }
    function makePlanKeepStatus() { const s = status; makePlan(); status = s }

    // ------------------------------------------------------------ 模擬飛行 → 預測告警 → 重規劃 → 報告
    function simulate() {
        const c = cand(selected)
        if (!c) return
        flown = c
        const ws = parseFloat(gustSpeed.text) || 9
        run = new Core.MissionRun(vehicleParams(), currentWind(), 1.15, [{ t_s: 300, speed_mps: ws, from_deg: (currentWind().from_deg + 330) % 360 }])
        const st = run.fly(c, 300)
        if (st.done) { finishReport([]); return }
        const ev = { type: "wind", speed_mps: ws, from_deg: (currentWind().from_deg + 330) % 360,
                     text_zh: qsTr("風速增強到 %1 m/s").arg(ws) }
        const rp = Core.replan(mission, vehicleParams(), currentWind(), st, ev)
        alertInfo = Core.predictiveAlert(vehicleParams(), st, rp)
        stage = "replan"
        result = rp
        selected = rp.pick.choice_id || rp.rule_choice
        drawPreview()
        askModel(rp)
    }
    function continueFlight() {
        const c = cand(selected)
        if (!c) return
        result.final_choice = c.id
        run.fly(c)
        finishReport([result])
    }
    function finishReport(replans) {
        report = Core.makeReport(run, mission, flown, replans, alertInfo ? [alertInfo] : [])
        stage = "report"
        if (!modelEnabled) return
        busy = true
        const pr = Core.reportPrompt(report)
        callModel(pr.system, pr.user, function (r) {
            busy = false
            if (r.ok) report = Core.applyReportLlm(report, r.content)
        })
    }
    function applyCalib() {
        missionSettings.calib = report.next_calib
        status = qsTr("耗電修正係數已更新為 %1，之後的規劃都會套用").arg(report.next_calib.toFixed(2))
        makePlanKeepStatus()
    }

    // ------------------------------------------------------------ 模型呼叫（OpenAI 相容或 Ollama；關閉 thinking）
    function callModel(system, user, done) {
        const xhr = new XMLHttpRequest()
        let finished = false
        const t0 = Date.now()
        function end(r) { if (finished) return; finished = true; timer.stop(); r.latency_ms = Date.now() - t0; done(r) }
        timer.onFire = function () { xhr.abort(); end({ ok: false, error: qsTr("逾時") }) }
        timer.interval = modelTimeoutMs
        timer.restart()
        const messages = [{ role: "system", content: system }, { role: "user", content: user }]
        let url, body
        if (backend === "ollama") {
            url = modelUrl.replace(/\/$/, "") + "/api/chat"
            body = { model: modelName, messages: messages, stream: false, format: "json", think: false,
                     options: { temperature: 0, seed: 17, num_predict: 1024 } }
        } else {
            url = modelUrl.replace(/\/$/, "") + "/chat/completions"
            body = { model: modelName, messages: messages, temperature: 0, max_tokens: 1024,
                     chat_template_kwargs: { enable_thinking: false } }
        }
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status < 200 || xhr.status >= 300) { end({ ok: false, error: "HTTP " + xhr.status }); return }
            try {
                const j = JSON.parse(xhr.responseText)
                const content = backend === "ollama" ? j.message.content : j.choices[0].message.content
                end(content ? { ok: true, content: content } : { ok: false, error: qsTr("回覆空白") })
            } catch (e) { end({ ok: false, error: qsTr("回覆格式錯誤") }) }
        }
        xhr.open("POST", url)
        xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(JSON.stringify(body))
    }
    Timer { id: timer; property var onFire: null; onTriggered: if (onFire) onFire() }

    // ------------------------------------------------------------ 地圖預覽
    property var _lines: []
    function clearPreview() {
        if (map) _lines.forEach(l => { map.removeMapItem(l); l.destroy() })
        _lines = []
    }
    function drawPreview() {
        clearPreview()
        if (!map || !result || !open) return
        const c = cand(selected)
        if (!c) return
        const line = Qt.createQmlObject('import QtLocation; MapPolyline { line.width: 4; opacity: 0.9 }', map)
        line.line.color = stage === "replan" ? cWarn : cPrimary
        line.path = c.path.map(p => QtPositioning.coordinate(p.lat, p.lon))
        map.addMapItem(line)
        _lines = [line]
    }
    onSelectedChanged: drawPreview()
    onOpenChanged: open ? (result ? drawPreview() : makePlan()) : clearPreview()
    Component.onDestruction: clearPreview()

    // ------------------------------------------------------------ 畫面
    component Btn: Button {
        id: b
        property bool primary: false
        font.pixelSize: root.fs
        contentItem: Text { text: b.text; color: b.primary ? "#06222A" : root.cText; font: b.font; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 6; color: b.primary ? (b.enabled ? root.cPrimary : Qt.darker(root.cPrimary, 2)) : "transparent"; border.color: root.cBorder }
    }
    component Lbl: Text { color: root.cText; font.pixelSize: root.fs; wrapMode: Text.Wrap }
    component Field: TextField {
        implicitWidth: 64; font.pixelSize: root.fs; color: root.cText; inputMethodHints: Qt.ImhFormattedNumbersOnly
        background: Rectangle { color: Qt.rgba(0, 0, 0, 0.4); border.color: root.cBorder; radius: 4 }
    }

    Btn {
        id: toggleBtn
        objectName: "missionAiToggle"
        anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 16
        primary: !root.open
        text: root.open ? qsTr("關閉 AI 建議") : qsTr("AI 任務建議")
        onClicked: root.open = !root.open
    }

    Rectangle {
        id: panel
        visible: root.open
        anchors.left: parent.left; anchors.top: toggleBtn.bottom; anchors.bottom: parent.bottom; anchors.margins: 16
        width: Math.min(520, root.width - 32)
        color: root.cPanel; radius: 10; border.color: root.cBorder

        Flickable {
            anchors.fill: parent; anchors.margins: 14
            contentHeight: col.implicitHeight; clip: true
            ColumnLayout {
                id: col
                width: parent.width
                spacing: 10

                Lbl { text: root.stage === "plan" ? qsTr("① 出發前規劃") : root.stage === "replan" ? qsTr("② 飛行中重規劃（模擬）") : qsTr("③ 智慧任務報告（模擬）")
                      font.pixelSize: root.fs + 4; font.bold: true }
                Lbl {
                    Layout.fillWidth: true; color: root.cMuted; font.pixelSize: root.fs - 2
                    text: qsTr("演算法算數字、產生候選；%1。耗電修正係數 %2。")
                          .arg(root.modelEnabled ? qsTr("模型 %1 只在候選中選").arg(root.modelName) : qsTr("未設定模型，以規則選擇"))
                          .arg(missionSettings.calib.toFixed(2))
                }

                RowLayout {
                    visible: root.stage === "plan"
                    spacing: 6
                    Lbl { text: qsTr("風速") }
                    Field { id: windSpeed; objectName: "windSpeed"
                            text: root.activeVehicle && root.activeVehicle.wind ? root.activeVehicle.wind.speed.rawValue.toFixed(1) : "4" }
                    Lbl { text: qsTr("m/s 風從") }
                    Field { id: windFrom; objectName: "windFrom"
                            text: root.activeVehicle && root.activeVehicle.wind ? root.activeVehicle.wind.direction.rawValue.toFixed(0) : "270" }
                    Lbl { text: "°" }
                    Btn { objectName: "planBtn"; primary: true; text: qsTr("產生候選"); onClicked: root.makePlan() }
                }

                // 選配目標（點一下切換）：選配目標在電量不足時可被略過
                Flow {
                    visible: root.stage === "plan" && root.mission !== null
                    Layout.fillWidth: true; spacing: 6
                    Lbl { text: qsTr("點航點設為選配：") ; color: root.cMuted; font.pixelSize: root.fs - 2 }
                    Repeater {
                        model: root.mission ? root.mission.targets : []
                        delegate: Rectangle {
                            required property var modelData
                            readonly property bool opt: !!root.optional[modelData.id]
                            width: chip.implicitWidth + 16; height: chip.implicitHeight + 8; radius: 12
                            color: opt ? Qt.rgba(0.77, 0.71, 0.99, 0.2) : Qt.rgba(0, 0.83, 0.95, 0.15)
                            border.color: opt ? root.cLlm : root.cPrimary
                            Text { id: chip; anchors.centerIn: parent; color: root.cText; font.pixelSize: root.fs - 2
                                   text: parent.modelData.id + (parent.opt ? qsTr(" 選配") : qsTr(" 必要")) }
                            MouseArea { anchors.fill: parent; onClicked: { const o = Object.assign({}, root.optional); o[parent.modelData.id] = !o[parent.modelData.id]; root.optional = o; root.makePlan() } }
                        }
                    }
                }

                // 預測告警
                Rectangle {
                    visible: root.stage === "replan" && root.alertInfo !== null
                    Layout.fillWidth: true; implicitHeight: alertText.implicitHeight + 16; radius: 6
                    color: Qt.rgba(0.98, 0.75, 0.14, 0.15); border.color: root.cWarn
                    Lbl { id: alertText; anchors.fill: parent; anchors.margins: 8
                          text: root.alertInfo ? qsTr("⚠ 預測告警（%1 分）：%2").arg((root.alertInfo.t_s / 60).toFixed(1)).arg(root.alertInfo.text_zh) : "" }
                }

                // 建議卡
                Rectangle {
                    visible: root.result !== null && root.stage !== "report"
                    Layout.fillWidth: true; implicitHeight: pickCol.implicitHeight + 16; radius: 6
                    color: Qt.rgba(0, 0.83, 0.95, 0.08); border.color: root.result && root.result.pick.source === "llm" ? root.cLlm : root.cPrimary
                    ColumnLayout {
                        id: pickCol; anchors.fill: parent; anchors.margins: 8; spacing: 2
                        Lbl { Layout.fillWidth: true; font.bold: true
                              text: !root.result ? "" : (root.result.pick.decision === "HOLD" ? qsTr("暫緩（HOLD）：請人工判斷")
                                    : qsTr("建議 %1　〔%2〕").arg(root.result.pick.choice_id)
                                         .arg(root.result.pick.source === "llm" ? qsTr("模型") : qsTr("規則")))
                                    + (root.busy ? qsTr("　模型思考中…") : "") }
                        Lbl { Layout.fillWidth: true; color: root.cMuted; text: root.result ? root.result.pick.reason_zh : "" }
                    }
                }

                // 候選清單
                Repeater {
                    model: root.stage !== "report" && root.result ? root.result.candidates : []
                    delegate: Rectangle {
                        id: row
                        required property var modelData
                        objectName: "cand_" + modelData.id
                        Layout.fillWidth: true; implicitHeight: rc.implicitHeight + 12; radius: 6
                        color: root.selected === modelData.id ? Qt.rgba(0, 0.83, 0.95, 0.18) : Qt.rgba(1, 1, 1, 0.04)
                        border.color: root.selected === modelData.id ? root.cPrimary : "transparent"
                        opacity: modelData.feasible ? 1 : 0.55
                        ColumnLayout {
                            id: rc; anchors.fill: parent; anchors.margins: 6; spacing: 0
                            RowLayout {
                                Layout.fillWidth: true
                                Lbl { text: row.modelData.id + "  " + row.modelData.label; font.bold: true; Layout.fillWidth: true }
                                Lbl { text: row.modelData.feasible ? qsTr("可行") : qsTr("不可行"); color: row.modelData.feasible ? root.cOk : root.cCrit }
                            }
                            Lbl { Layout.fillWidth: true; color: root.cMuted; font.pixelSize: root.fs - 2
                                  text: (row.modelData.order.join("→") || qsTr("直接返航")) + qsTr("　%1 km・%2 分・%3 Wh・落地 %4%")
                                        .arg(row.modelData.dist_km).arg(row.modelData.time_min).arg(row.modelData.energy_wh).arg(row.modelData.end_pct) }
                            Lbl { visible: text !== ""; Layout.fillWidth: true; color: root.cCrit; font.pixelSize: root.fs - 2
                                  text: row.modelData.violations.concat(row.modelData.missing_must.map(x => qsTr("缺必要目標 ") + x)).join("；") }
                        }
                        MouseArea { anchors.fill: parent; onClicked: root.selected = row.modelData.id }
                    }
                }

                // 報告
                ColumnLayout {
                    visible: root.stage === "report" && root.report !== null
                    Layout.fillWidth: true; spacing: 6
                    Lbl { Layout.fillWidth: true; text: root.report ? root.report.summary_zh : ""
                          color: root.report && root.report.source === "llm" ? root.cLlm : root.cText }
                    Lbl { text: qsTr("建議"); font.bold: true }
                    Repeater {
                        model: root.report ? root.report.suggestions : []
                        delegate: Lbl {
                            required property var modelData
                            Layout.fillWidth: true
                            color: modelData.level === "crit" ? root.cCrit : modelData.level === "warn" ? root.cWarn : root.cText
                            text: "• " + modelData.text_zh + "  [" + modelData.evidence_ids.join(",") + "]"
                        }
                    }
                    Lbl { text: qsTr("演算法算出的事實"); font.bold: true }
                    Repeater {
                        model: root.report ? root.report.facts : []
                        delegate: Lbl { required property var modelData; Layout.fillWidth: true; color: root.cMuted; font.pixelSize: root.fs - 2
                                        text: modelData.id + "  " + modelData.text }
                    }
                }

                Lbl { visible: root.status !== ""; Layout.fillWidth: true; color: root.cOk; text: root.status }

                Flow {
                    Layout.fillWidth: true; spacing: 8
                    Btn { objectName: "applyBtn"; visible: root.stage === "plan"; primary: true; enabled: !!root.cand(root.selected) && root.cand(root.selected).feasible
                          text: qsTr("套用 %1 的順序").arg(root.selected); onClicked: root.applySelected() }
                    Btn { objectName: "undoBtn"; visible: root.stage === "plan"; enabled: root.undoStack.length > 0
                          text: qsTr("復原（%1）").arg(root.undoStack.length); onClicked: root.undo() }
                    Btn { objectName: "simBtn"; visible: root.stage === "plan"; enabled: !!root.cand(root.selected) && root.cand(root.selected).feasible
                          text: qsTr("模擬飛行與報告"); onClicked: root.simulate() }
                    Lbl { visible: root.stage === "plan"; text: qsTr("中途風速"); color: root.cMuted }
                    Field { id: gustSpeed; visible: root.stage === "plan"; text: "9" }
                    Btn { objectName: "continueBtn"; visible: root.stage === "replan"; primary: true; enabled: !!root.cand(root.selected) && root.cand(root.selected).feasible
                          text: qsTr("確認 %1 並繼續").arg(root.selected); onClicked: root.continueFlight() }
                    Btn { objectName: "calibBtn"; visible: root.stage === "report"; primary: true
                          text: root.report ? qsTr("套用修正係數 %1").arg(root.report.next_calib.toFixed(2)) : ""; onClicked: root.applyCalib() }
                    Btn { visible: root.stage !== "plan"; text: qsTr("回到規劃"); onClicked: root.makePlan() }
                }
            }
        }
    }
}
