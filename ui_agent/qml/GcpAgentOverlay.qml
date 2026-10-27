pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore

import QGroundControl.GCP

import "GcpAgentCore.js" as Core

// 每個畫面都能叫出的介面助理：右側浮動按鈕 → 輸入意圖 → 規則產生候選（必要時問模型挑）→ 套用 → 可多步復原。
// 放在 GcpMainShell 最上層（anchors.fill: parent）。只換頁與調整版面，不送飛行指令、不改參數值。
Item {
    id: root

    // GcpMainShell 傳入：agentLocation()、agentGoTo(page, section)、agentPageName(page)
    property var shell: null
    // 讀環境變數（正式版傳 GcpEnv.value）；預設全部用預設值
    property var envValue: function (name, fallback) { return fallback }

    // Android 上不方便設環境變數：面板內「模型設定」存在 Settings，優先於環境變數
    Settings {
        id: agentSettings
        category: "GCP/Agent"
        property string backend: ""
        property string llmUrl: ""
        property string llmModel: ""
    }
    readonly property string backend: agentSettings.backend || envValue("GCS_LLM_BACKEND", "openai")
    readonly property string modelUrl: agentSettings.llmUrl || envValue("GCS_LLM_URL", "")
    readonly property string modelName: agentSettings.llmModel || envValue("GCS_LLM_MODEL", "")
    readonly property int modelTimeoutMs: parseInt(envValue("GCS_LLM_TIMEOUT_MS", "20000"), 10)
    readonly property bool modelAlways: envValue("GCS_AGENT_LLM_ALWAYS", "0") === "1"
    readonly property bool modelEnabled: backend !== "none" && modelUrl !== ""

    property bool open: false
    property bool busy: false
    property string statusText: ""
    property string messageText: ""
    property var choices: []           // CLARIFY 時讓使用者點選的候選
    property var _pending: null        // 目前的分析結果
    property real _t0: 0

    readonly property color cBg: "#E6111827"
    readonly property color cPanel: "#F2172033"
    readonly property color cLine: "#33FFFFFF"
    readonly property color cText: "#F3F4F6"
    readonly property color cSub: "#9CA3AF"
    readonly property color cAccent: "#22D3EE"
    readonly property color cWarn: "#FBBF24"

    signal decisionLogged(var entry)   // 給測試與記錄用

    // ------------------------------------------------------------ 流程
    function context() {
        const loc = shell && shell.agentLocation ? shell.agentLocation() : { page: 0, section: -1 }
        return { page: loc.page, section: loc.section, modules: GcpAgentState.moduleInfo(),
                 canUndo: GcpAgentState.canUndo, canRedo: GcpAgentState.canRedo }
    }

    function submit(text) {
        text = String(text || "").trim()
        if (!text || busy) return
        choices = []
        messageText = ""
        const ctx = context()
        let result = Core.analyze(text, ctx)
        _pending = result
        _t0 = Date.now()
        const ask = modelEnabled && !result.rule.final && (Core.needsModel(result, modelAlways) || result.candidates.length === 0)
        if (ask && result.candidates.length === 0) {
            // 規則完全沒對到：把全部畫面當候選，讓模型用語意挑
            result.candidates = Core.catalogCandidates(ctx)
        }
        if (ask && result.candidates.length) {
            busy = true
            statusText = qsTr("模型判斷中…")
            callModel(result, ctx, function (model) { busy = false; statusText = ""; finish(result, model) })
        } else {
            finish(result, null)
        }
    }

    // model: null（沒問）或 { ok, decision, choice_id, reason_zh, error, latency_ms }
    function finish(result, model) {
        let decision = result.rule, source = qsTr("規則")
        if (model && model.ok) {
            decision = model
            source = qsTr("模型")
        } else if (model && !model.ok) {
            source = qsTr("規則（模型無效：%1）").arg(model.error)
        }
        // 模型被給全目錄但無效時，規則原本就沒有候選 → 保持 HOLD
        if (decision.decision === "SELECT" && !Core.candidateById(result, decision.choice_id))
            decision = { decision: "HOLD", choice_id: "", reason_zh: qsTr("沒有對應的動作") }

        const entry = { time: new Date().toISOString(), intent: result.intent, rule: result.rule,
                        model: model, final: decision, source: source, backend: backend, modelName: modelName,
                        candidates: result.candidates.slice(0, 6).map(c => c.id), latency_ms: Date.now() - _t0 }
        console.log("[GcpAgent] " + JSON.stringify(entry))
        decisionLogged(entry)

        if (decision.decision === "SELECT") {
            execute(Core.candidateById(result, decision.choice_id), source)
        } else if (decision.decision === "CLARIFY") {
            choices = result.candidates.filter(c => c.score > 0 || source !== qsTr("規則")).slice(0, 6)
            messageText = (decision.reason_zh || qsTr("有多個可能")).replace(/[，。,]?\s*請選一個[：:]?$/, "") + qsTr("，請選一個：")
        } else {
            messageText = decision.reason_zh || qsTr("我沒辦法處理這個要求。可以試試「切到告警中心」或「把風速計移到左上角」。")
        }
    }

    function callModel(result, ctx, done) {
        const xhr = new XMLHttpRequest()
        let finished = false
        const t0 = Date.now()
        function end(r) { if (finished) return; finished = true; timeoutTimer.stop(); r.latency_ms = Date.now() - t0; done(r) }
        timeoutTimer.onFire = function () { xhr.abort(); end({ ok: false, error: qsTr("逾時") }) }
        timeoutTimer.interval = modelTimeoutMs
        timeoutTimer.restart()

        const messages = [{ role: "system", content: Core.SYSTEM_PROMPT },
                          { role: "user", content: Core.buildUserMessage(result, ctx) }]
        let url, body
        if (backend === "ollama") {
            url = modelUrl.replace(/\/$/, "") + "/api/chat"
            body = { model: modelName, messages: messages, stream: false, format: "json", options: { temperature: 0 } }
        } else {
            url = modelUrl.replace(/\/$/, "") + "/chat/completions"
            body = { model: modelName, messages: messages, temperature: 0, max_tokens: 200 }
            if (envValue("GCS_LLM_JSON_MODE", "1") === "1") body.response_format = { type: "json_object" }
        }
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status < 200 || xhr.status >= 300) { end({ ok: false, error: "HTTP " + xhr.status }); return }
            let content = ""
            try {
                const j = JSON.parse(xhr.responseText)
                content = backend === "ollama" ? j.message.content : j.choices[0].message.content
            } catch (e) { end({ ok: false, error: qsTr("回覆格式錯誤") }); return }
            const v = Core.validateModelDecision(Core.extractJson(content), result)
            v.raw = String(content).substring(0, 400)
            end(v)
        }
        xhr.open("POST", url)
        xhr.setRequestHeader("Content-Type", "application/json")
        const key = envValue("GCS_LLM_API_KEY", "")
        if (key) xhr.setRequestHeader("Authorization", "Bearer " + key)
        xhr.send(JSON.stringify(body))
    }

    Timer {
        id: timeoutTimer
        property var onFire: null
        repeat: false
        onTriggered: if (onFire) onFire()
    }

    // ------------------------------------------------------------ 執行
    function execute(c, source) {
        choices = []
        if (!c) return
        if (c.kind === "undo") {
            const labels = GcpAgentState.undo(c.steps || 1)
            messageText = labels.length ? qsTr("已復原：%1").arg(labels.join("、")) : qsTr("目前沒有可復原的變更")
            showToast(messageText, false)
            return
        }
        if (c.kind === "redo") {
            const label = GcpAgentState.redo()
            messageText = label ? qsTr("已重做：%1").arg(label) : qsTr("沒有可重做的變更")
            showToast(messageText, false)
            return
        }
        if (c.kind === "reset_all") {
            const ok = GcpAgentState.resetAll()
            messageText = ok ? qsTr("已全部復原到 agent 介入前（可再按復原取消）") : qsTr("目前沒有任何變更")
            showToast(messageText, ok)
            return
        }
        if (c.kind === "nav") {
            GcpAgentState.beginChange(c.label_zh.replace("切到", "切換到"))
            if (!shell || !shell.agentGoTo(c.page, c.section)) {
                GcpAgentState.cancelChange()
                messageText = qsTr("無法切到這個畫面（帳號權限不足或畫面不存在）")
                return
            }
            done(c, source)
            return
        }
        if (c.kind === "layout") {
            const mod = Core.MODULES.filter(m => m.id === c.module)[0]
            GcpAgentState.beginChange(c.label_zh)
            const loc = context()
            if (mod && loc.page !== mod.page && shell) shell.agentGoTo(mod.page, -1)
            _layoutJob = { c: c, source: source, tries: 0 }
            layoutRetry.restart()   // 換頁後模組要等畫面載入才登記
            return
        }
    }

    property var _layoutJob: null
    Timer {
        id: layoutRetry
        interval: 120
        repeat: false
        onTriggered: {
            const job = root._layoutJob
            if (!job) return
            const c = job.c
            const box = GcpAgentState.baseBox(c.module)
            if (!box) {
                if (++job.tries < 20) { restart(); return }
                root._layoutJob = null
                GcpAgentState.cancelChange()
                root.messageText = qsTr("這個模組目前不在畫面上，沒有調整。")
                return
            }
            root._layoutJob = null
            const arg = c.op === "move" ? c.region : c.op === "nudge" ? c.dir : c.factor
            const next = Core.layoutTarget(c.op, box, { w: box.areaW, h: box.areaH }, GcpAgentState.overrideOf(c.module), arg,
                                            GcpAgentState.otherRects(c.module))
            GcpAgentState.setOverride(c.module, next)
            root.done(c, job.source)
        }
    }

    function done(c, source) {
        messageText = qsTr("已套用：%1（%2）").arg(c.label_zh).arg(source)
        open = false
        showToast(c.label_zh, true)
    }

    // ------------------------------------------------------------ 提示列（面板關閉時也能一鍵復原）
    function showToast(text, withUndo) {
        toast.text = text
        toast.withUndo = withUndo && GcpAgentState.canUndo
        toast.opacity = 1
        toastTimer.restart()
    }
    Timer { id: toastTimer; interval: 7000; onTriggered: toast.opacity = 0 }

    Rectangle {
        id: toast
        property string text: ""
        property bool withUndo: false
        z: 3
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 120
        width: toastRow.implicitWidth + 40
        height: 64
        radius: 32
        color: root.cBg
        border.color: root.cLine
        RowLayout {
            id: toastRow
            anchors.centerIn: parent
            spacing: 20
            Text { text: "✦ " + toast.text; color: root.cText; font.pixelSize: 22 }
            Rectangle {
                visible: toast.withUndo
                Layout.preferredWidth: undoText.implicitWidth + 32
                Layout.preferredHeight: 44
                radius: 22
                color: "transparent"
                border.color: root.cAccent
                Text { id: undoText; anchors.centerIn: parent; text: qsTr("復原"); color: root.cAccent; font.pixelSize: 22; font.bold: true }
                MouseArea {
                    anchors.fill: parent
                    onClicked: { root.execute({ kind: "undo", steps: 1 }, ""); toast.opacity = 0 }
                }
            }
        }
    }

    // ------------------------------------------------------------ 浮動按鈕
    Rectangle {
        id: fab
        objectName: "agentButton"
        z: 2
        width: 76; height: 76; radius: 38
        anchors.right: parent.right
        anchors.rightMargin: root.open ? panel.width + 16 : 20
        y: parent.height * 0.42
        color: root.open ? root.cAccent : root.cBg
        border.color: root.cAccent
        border.width: 2
        Behavior on anchors.rightMargin { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Text {
            anchors.centerIn: parent
            text: root.busy ? "…" : "AI"
            color: root.open ? "#0B1220" : root.cAccent
            font.pixelSize: 26; font.bold: true
        }
        MouseArea {
            anchors.fill: parent
            onClicked: { root.open = !root.open; if (root.open) input.forceActiveFocus() }
        }
    }

    // ------------------------------------------------------------ 面板
    Rectangle {
        id: panel
        objectName: "agentPanel"
        z: 2
        width: Math.min(520, root.width * 0.42)
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 16
        x: root.open ? root.width - width - 16 : root.width + 8
        visible: x < root.width
        Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        radius: 16
        color: root.cPanel
        border.color: root.cLine
        MouseArea { anchors.fill: parent }   // 吃掉點擊，不穿透到下層畫面

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                Text { text: qsTr("介面助理"); color: root.cText; font.pixelSize: 28; font.bold: true }
                Item { Layout.fillWidth: true }
                Text {
                    text: "⚙"; color: settingsForm.visible ? root.cAccent : root.cSub; font.pixelSize: 26
                    MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: settingsForm.visible = !settingsForm.visible }
                }
                Item { Layout.preferredWidth: 18 }
                Text {
                    text: "✕"; color: root.cSub; font.pixelSize: 26
                    MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: root.open = false }
                }
            }
            Text {
                Layout.fillWidth: true
                text: {
                    const page = root.shell ? root.shell.currentPage : -1
                    return qsTr("目前畫面：%1").arg(Core.PAGES.filter(p => p.page === page).map(p => p.name)[0] || "-")
                }
                color: root.cSub; font.pixelSize: 18
            }

            // 模型設定（存在本機，重開 App 仍保留）
            ColumnLayout {
                id: settingsForm
                visible: false
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: [
                        { key: "backend", label: qsTr("後端（openai／ollama／none）"), value: root.backend },
                        { key: "llmUrl", label: qsTr("模型網址，例：http://192.168.50.6:8000/v1"), value: root.modelUrl },
                        { key: "llmModel", label: qsTr("模型名稱"), value: root.modelName }
                    ]
                    delegate: TextField {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredHeight: 48
                        font.pixelSize: 18
                        color: root.cText
                        text: modelData.value
                        placeholderText: modelData.label
                        placeholderTextColor: root.cSub
                        background: Rectangle { radius: 8; color: "#33000000"; border.color: root.cLine }
                        onEditingFinished: agentSettings[modelData.key] = text.trim()
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                TextField {
                    id: input
                    objectName: "agentInput"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 56
                    font.pixelSize: 22
                    color: root.cText
                    placeholderText: qsTr("想做什麼？例如：查看飛行設定")
                    placeholderTextColor: root.cSub
                    enabled: !root.busy
                    background: Rectangle { radius: 10; color: "#33000000"; border.color: input.activeFocus ? root.cAccent : root.cLine }
                    onAccepted: { root.submit(text); text = "" }
                }
                Rectangle {
                    Layout.preferredWidth: 88; Layout.preferredHeight: 56; radius: 10
                    color: root.busy ? root.cLine : root.cAccent
                    Text { anchors.centerIn: parent; text: qsTr("送出"); color: "#0B1220"; font.pixelSize: 22; font.bold: true }
                    MouseArea { anchors.fill: parent; onClicked: { root.submit(input.text); input.text = "" } }
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: [qsTr("我想查看飛行設定"), qsTr("把風速計移到左上角"), qsTr("小地圖放大一點"),
                            qsTr("隱藏底部遙測列"), qsTr("去告警中心")]
                    delegate: Rectangle {
                        required property string modelData
                        width: chipText.implicitWidth + 24; height: 40; radius: 20
                        color: "transparent"; border.color: root.cLine
                        Text { id: chipText; anchors.centerIn: parent; text: parent.modelData; color: root.cSub; font.pixelSize: 17 }
                        MouseArea { anchors.fill: parent; onClicked: root.submit(parent.modelData) }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: text !== ""
                text: root.statusText
                color: root.cWarn; font.pixelSize: 20
            }
            Text {
                objectName: "agentMessage"
                Layout.fillWidth: true
                visible: text !== ""
                text: root.messageText
                wrapMode: Text.Wrap
                color: root.cText; font.pixelSize: 21
            }
            Repeater {
                model: root.choices
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 54
                    radius: 10
                    color: "#1A22D3EE"
                    border.color: root.cAccent
                    Text {
                        anchors.left: parent.left; anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 32; elide: Text.ElideRight
                        text: parent.modelData.label_zh; color: root.cText; font.pixelSize: 20
                    }
                    MouseArea { anchors.fill: parent; onClicked: root.execute(parent.modelData, qsTr("使用者選擇")) }
                }
            }

            Item { Layout.fillHeight: true }

            // 變更紀錄與復原
            Text { text: qsTr("變更紀錄"); color: root.cSub; font.pixelSize: 18 }
            ListView {
                id: historyList
                Layout.fillWidth: true
                Layout.preferredHeight: 190
                clip: true
                model: { GcpAgentState.revision; return GcpAgentState.undoStack.slice().reverse() }
                delegate: Text {
                    required property var modelData
                    required property int index
                    width: historyList.width
                    text: (index === 0 ? "● " : "○ ") + modelData.label
                    color: index === 0 ? root.cText : root.cSub
                    font.pixelSize: 18; elide: Text.ElideRight
                    height: 32
                }
                Text {
                    anchors.centerIn: parent
                    visible: historyList.count === 0
                    text: qsTr("尚無變更"); color: root.cSub; font.pixelSize: 18
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Repeater {
                    model: [
                        { label: qsTr("復原"), kind: "undo", en: GcpAgentState.canUndo },
                        { label: qsTr("重做"), kind: "redo", en: GcpAgentState.canRedo },
                        { label: qsTr("全部復原"), kind: "reset_all", en: GcpAgentState.canUndo }
                    ]
                    delegate: Rectangle {
                        required property var modelData
                        objectName: "agent_" + modelData.kind
                        Layout.fillWidth: true
                        Layout.preferredHeight: 52
                        radius: 10
                        opacity: modelData.en ? 1 : 0.4
                        color: "transparent"
                        border.color: root.cAccent
                        Text { anchors.centerIn: parent; text: parent.modelData.label; color: root.cAccent; font.pixelSize: 20 }
                        MouseArea {
                            anchors.fill: parent
                            enabled: parent.modelData.en
                            onClicked: root.execute({ kind: parent.modelData.kind, steps: 1 }, "")
                        }
                    }
                }
            }
            Text {
                Layout.fillWidth: true
                text: root.modelEnabled ? qsTr("模型：%1（%2）；規則不確定時才詢問").arg(root.modelName || "-").arg(root.backend)
                                        : qsTr("規則模式（未設定 GCS_LLM_URL）")
                color: root.cSub; font.pixelSize: 15; elide: Text.ElideRight
            }
        }
    }
}
