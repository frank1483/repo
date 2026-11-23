pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "GcpAiAgentCore.js" as Core
import "GcpAiAgentBus.js" as Bus
import "GcpAiAgentBuild.js" as Build
import "../Agent/GcpAgentCore.js" as AgentCore
import "../Agent/GcpAgentThemePalette.js" as Palette

// 「AI Agent（方案 A／B）」面板（說明 v3，使用者 2026-11-23 同意）。方案在編譯時寫死（GcpAiAgentBuild.js）。
// 一句話 → 本機 Agent 服務（127.0.0.1，只跑本執行檔的方案）→ 顯示回覆、方向、步驟、引文與提案。
// 提案只有在操作員按「套用」後才改畫面：航線寫進任務規劃頁；版面、文字大小、主題走 UI agent 的狀態與檢查（gateSelection、
// layoutTarget、可復原群組）。每項都能「復原」。飛控類請求只顯示固定說明，這個面板沒有任何送飛控指令的路徑。
Item {
    id: root
    objectName: "aiAgentPanel"

    property var shell: null                  // GcpMainShell：agentLocation()／agentGoTo(page, section)
    property var agentState: null             // UI agent 狀態單例 GcpAgentState（插槽傳入）
    property string apiBase: Build.AGENT_URL  // 插槽傳入 GCS_AB_AGENT_URL；預設是編譯時寫死的埠
    property var envValue: function (name, fallback) { return fallback }
    readonly property string plan: Build.PLAN

    property color cPrimary: plan === "B" ? "#F59E0B" : "#22D3EE"
    property color cPanel: Qt.rgba(0.04, 0.05, 0.07, 0.96)
    property color cBorder: Qt.rgba(1, 1, 1, 0.12)
    property color cText: "white"
    property color cMuted: Qt.rgba(1, 1, 1, 0.6)
    property color cOk: "#4ADE80"
    property color cWarn: "#FBBF24"
    property color cCrit: "#EF4444"
    readonly property real fs: 14 * (agentState && agentState.textScale ? agentState.textScale : 1)

    property bool open: false
    property bool online: false
    property var health: null
    property bool busy: false                 // 等服務回覆
    property bool applying: false             // 正在改畫面
    property real _t0: 0
    property int waitedS: 0
    property var view: null                   // 最近一次回覆
    property var history: []                  // 之前的回覆（最新在前，最多 5 筆）
    property var applied: ({})                // "task:index" → 套用紀錄（復原用）
    property string message: ""
    property string selectedModel: ""
    property int _gen: 0
    property bool showTemplate: false

    // ------------------------------------------------------------ 服務
    function request(method, path, data, done) {
        const xhr = new XMLHttpRequest()
        xhr.onreadystatechange = function () {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            let j = null
            try { j = JSON.parse(xhr.responseText) } catch (e) { j = null }
            root.online = xhr.status > 0
            done(xhr.status, j)
        }
        xhr.open(method, apiBase.replace(/\/$/, "") + path)
        if (data) xhr.setRequestHeader("Content-Type", "application/json")
        xhr.send(data ? JSON.stringify(data) : null)
    }
    function checkHealth() {
        request("GET", "/api/agent/health", null, function (status, j) {
            root.online = status === 200 && j !== null && j.ok === true
            root.health = root.online ? j : null
        })
    }
    Timer { interval: 5000; running: root.open; repeat: true; triggeredOnStart: true; onTriggered: root.checkHealth() }
    Timer { interval: 1000; running: root.busy; repeat: true; onTriggered: root.waitedS = Math.round((Date.now() - root._t0) / 1000) }

    function send(text) {
        text = String(text || "").trim()
        if (!text || busy) return
        if (health && health.plan && health.plan !== plan) { message = qsTr("服務是方案 %1，這個執行檔是方案 %2；請用對應的開啟腳本").arg(health.plan).arg(plan); return }
        busy = true; message = ""; _t0 = Date.now(); waitedS = 0
        const gen = ++_gen
        request("POST", "/api/agent/request", { text: text }, function (status, j) {
            if (gen !== root._gen) return
            root.busy = false
            if (status !== 200 || !j) { root.message = status === 0 ? qsTr("Agent 服務未連線") : qsTr("服務回應錯誤（%1）：%2").arg(status).arg(j && j.error ? j.error : ""); return }
            if (root.view) root.history = [root.view].concat(root.history).slice(0, 5)
            root.view = j
            root.showTemplate = false
            if (!j.ok) root.message = qsTr("執行錯誤：%1").arg(j.error || "")
        })
    }
    function cancelWait() { _gen++; busy = false; message = qsTr("已不等這次回覆（服務端仍會跑完並記錄）") }

    function mark(p, state, detail) {
        if (!view) return
        request("POST", "/api/agent/mark", { task_id: view.task_id, index: p.index, state: state, detail: detail || null }, function () {})
        const props = view.proposals.slice()
        props[p.index] = Object.assign({}, props[p.index], { state: state })
        view = Object.assign({}, view, { proposals: props })
    }
    function keyOf(p) { return (view ? view.task_id : "") + ":" + p.index }
    function setApplied(p, rec) { const a = Object.assign({}, applied); if (rec) a[keyOf(p)] = rec; else delete a[keyOf(p)]; applied = a }

    // ------------------------------------------------------------ 套用
    function finishApply(p, rec, label) {
        applying = false
        setApplied(p, rec)
        mark(p, "APPLIED", label)
        message = qsTr("已套用：%1").arg(label)
    }
    function failApply(p, reason) {
        applying = false
        mark(p, "APPLY_FAILED", reason)
        message = qsTr("套用失敗：%1").arg(reason)
    }
    function topEntry() {
        const s = agentState ? agentState.undoStack : null
        return s && s.length ? { len: s.length, label: s[s.length - 1].label } : { len: 0, label: "" }
    }

    function apply(p) {
        if (applying || busy || !Core.canApply(p, applied[keyOf(p)])) return
        const kind = Core.applyKind(p)
        if (kind !== "route" && kind !== "model" && !agentState) { failApply(p, qsTr("UI agent 未載入")); return }
        applying = true
        message = qsTr("套用中…")
        try {
            if (kind === "route") applyRoute(p)
            else if (kind === "model") {
                const prev = selectedModel
                selectedModel = p.ui.name || p.ui.model_id
                finishApply(p, { kind: "model", prev: prev }, qsTr("選用%1（筆電只有 gemma4:e2b，僅記錄選擇）").arg(selectedModel))
            } else if (kind === "theme") applyTheme(p)
            else applyAgentStep(p)
        } catch (e) { failApply(p, String(e && e.message ? e.message : e)) }
    }

    // 版面與文字大小：和 UI agent 同一套檢查與重排，一個提案一個可復原群組
    property var _layoutJob: null
    function applyAgentStep(p) {
        const c = Core.agentCandidate(p.ui)
        const ctx = { modules: agentState.moduleInfo ? agentState.moduleInfo() : {} }
        const gate = AgentCore.gateSelection({ decision: "SELECT", steps: [{ choice_id: c.id }] }, [c], ctx)
        if (!gate.ok) { failApply(p, qsTr("UI agent 檢查不通過：%1").arg(gate.failures.map(f => f.code).join("、"))); return }
        const checkpoint = agentState.beginGroup()
        if (c.kind === "text_scale") {
            try { agentState.setTextScale(c.value); agentState.commitGroup(checkpoint, c.label_zh, "layout") }
            catch (e) { agentState.rollbackGroup(checkpoint); throw e }
            finishApply(p, Object.assign({ kind: "agent" }, topEntry()), c.label_zh)
            return
        }
        const mod = AgentCore.moduleById(c.module)
        if (!mod || !shell || !shell.agentGoTo(mod.page, -1)) { agentState.rollbackGroup(checkpoint); failApply(p, qsTr("無法開啟%1所在的畫面").arg(mod ? mod.name : c.module)); return }
        _layoutJob = { p: p, c: c, checkpoint: checkpoint, tries: 0, page: mod.page }
        layoutRetry.restart()
    }
    Timer {
        id: layoutRetry
        interval: 120
        onTriggered: {
            const job = root._layoutJob
            if (!job) return
            function fail(reason) { root._layoutJob = null; try { root.agentState.rollbackGroup(job.checkpoint) } catch (e) {} ; root.failApply(job.p, reason) }
            const loc = root.shell && root.shell.agentLocation ? root.shell.agentLocation() : { page: job.page }
            if (loc.page !== job.page) { fail(qsTr("等待時畫面已改變，已還原")); return }
            const box = root.agentState.baseBox(job.c.module)
            if (!box || box.areaW <= 0 || box.areaH <= 0) {
                if (++job.tries < 25) { restart(); return }
                fail(qsTr("元件尚未顯示（多半要先連上載具），已還原")); return
            }
            root._layoutJob = null
            try {
                const c = job.c
                const arg = c.op === "move" ? c.region : c.factor
                const next = AgentCore.layoutTarget(c.op, box, { w: box.areaW, h: box.areaH }, root.agentState.overrideOf(c.module), arg,
                                                    root.agentState.otherRects(c.module), AgentCore.moduleById(c.module))
                root.agentState.setOverride(c.module, next)
                root.agentState.commitGroup(job.checkpoint, c.label_zh, "layout")
            } catch (e) { fail(qsTr("版面調整失敗，已還原")); return }
            root.finishApply(job.p, Object.assign({ kind: "agent" }, root.topEntry()), job.c.label_zh)
        }
    }

    // 主題：深色＝UI agent 預設色彩；高對比＝UI agent 內建捷徑；淺色＝三組固定顏色逐組走 preview 與對比檢查
    function applyTheme(p) {
        const t = p.ui.theme
        if (!agentState.themeReady) { failApply(p, qsTr("主題設定尚未就緒")); return }
        if (t === "dark") {
            const changed = agentState.resetTheme(true)
            finishApply(p, changed ? Object.assign({ kind: "agent" }, topEntry()) : { kind: "none" }, changed ? qsTr("深色（預設色彩）") : qsTr("深色（已是預設色彩，畫面不變）"))
        } else if (t === "high_contrast") {
            agentState.applyThemeHighContrast(agentState.previewThemeHighContrast(), true)
            finishApply(p, Object.assign({ kind: "agent" }, topEntry()), qsTr("高對比"))
        } else if (t === "light") {
            let groups = Palette.checkedGroups(agentState.themeGroups)
            for (const a of Core.LIGHT_ACTIONS) {
                const v = Palette.preview(groups, a, agentState.themePolicy)
                if (v.kind !== "confirm") { failApply(p, qsTr("淺色主題不通過對比檢查（%1）").arg(a.group)); return }
                groups = v.groups
            }
            if (!Palette.verify(groups, agentState.themePolicy).pass) { failApply(p, qsTr("淺色主題最終對比檢查不通過")); return }
            const checkpoint = agentState.beginGroup()
            try { agentState._writeThemeGroups(groups); agentState.commitGroup(checkpoint, qsTr("淺色主題"), "theme") }
            catch (e) { agentState.rollbackGroup(checkpoint); throw e }
            finishApply(p, Object.assign({ kind: "agent" }, topEntry()), qsTr("淺色主題"))
        } else failApply(p, qsTr("不認得的主題：%1").arg(t))
    }

    // 航線：切到任務規劃頁，等接收端就緒後寫航點；記下原本的航點給復原
    property var _routeJob: null
    function applyRoute(p) {
        const pts = Core.checkedPoints(p.ui.points)
        if (!pts) { failApply(p, qsTr("航點資料不合格")); return }
        if (!shell || !shell.agentGoTo(Core.PLANNER_PAGE, -1)) { failApply(p, qsTr("無法切到任務規劃頁")); return }
        _routeJob = { p: p, points: pts, tries: 0, undo: false }
        routeRetry.restart()
    }
    Timer {
        id: routeRetry
        interval: 100
        onTriggered: {
            const job = root._routeJob
            if (!job) return
            const sink = Bus.current()
            if (!sink || !sink.missionController) {
                if (++job.tries < 50) { restart(); return }
                root._routeJob = null
                if (job.undo) { root.applying = false; root.message = qsTr("任務規劃頁沒有就緒，未復原") }
                else root.failApply(job.p, qsTr("任務規劃頁沒有就緒"))
                return
            }
            root._routeJob = null
            if (job.undo) {
                const ok = sink.restore(job.before)
                root.applying = false
                if (ok) { root.setApplied(job.p, null); root.mark(job.p, "UNDONE", qsTr("還原 %1 個航點").arg(job.before.length)); root.message = qsTr("已復原航點") }
                else root.message = qsTr("航點還原失敗")
                return
            }
            const r = sink.apply(job.points)
            if (r.ok) root.finishApply(job.p, { kind: "route", before: r.before }, qsTr("寫入 %1 個航點到任務規劃頁").arg(job.points.length))
            else root.failApply(job.p, r.reason)
        }
    }

    // ------------------------------------------------------------ 復原
    function undo(p) {
        const rec = applied[keyOf(p)]
        if (!rec || applying) return
        if (rec.kind === "route") {
            if (!shell || !shell.agentGoTo(Core.PLANNER_PAGE, -1)) { message = qsTr("無法切到任務規劃頁"); return }
            applying = true
            _routeJob = { p: p, before: rec.before, tries: 0, undo: true }
            routeRetry.restart()
            return
        }
        if (rec.kind === "model") selectedModel = rec.prev
        else if (rec.kind === "agent") {
            const top = topEntry()
            if (top.len !== rec.len || top.label !== rec.label) { message = qsTr("之後畫面還有其他變更；請先用右側 AI 按鈕的復原，回到這一步再按"); return }
            agentState.undo(1)
        }
        setApplied(p, null)
        mark(p, "UNDONE", "")
        message = qsTr("已復原：%1").arg(p.label)
    }

    function openReport() { if (!shell || !shell.agentGoTo(Core.TELEMETRY_PAGE, Core.REPORT_SECTION)) message = qsTr("無法開啟智慧任務報告子頁") }

    // ------------------------------------------------------------ 畫面
    component Btn: Button {
        id: b
        property bool primary: false
        font.pixelSize: root.fs
        contentItem: Text { text: b.text; color: b.primary ? "#06222A" : root.cText; font: b.font; opacity: b.enabled ? 1 : 0.45
                            horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { radius: 6; color: b.primary ? (b.enabled ? root.cPrimary : Qt.darker(root.cPrimary, 2)) : "transparent"; border.color: root.cBorder }
    }
    component Lbl: Text { color: root.cText; font.pixelSize: root.fs; wrapMode: Text.Wrap; Layout.fillWidth: true }
    component Head: Text { color: root.cPrimary; font.pixelSize: root.fs; font.bold: true; Layout.fillWidth: true; Layout.topMargin: 6 }

    Rectangle {
        id: fab
        objectName: "aiAgentToggle"
        width: 76; height: 76; radius: 38
        anchors.right: parent.right
        anchors.rightMargin: 20
        y: parent.height * 0.42 + 96          // UI agent 的 AI 按鈕正下方
        visible: !root.open
        color: Qt.rgba(0.07, 0.09, 0.15, 0.9)
        border.color: root.cPrimary; border.width: 2
        Text { anchors.centerIn: parent; text: root.busy ? "…" : root.plan; color: root.cPrimary; font.pixelSize: 26; font.bold: true }
        MouseArea { anchors.fill: parent; onClicked: { root.open = true; input.forceActiveFocus() } }
    }

    Rectangle {
        id: panel
        objectName: "aiAgentBox"
        visible: root.open
        width: Math.min(root.width - 32, Math.max(380, root.width * 0.36))
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        anchors.margins: 16; anchors.topMargin: 96
        radius: 12; color: root.cPanel; border.color: root.cBorder
        MouseArea { anchors.fill: parent }    // 不穿透到下層畫面

        ColumnLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Text { text: qsTr("AI Agent · %1").arg(Core.planTitle(root.plan)); color: root.cPrimary; font.pixelSize: root.fs + 2; font.bold: true; Layout.fillWidth: true; elide: Text.ElideRight }
                Btn { text: qsTr("收起"); onClicked: root.open = false }
            }
            Text {
                Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: root.fs - 2
                color: root.online ? root.cMuted : root.cWarn
                text: !root.online ? qsTr("Agent 服務未連線（%1）").arg(root.apiBase)
                      : qsTr("服務：%1，%2，模型 %3").arg(root.health.plan_name).arg(root.health.mode === "live" ? qsTr("真模型") : qsTr("假模型"))
                          .arg(root.health.model || "—") + (root.selectedModel ? qsTr("；已選定 %1").arg(root.selectedModel) : "")
            }
            RowLayout {
                Layout.fillWidth: true
                TextField {
                    id: input
                    objectName: "aiAgentInput"
                    Layout.fillWidth: true
                    font.pixelSize: root.fs; color: root.cText
                    placeholderText: qsTr("輸入一句話，例如：規劃北側巡檢的覆蓋航線，風速計放大")
                    placeholderTextColor: root.cMuted
                    background: Rectangle { color: Qt.rgba(0, 0, 0, 0.4); border.color: root.cBorder; radius: 4 }
                    enabled: !root.busy
                    onAccepted: root.send(text)
                }
                Btn { objectName: "aiAgentSend"; primary: true; text: qsTr("送出"); enabled: root.online && !root.busy && input.text.trim() !== ""; onClicked: root.send(input.text) }
            }
            RowLayout {
                visible: root.busy
                Lbl { text: qsTr("%1 處理中… %2 秒").arg(Core.planTitle(root.plan)).arg(root.waitedS); color: root.cWarn }
                Btn { text: qsTr("不等了"); onClicked: root.cancelWait() }
            }
            Lbl { objectName: "aiAgentMessage"; visible: root.message !== ""; text: root.message; color: root.cWarn }

            ScrollView {
                Layout.fillWidth: true; Layout.fillHeight: true
                clip: true
                contentWidth: availableWidth
                ColumnLayout {
                    width: parent.width
                    spacing: 4
                    visible: root.view !== null
                    Head { text: qsTr("回覆") + "  ·  " + Core.replySourceZh(root.view) }
                    Lbl { objectName: "aiAgentReply"; text: root.view ? root.view.reply : ""; font.bold: true }
                    Text {
                        visible: root.view !== null && root.view.reply_template && root.view.reply_template !== root.view.reply
                        text: root.showTemplate ? qsTr("▼ 模板原文：") + (root.view ? root.view.reply_template : "") : qsTr("▶ 看模板原文")
                        color: root.cMuted; font.pixelSize: root.fs - 2; wrapMode: Text.Wrap; Layout.fillWidth: true
                        MouseArea { anchors.fill: parent; onClicked: root.showTemplate = !root.showTemplate }
                    }
                    Lbl { visible: root.view !== null && !!root.view.flight_notice; text: root.view && root.view.flight_notice ? String(root.view.flight_notice.text || root.view.flight_notice.reply_zh || JSON.stringify(root.view.flight_notice)) : ""; color: root.cWarn }

                    Head { text: qsTr("方向（第 1 段排序）") }
                    Lbl {
                        text: root.view ? (root.view.directions || []).map(d => Core.dirZh(d) + "：" + ((root.view.dir_status || {})[d] || "")).join("　") || qsTr("（無）") : ""
                    }
                    Head { text: root.plan === "B" ? qsTr("計畫步驟") : qsTr("逐步步驟") }
                    Lbl { objectName: "aiAgentSteps"; text: root.view ? Core.stepLines(root.view.steps).join("\n") || qsTr("（無）") : ""; font.pixelSize: root.fs - 1 }
                    Lbl { visible: root.plan === "B" && root.view !== null && root.view.replans !== undefined && root.view.replans !== null; text: root.view ? qsTr("重規劃 %1 次").arg(root.view.replans) : ""; color: root.cMuted }
                    Lbl { visible: text !== ""; text: root.view ? Core.outcomeLines(root.view.outcomes).join("\n") : ""; color: root.cMuted; font.pixelSize: root.fs - 1 }

                    Head { visible: root.view !== null && !!root.view.manual; text: qsTr("手冊引文") }
                    Repeater {
                        model: root.view && root.view.manual ? root.view.manual.refs : []
                        delegate: Lbl {
                            required property var modelData
                            text: "• " + [modelData.manual, modelData.section || modelData.title, modelData.chunk_id].filter(x => x).join(" · ") +
                                  (modelData.text ? "\n  " + String(modelData.text).slice(0, 160) : "")
                            font.pixelSize: root.fs - 1
                        }
                    }
                    Lbl { visible: root.view !== null && root.view.qa !== null && root.view.qa !== undefined; text: qsTr("問答：工具在 v3.11 還沒接上，只會回部分完成"); color: root.cMuted }
                    Btn { visible: root.view !== null && !!root.view.report; text: qsTr("開啟智慧任務報告子頁"); onClicked: root.openReport() }

                    Head { text: qsTr("提案（按「套用」才會改畫面）") }
                    Lbl { visible: root.view !== null && !(root.view.proposals || []).length; text: qsTr("（沒有提案）"); color: root.cMuted }
                    Repeater {
                        objectName: "aiAgentProposals"
                        model: root.view ? root.view.proposals : []
                        delegate: Rectangle {
                            id: card
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: cardCol.implicitHeight + 12
                            radius: 6; color: Qt.rgba(1, 1, 1, 0.04); border.color: root.cBorder
                            ColumnLayout {
                                id: cardCol
                                anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6
                                Lbl { text: (card.modelData.label || card.modelData.action) + "　[" + Core.stateZh(card.modelData.state) + "]"
                                      color: card.modelData.supported ? root.cText : root.cMuted }
                                Lbl { visible: card.modelData.ui && card.modelData.ui.kind === "route" && !!card.modelData.ui.evaluation
                                      text: card.modelData.ui && card.modelData.ui.evaluation ? qsTr("預覽驗算：%1，預估落地電量 %2%").arg(card.modelData.ui.evaluation.result)
                                          .arg(Number(card.modelData.ui.evaluation.est_end_pct || 0).toFixed(1)) : ""
                                      color: root.cMuted; font.pixelSize: root.fs - 2 }
                                RowLayout {
                                    Btn { objectName: "apply_" + card.modelData.index; primary: true; text: qsTr("套用")
                                          enabled: !root.applying && !root.busy && Core.canApply(card.modelData, root.applied[root.keyOf(card.modelData)])
                                          onClicked: root.apply(card.modelData) }
                                    Btn { objectName: "undo_" + card.modelData.index; text: qsTr("復原")
                                          enabled: !root.applying && !!root.applied[root.keyOf(card.modelData)]
                                          onClicked: root.undo(card.modelData) }
                                }
                            }
                        }
                    }
                    Lbl { text: Core.timing(root.view); color: root.cMuted; font.pixelSize: root.fs - 2; Layout.topMargin: 6 }
                    Lbl { visible: root.history.length > 0; text: qsTr("之前：") + root.history.map(h => h.text).join("｜"); color: root.cMuted; font.pixelSize: root.fs - 2 }
                }
            }
        }
    }
}
