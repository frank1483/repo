pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtPositioning

import "GcpMissionAiCore.js" as Core

// 任務規劃頁的「AI 任務建議」面板（MVP 桌面版，使用者 2026-11-13 確認設計 v1 的 8 項）。
// 讀規劃頁目前的航點 → POST /api/plan（gcs_demo.server :8765）→ 伺服器用演算法產生候選，經閘道 :8090 讓模型在候選內選一條。
// 操作員按「套用」才改航點（只改順序或拿掉選配點），每次套用都可「復原」。不送任何飛行指令。
// 伺服器沒開：顯示「AI 服務未連線」並停用按鈕；這裡沒有規則備援，規則退回只在伺服器做。
// 「模擬飛行與報告」是模擬（風變大 → 預測告警 → 重規劃 → 報告），報告也會出現在遙測頁的「任務報告」子頁。
Item {
    id: root

    property var missionController: null      // PlanMasterController.missionController
    property var map: null                    // 規劃頁地圖（預覽線畫在這裡；null 時不畫）
    property var activeVehicle: null          // 有連線時讀飛控估測風
    property string apiBase: "http://127.0.0.1:8765"   // 插槽傳入 GCS_MVP_API_URL
    property var envValue: function (name, fallback) { return fallback }   // 插槽傳入；面板目前不讀環境變數
    property real panelScale: 1.0

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

    property bool open: false
    property bool online: false
    property string modelName: ""
    property bool busy: false
    property string stage: "plan"             // plan | replan | report
    property var body: null                   // 送去規劃的 mission（WP1…WPn）
    property string bodySig: ""
    property var optional: ({})
    property var result: null
    property string selected: ""
    property var undoStack: []
    property var report: null
    property var alertInfo: null
    property string status: ""

    signal reportReady(var report)

    // ------------------------------------------------------------ 伺服器
    function request(method, path, data, done) {
        const xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            let j = null
            if (xhr.status >= 200 && xhr.status < 300) { try { j = JSON.parse(xhr.responseText) } catch (e) { j = null } }
            root.online = xhr.status > 0
            done(j)
        }
        xhr.open(method, apiBase.replace(/\/$/, "") + path)
        if (data) xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(data ? JSON.stringify(data) : null)
    }
    function checkServer() {
        request("GET", "/api/scenario", null, function (j) {
            root.online = j !== null
            if (j && j.llm) root.modelName = j.llm.model + (j.llm.available ? "" : qsTr("（未設定）"))
        })
    }
    Timer { interval: 5000; running: root.open; repeat: true; triggeredOnStart: true; onTriggered: root.checkServer() }

    // ------------------------------------------------------------ 讀與改規劃頁航點
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
    function snapshot() {
        return waypointItems().map(it => ({ lat: it.coordinate.latitude, lon: it.coordinate.longitude,
                                             alt: it.altitude ? it.altitude.rawValue : 50 }))
    }
    function homeOf(snap) {
        const h = missionController ? missionController.plannedHomePosition : null
        return h && h.isValid ? { lat: h.latitude, lon: h.longitude } : (snap.length ? { lat: snap[0].lat, lon: snap[0].lon } : null)
    }
    function readBody() { const s = snapshot(); return Core.missionBody(s, homeOf(s), optional, 8, qsTr("規劃頁任務")) }

    // 把航點改成 points（數量可以比原來少）；用 QGC 的 removeVisualItem / insertSimpleMissionItem 增減
    function writePoints(points) {
        let items = waypointItems()
        while (items.length > points.length && typeof missionController.removeVisualItem === "function") {
            missionController.removeVisualItem(missionController.visualItems.indexOf(items[items.length - 1]))
            items = waypointItems()
        }
        while (items.length < points.length && typeof missionController.insertSimpleMissionItem === "function") {
            const p = points[items.length]
            missionController.insertSimpleMissionItem(QtPositioning.coordinate(p.lat, p.lon), missionController.visualItems.count, false)
            items = waypointItems()
        }
        for (let i = 0; i < items.length && i < points.length; i++) {
            items[i].coordinate = QtPositioning.coordinate(points[i].lat, points[i].lon)
            if (items[i].altitude) items[i].altitude.rawValue = points[i].alt
        }
        return items.length === points.length
    }

    // ------------------------------------------------------------ 規劃
    function wind() {
        function num(t) { return t.trim() === "" ? 0 : Number(t) }
        return { speed_mps: num(windSpeed.text), from_deg: num(windFrom.text) }
    }
    function makePlan(keepStatus) {
        const b = readBody()
        if (!b) { status = qsTr("請先在地圖上放至少 1 個航點"); return }
        const w = wind()
        if (!isFinite(w.speed_mps) || !isFinite(w.from_deg)) { status = qsTr("風速或風向不是數字"); return }
        busy = true; stage = "plan"; report = null; alertInfo = null
        if (!keepStatus) status = qsTr("規劃中（模型選擇最多約 1 分鐘）…")
        const prev = status
        request("POST", "/api/plan", { mission: b, wind: w }, function (j) {
            root.busy = false
            if (!j) { root.status = root.online ? qsTr("伺服器回應錯誤") : qsTr("AI 服務未連線"); return }
            if (j.ok === false) { root.result = null; root.status = j.reason_zh; return }
            root.body = b; root.bodySig = Core.signature(b)
            root.result = j; root.selected = Core.pickedId(j)
            root.status = keepStatus ? prev : ""
            root.drawPreview()
        })
    }
    function changedSincePlan() { return Core.signature(readBody()) !== bodySig }
    function cand(id) { return result ? Core.find(result.candidates, id) : null }

    // ------------------------------------------------------------ 套用與復原
    function applySelected() {
        const c = cand(selected)
        if (stage !== "plan" || !Core.applicable(c)) { status = qsTr("這個候選不能直接套用"); return }
        if (changedSincePlan()) { status = qsTr("航點在規劃後被改過，請重新產生候選"); return }
        const before = snapshot()
        const r = Core.reorder(before, c)
        if (!r) { status = qsTr("候選與目前航點對不起來，請重新產生候選"); return }
        if (!writePoints(r.points)) { writePoints(before); status = qsTr("無法改動航點，已還原"); return }
        undoStack = undoStack.concat([before])
        optional = ({})
        status = qsTr("已套用 %1%2；可按「復原」").arg(c.id)
                 .arg(r.dropped.length ? qsTr("，拿掉選配點 %1").arg(r.dropped.join("、")) : "")
                 + (c.speed_mps !== body.speed_mps ? qsTr("。建議速度 %1 m/s 請在任務設定中調整").arg(c.speed_mps) : "")
        makePlan(true)
    }
    function undo() {
        if (!undoStack.length) return
        writePoints(undoStack[undoStack.length - 1])
        undoStack = undoStack.slice(0, -1)
        status = qsTr("已復原到上一次套用前的航點")
        makePlan(true)
    }

    // ------------------------------------------------------------ 模擬飛行 → 預測告警 → 重規劃 → 報告
    function simulate() {
        const c = cand(selected)
        if (!Core.applicable(c)) return
        if (changedSincePlan()) { status = qsTr("航點在規劃後被改過，請重新產生候選"); return }
        busy = true; status = qsTr("模擬飛行中…")
        request("POST", "/api/start", { mission_version: result.mission_version, choice_id: c.id }, function (j) {
            root.busy = false
            if (!j || j.ok === false) { root.status = j ? j.reason_zh : qsTr("AI 服務未連線"); return }
            if (j.report) { root.finish(j.report); return }
            root.alertInfo = j.alert
            root.stage = "replan"; root.result = j.replan; root.selected = Core.pickedId(j.replan)
            root.status = ""
            root.drawPreview()
        })
    }
    function continueFlight() {
        const c = cand(selected)
        if (!c || !c.feasible) return
        busy = true; status = qsTr("繼續模擬並撰寫報告（最多約 1.5 分鐘）…")
        request("POST", "/api/continue", { mission_version: result.mission_version, choice_id: c.id }, function (j) {
            root.busy = false
            if (!j || j.ok === false) { root.status = j ? j.reason_zh : qsTr("AI 服務未連線"); return }
            root.finish(j.report)
        })
    }
    function finish(rep) {
        report = rep; stage = "report"; status = qsTr("報告也可在「遙測／飛航數據 → 任務報告」查看")
        clearPreview()
        reportReady(rep)
    }

    // ------------------------------------------------------------ 地圖預覽
    property var _lines: []
    function clearPreview() {
        if (map) _lines.forEach(l => { map.removeMapItem(l); l.destroy() })
        _lines = []
    }
    function drawPreview() {
        clearPreview()
        const c = cand(selected)
        if (!map || !open || !c || !c.path) return
        const line = Qt.createQmlObject('import QtLocation; MapPolyline { line.width: 4; opacity: 0.9 }', map)
        line.line.color = stage === "replan" ? cWarn : cPrimary
        line.path = c.path.map(p => QtPositioning.coordinate(p.lat, p.lon))
        map.addMapItem(line)
        _lines = [line]
    }
    onSelectedChanged: drawPreview()
    onOpenChanged: open ? drawPreview() : clearPreview()
    Component.onDestruction: clearPreview()

    // ------------------------------------------------------------ 畫面
    component Btn: Button {
        id: b
        property bool primary: false
        font.pixelSize: root.fs
        contentItem: Text { text: b.text; color: b.primary ? "#06222A" : root.cText; font: b.font; opacity: b.enabled ? 1 : 0.45
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 6; color: b.primary ? (b.enabled ? root.cPrimary : Qt.darker(root.cPrimary, 2)) : "transparent"; border.color: root.cBorder }
    }
    component Lbl: Text { color: root.cText; font.pixelSize: root.fs; wrapMode: Text.Wrap }
    component Field: TextField {
        implicitWidth: 64; font.pixelSize: root.fs; color: root.cText; inputMethodHints: Qt.ImhFormattedNumbersOnly
        background: Rectangle { color: Qt.rgba(0, 0, 0, 0.4); border.color: root.cBorder; radius: 4 }
    }

    readonly property bool ready: online && !busy

    Btn {
        id: toggleBtn
        objectName: "aiMissionToggle"
        anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 16
        primary: !root.open
        text: root.open ? qsTr("關閉 AI 建議") : qsTr("AI 任務建議")
        onClicked: root.open = !root.open
    }

    Rectangle {
        id: panel
        visible: root.open
        anchors.left: parent.left; anchors.top: toggleBtn.bottom; anchors.bottom: parent.bottom; anchors.margins: 16
        width: Math.min(520 * root.panelScale, root.width - 32)
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
                Rectangle {
                    visible: !root.online
                    Layout.fillWidth: true; implicitHeight: offText.implicitHeight + 16; radius: 6
                    color: Qt.rgba(0.94, 0.27, 0.27, 0.15); border.color: root.cCrit
                    Lbl { id: offText; objectName: "offline"; anchors.fill: parent; anchors.margins: 8
                          text: qsTr("AI 服務未連線（%1）。請先啟動閘道 8090 與任務服務 8765。").arg(root.apiBase) }
                }
                Lbl {
                    visible: root.online
                    Layout.fillWidth: true; color: root.cMuted; font.pixelSize: root.fs - 2
                    text: qsTr("演算法產生候選並算數字；模型 %1 只在候選中選。").arg(root.modelName)
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
                    Btn { objectName: "planBtn"; primary: true; enabled: root.ready; text: qsTr("產生候選"); onClicked: root.makePlan(false) }
                }

                Flow {
                    visible: root.stage === "plan" && root.body !== null
                    Layout.fillWidth: true; spacing: 6
                    Lbl { text: qsTr("點航點設為選配：") ; color: root.cMuted; font.pixelSize: root.fs - 2 }
                    Repeater {
                        model: root.body ? root.body.targets : []
                        delegate: Rectangle {
                            id: chipBox
                            required property var modelData
                            readonly property bool opt: !!root.optional[modelData.id]
                            width: chip.implicitWidth + 16; height: chip.implicitHeight + 8; radius: 12
                            color: opt ? Qt.rgba(0.77, 0.71, 0.99, 0.2) : Qt.rgba(0, 0.83, 0.95, 0.15)
                            border.color: opt ? root.cLlm : root.cPrimary
                            Text { id: chip; anchors.centerIn: parent; color: root.cText; font.pixelSize: root.fs - 2
                                   text: chipBox.modelData.id + (chipBox.opt ? qsTr(" 選配") : qsTr(" 必要")) }
                            MouseArea { anchors.fill: parent; enabled: root.ready
                                        onClicked: { const o = Object.assign({}, root.optional); o[chipBox.modelData.id] = !o[chipBox.modelData.id]; root.optional = o; root.makePlan(false) } }
                        }
                    }
                }

                Rectangle {
                    visible: root.stage === "replan" && !!root.alertInfo
                    Layout.fillWidth: true; implicitHeight: alertText.implicitHeight + 16; radius: 6
                    color: Qt.rgba(0.98, 0.75, 0.14, 0.15); border.color: root.cWarn
                    Lbl { id: alertText; anchors.fill: parent; anchors.margins: 8
                          text: root.alertInfo ? qsTr("⚠ 預測告警：%1　%2").arg(root.alertInfo.title || "").arg(root.alertInfo.text_zh || "") : "" }
                }

                Rectangle {
                    visible: root.result !== null && root.stage !== "report"
                    Layout.fillWidth: true; implicitHeight: pickCol.implicitHeight + 16; radius: 6
                    color: Qt.rgba(0, 0.83, 0.95, 0.08)
                    border.color: root.result && root.result.pick.source === "llm" ? root.cLlm : root.cPrimary
                    ColumnLayout {
                        id: pickCol; anchors.fill: parent; anchors.margins: 8; spacing: 2
                        Lbl { objectName: "pickTitle"; Layout.fillWidth: true; font.bold: true
                              text: !root.result ? "" : (root.result.pick.decision === "HOLD" ? qsTr("暫緩（HOLD）：請人工判斷")
                                    : qsTr("建議 %1　〔%2〕").arg(root.result.pick.choice_id || root.result.rule_choice)
                                         .arg(Core.sourceTag(root.result.pick).zh)) }
                        Lbl { Layout.fillWidth: true; color: root.cMuted; text: root.result ? root.result.pick.reason_zh : "" }
                    }
                }

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
                                  text: ((row.modelData.order || []).join("→") || qsTr("直接返航")) + qsTr("　%1 km・%2 分・%3 Wh・落地 %4%")
                                        .arg(row.modelData.dist_km).arg(row.modelData.time_min).arg(row.modelData.energy_wh).arg(row.modelData.end_pct) }
                            Lbl { visible: !!row.modelData.sorties; Layout.fillWidth: true; color: root.cWarn; font.pixelSize: root.fs - 2
                                  text: qsTr("分兩趟、需換電池：只供參考，不能直接套用") }
                        }
                        MouseArea { anchors.fill: parent; onClicked: root.selected = row.modelData.id }
                    }
                }

                ColumnLayout {
                    visible: root.stage === "report" && root.report !== null
                    Layout.fillWidth: true; spacing: 6
                    Lbl { text: root.report ? Core.reportTag(root.report).zh : ""; color: root.cMuted; font.pixelSize: root.fs - 2 }
                    Lbl { objectName: "reportSummary"; Layout.fillWidth: true; text: root.report ? root.report.summary_zh : ""
                          color: root.report && root.report.source === "llm" ? root.cLlm : root.cText }
                    Repeater {
                        model: root.report ? root.report.suggestions : []
                        delegate: Lbl {
                            required property var modelData
                            Layout.fillWidth: true
                            text: "• " + modelData.text_zh + "  [" + (modelData.evidence_ids || []).join(",") + "]"
                        }
                    }
                }

                Lbl { visible: root.status !== ""; Layout.fillWidth: true; color: root.cOk; text: root.status; objectName: "status" }
                Lbl { visible: root.busy; text: qsTr("處理中…"); color: root.cMuted }

                Flow {
                    Layout.fillWidth: true; spacing: 8
                    Btn { objectName: "applyBtn"; visible: root.stage === "plan"; primary: true
                          enabled: root.ready && Core.applicable(root.cand(root.selected))
                          text: qsTr("套用 %1").arg(root.selected); onClicked: root.applySelected() }
                    Btn { objectName: "undoBtn"; visible: root.stage === "plan"; enabled: root.ready && root.undoStack.length > 0
                          text: qsTr("復原（%1）").arg(root.undoStack.length); onClicked: root.undo() }
                    Btn { objectName: "simBtn"; visible: root.stage === "plan"; enabled: root.ready && Core.applicable(root.cand(root.selected))
                          text: qsTr("模擬飛行與報告"); onClicked: root.simulate() }
                    Btn { objectName: "continueBtn"; visible: root.stage === "replan"; primary: true
                          enabled: root.ready && !!root.cand(root.selected) && root.cand(root.selected).feasible
                          text: qsTr("確認 %1 並繼續（模擬）").arg(root.selected); onClicked: root.continueFlight() }
                    Btn { visible: root.stage !== "plan"; enabled: root.ready; text: qsTr("回到規劃"); onClicked: root.makePlan(false) }
                }
            }
        }
    }
}
