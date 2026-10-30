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
        property int llmTimeoutMs: 0 // 0 inherits environment/default; panel overrides only when positive.
    }
    readonly property string backend: agentSettings.backend || envValue("GCS_LLM_BACKEND", "openai")
    readonly property string modelUrl: agentSettings.llmUrl || envValue("GCS_LLM_URL", "")
    readonly property string modelName: agentSettings.llmModel || envValue("GCS_LLM_MODEL", "")
    readonly property int modelTimeoutMs: resolvedModelTimeoutMs()
    readonly property bool modelAlways: envValue("GCS_AGENT_LLM_ALWAYS", "0") === "1"
    readonly property bool modelEnabled: backend !== "none" && modelUrl !== ""

    property bool open: false
    property bool busy: false
    property string statusText: ""
    property string messageText: ""
    property string modelNotice: "" // Separate from action text so rule fallback remains visible.
    property var choices: []           // CLARIFY 時讓使用者點選的候選
    property string pendingText: "" // No timer: retained until completion/cancel/save/close.
    property var _pending: null        // 目前的分析結果
    property real _t0: 0
    property var _cancelModel: null
    property int _modelGeneration: 0
    property var _confirmation: null   // Detached plan; no execution until explicit Yes.
    property var _choiceGuard: null
    readonly property bool canSaveLayout: !busy && GcpAgentState.hasUnsavedChanges
    property var changeLog: []         // Session log includes undone actions; never written to Settings.

    function resolvedModelTimeoutMs() {
        const saved = Number(agentSettings.llmTimeoutMs)
        const n = isFinite(saved) && saved > 0 ? saved : Number(envValue("GCS_LLM_TIMEOUT_MS", "60000"))
        return isFinite(n) && n > 0 ? Math.max(1, Math.min(120000, Math.floor(n))) : 60000
    }

    function setModelTimeout(text) {
        if (busy) return false
        const value = String(text).trim()
        if (value === "") { agentSettings.llmTimeoutMs = 0; return true }
        // Panel accepts whole milliseconds; malformed edits never change the prior setting.
        if (!/^[0-9]+$/.test(value)) return false
        const n = Number(value)
        if (!isFinite(n) || n < 1 || n > 120000) return false
        agentSettings.llmTimeoutMs = n
        return true
    }

    function recordChange(text) {
        changeLog = [{ label: text, time: new Date().toISOString() }].concat(changeLog).slice(0, 50)
    }

    readonly property color cBg: "#E6111827"
    readonly property color cPanel: "#F2172033"
    readonly property color cLine: "#33FFFFFF"
    readonly property color cText: "#F3F4F6"
    readonly property color cSub: "#9CA3AF"
    readonly property color cAccent: "#22D3EE"
    readonly property color cWarn: "#FBBF24"

    signal decisionLogged(var entry)   // 給測試與記錄用

    onOpenChanged: {
        if (!open) {
            clearConfirmation()
            pendingText = ""
            choices = []
            _pending = null
            _choiceGuard = null
            if (_cancelModel) cancelWaiting()
        }
    }

    // ------------------------------------------------------------ 流程
    function context() {
        const loc = shell && shell.agentLocation ? shell.agentLocation() : { page: 0, section: -1 }
        return { page: loc.page, section: loc.section, modules: GcpAgentState.moduleInfo(),
                 textScale: GcpAgentState.textScale, canUndo: GcpAgentState.canUndo, canRedo: GcpAgentState.canRedo, layoutNames: GcpAgentState.layoutNames() }
    }

    function sameContext(guard) {
        const now = context()
        return guard && guard.revision === GcpAgentState.revision && guard.page === now.page && guard.section === now.section
    }

    function cancelWaiting() {
        modelNotice = ""
        clearConfirmation()
        pendingText = ""
        _modelGeneration++
        if (_transaction) failSteps(qsTr("已取消，已還原整組"))
        if (_cancelModel) _cancelModel()
        busy = false
        statusText = ""
        choices = []
        _pending = null
        _choiceGuard = null
        messageText = qsTr("已取消")
    }

    function submit(text) {
        text = String(text || "").trim()
        if (/^(取消|算了|cancel)[。！!]?$/i.test(text)) { cancelWaiting(); return }
        if (!text || busy) return
        modelNotice = ""
        clearConfirmation()
        choices = []
        messageText = ""
        const ctx = context()
        let result = Core.analyzeTurn(text, ctx, pendingText)
        if (!result.pending_intent) pendingText = ""
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
            const generation = ++_modelGeneration
            const guard = { revision: GcpAgentState.revision, page: ctx.page, section: ctx.section }
            callModel(result, ctx, function (model) {
                if (generation !== _modelGeneration) return
                busy = false
                statusText = ""
                if (!sameContext(guard)) {
                    _pending = null
                    choices = []
                    messageText = qsTr("畫面已改變，請再說一次")
                    return
                }
                finish(result, model)
            })
        } else {
            finish(result, null)
        }
    }

    // model: null（沒問）或 { ok, decision, choice_id, reason_zh, error, latency_ms }
    function finish(result, model) {
        modelNotice = model && !model.ok ? qsTr("模型未完成（%1），已改用規則判斷。").arg(model.error) : ""
        let decision = result.rule, source = qsTr("規則")
        if (model && model.ok) {
            decision = model
            source = qsTr("模型")
        } else if (model && !model.ok) {
            source = qsTr("規則（模型無效：%1）").arg(model.error)
        }
        // A generic settings utterance must stay a clarification: a model cannot
        // invent which setting the user meant. Model errors use the same fallback.
        if (result.generic_settings) { decision = result.rule; source = qsTr("規則（設定目標待確認）") }
        // 模型被給全目錄但無效時，規則原本就沒有候選 → 保持 HOLD
        const selectedIds = decision.steps ? decision.steps.map(s => s.choice_id) : [decision.choice_id]
        if (decision.decision === "SELECT" && (!selectedIds.length || selectedIds.length > Core.MAX_PLAN_STEPS ||
            selectedIds.some(id => !Core.candidateById(result, id))))
            decision = { decision: "HOLD", choice_id: "", reason_zh: qsTr("沒有對應的動作") }

        const entry = { time: new Date().toISOString(), intent: result.intent, rule: result.rule,
                        model: model, final: decision, source: source, backend: backend, modelName: modelName,
                        candidates: result.candidates.slice(0, 6).map(c => c.id), latency_ms: Date.now() - _t0 }
        console.log("[GcpAgent] " + JSON.stringify(entry))
        decisionLogged(entry)

        if (decision.decision === "SELECT") {
            const steps = selectedIds.map(id => Core.candidateById(result, id))
            requestExecution(steps, source, {
                modelSelected: decision === model,
                goal: result.goal_intent === true,
                ruleUnique: result.rule.decision === "SELECT" && !result.compound && steps.length === 1 &&
                    result.rule.choice_id === steps[0].id &&
                    result.candidates.filter(c => c.score >= 0.75).length === 1,
                intent: result.intent
            })
        } else if (decision.decision === "CLARIFY") {
            pendingText = result.intent
            const loc = context()
            _choiceGuard = { revision: GcpAgentState.revision, page: loc.page, section: loc.section }
            const available = result.candidates.filter(c => c.score > 0 || source !== qsTr("規則"))
            choices = result.compound ? [] : (result.generic_settings ? available : available.slice(0, 6))
            messageText = result.compound ? decision.reason_zh : (decision.reason_zh || qsTr("有多個可能")).replace(/[，。,]?\s*請選一個[：:]?$/, "") + qsTr("，請選一個：")
        } else {
            pendingText = result.pending_text || ""
            messageText = decision.reason_zh || qsTr("我沒辦法處理這個要求。可以試試「切到告警中心」或「把風速計移到左上角」。")
        }
    }

    // The future goal planner must call this gate with goal:true after building its plan.
    // Item6 is deliberately not implemented by this item4 patch.
    function clearConfirmation() {
        _confirmation = null
    }

    function requestExecution(steps, source, policy) {
        if (busy || _transaction) return
        clearConfirmation()
        choices = []
        if (!Array.isArray(steps) || !steps.length || steps.length > Core.MAX_PLAN_STEPS ||
            steps.some(c => !c || ["nav", "layout", "text_scale", "layout_load", "layout_default",
                "layout_save_current", "layout_save", "undo", "redo", "reset_all"].indexOf(c.kind) < 0) ||
            (steps.length > 1 && steps.some(c => ["nav", "layout", "text_scale"].indexOf(c.kind) < 0))) {
            messageText = qsTr("沒有可確認的介面動作，請改說")
            return
        }
        policy = policy || {}
        const requireCard = policy.modelSelected === true || policy.goal === true || steps.length > 1 ||
            (steps[0].kind !== "nav" && policy.ruleUnique !== true && policy.userSelected !== true)
        // Detach from model/rule candidates so they cannot mutate a plan after it is shown.
        const plan = JSON.parse(JSON.stringify(steps))
        if (!requireCard) { executeSteps(plan, source); return }
        const loc = context()
        _confirmation = { steps: plan, source: source, intent: policy.intent || "",
            guard: { revision: GcpAgentState.revision, page: loc.page, section: loc.section } }
        pendingText = ""
        messageText = ""
        decisionLogged({ phase: "confirmation_required", intent: _confirmation.intent,
            steps: plan.map(c => c.id), model_selected: policy.modelSelected === true,
            goal: policy.goal === true, executed: false })
    }

    function confirmationSummary() {
        if (!_confirmation) return ""
        const marks = ["①", "②", "③", "④", "⑤"]
        return qsTr("我理解你要：") + "\n" + _confirmation.steps.map((c, i) =>
            marks[i] + " " + c.label_zh).join("\n") + "\n" + qsTr("對嗎？")
    }

    function confirmIntent() {
        if (busy || _transaction || !_confirmation) return
        const pending = _confirmation
        clearConfirmation() // Consume before dispatch: repeated clicks cannot apply it twice.
        if (!sameContext(pending.guard)) {
            pendingText = ""
            _pending = null
            choices = []
            messageText = qsTr("畫面已改變，請再說一次")
            return
        }
        _pending = null
        decisionLogged({ phase: "confirmation_accepted", intent: pending.intent,
            steps: pending.steps.map(c => c.id), source: pending.source })
        executeSteps(pending.steps, pending.source)
    }

    function rejectIntent() {
        if (!_confirmation || busy) return
        const intent = _confirmation.intent
        clearConfirmation()
        pendingText = ""
        choices = []
        _pending = null
        messageText = qsTr("請改說你想做什麼，尚未套用任何動作")
        decisionLogged({ phase: "confirmation_rejected", intent: intent, executed: false })
        input.forceActiveFocus()
    }

    function callModel(result, ctx, done) {
        let xhr = null, finished = false, fallbackSent = false
        const t0 = Date.now(), requestBackend = backend
        // Snapshot connection settings for the whole request, including any schema retry.
        const requestUrl = modelUrl.replace(/\/+$/, ""), requestModel = modelName
        const requestTimeoutMs = modelTimeoutMs, requestKey = envValue("GCS_LLM_API_KEY", "")
        // Native Ollama always receives the candidate-bound schema. The env switch is OpenAI-only.
        const schemaOn = requestBackend === "ollama" || envValue("GCS_LLM_SCHEMA", "1") === "1"
        const schema = Core.decisionSchema(result)
        function end(r) {
            if (finished) return
            finished = true
            timeoutTimer.stop()
            timeoutTimer.onFire = null
            root._cancelModel = null
            r.latency_ms = Date.now() - t0
            r.timeout_ms = requestTimeoutMs
            r.request_backend = requestBackend
            r.request_model = requestModel
            done(r)
        }
        root._cancelModel = function () {
            if (finished) return
            finished = true
            timeoutTimer.stop()
            timeoutTimer.onFire = null
            root._cancelModel = null
            if (xhr) xhr.abort()
        }
        timeoutTimer.onFire = function () {
            if (finished) return
            const active = xhr
            end({ ok: false, error_code: "TIMEOUT", error: qsTr("等待超過 %1 秒").arg(requestTimeoutMs / 1000) })
            if (active) active.abort()
        }
        timeoutTimer.interval = requestTimeoutMs
        timeoutTimer.restart() // One deadline covers both attempts.
        const messages = [{ role: "system", content: Core.SYSTEM_PROMPT },
                          { role: "user", content: Core.buildUserMessage(result, ctx) }]
        function send(useSchema) {
            const current = new XMLHttpRequest()
            xhr = current
            let url, body
            if (requestBackend === "ollama") {
                url = requestUrl + "/api/chat"
                body = { model: requestModel, messages: messages, stream: false,
                         format: schema, options: { temperature: 0 } }
            } else {
                url = requestUrl + "/chat/completions"
                body = { model: requestModel, messages: messages, temperature: 0, max_tokens: 500 }
                if (useSchema) body.response_format = { type: "json_schema",
                    json_schema: { name: "gcp_ui_decision", strict: false, schema: schema } }
                else if (fallbackSent || envValue("GCS_LLM_JSON_MODE", "1") === "1")
                    body.response_format = { type: "json_object" }
            }
            current.onreadystatechange = function () {
                if (finished || current !== xhr || current.readyState !== XMLHttpRequest.DONE) return
                if (requestBackend !== "ollama" && useSchema && current.status === 400 && !fallbackSent) {
                    fallbackSent = true
                    send(false)
                    return
                }
                if (current.status < 200 || current.status >= 300) { end({ ok: false, error: "HTTP " + current.status }); return }
                let content = ""
                try {
                    const j = JSON.parse(current.responseText)
                    content = requestBackend === "ollama" ? j.message.content : j.choices[0].message.content
                } catch (e) { end({ ok: false, error: qsTr("回覆格式錯誤") }); return }
                const v = Core.validateModelDecision(Core.extractJson(content), result)
                v.raw = String(content).substring(0, 400)
                v.schema_fallback = fallbackSent
                end(v)
            }
            try {
                current.open("POST", url)
                current.setRequestHeader("Content-Type", "application/json")
                if (requestKey) current.setRequestHeader("Authorization", "Bearer " + requestKey)
                current.send(JSON.stringify(body))
            } catch (e) { end({ ok: false, error: qsTr("無法建立模型請求") }); current.abort() }
        }
        send(schemaOn)
    }

    Timer {
        id: timeoutTimer
        property var onFire: null
        repeat: false
        onTriggered: if (onFire) onFire()
    }

    // ------------------------------------------------------------ 執行
    function choose(c) {
        if (!sameContext(_choiceGuard)) {
            choices = []
            messageText = qsTr("畫面已改變，請再說一次")
            return
        }
        requestExecution([c], qsTr("使用者選擇"), { userSelected: true,
            goal: _pending && _pending.goal_intent === true, intent: _pending ? _pending.intent : "" })
    }

    function execute(c, source) {
        if (busy || _transaction) return
        if (root._confirmation) root.clearConfirmation()
        choices = []
        if (!c) return
        if (c.kind === "layout_save_current") {
            pendingText = ""
            if (!canSaveLayout) { messageText = qsTr("沒有未儲存的版面變更"); return }
            try {
                GcpAgentState.saveCurrentLayout()
                messageText = qsTr("已儲存版面，重開後會套回這一版")
                recordChange(messageText)
            } catch (e) {
                console.warn("[GcpAgent] Explicit save failed; prior Settings retained: " + e)
                messageText = qsTr("無法儲存版面，原設定保留，請查看紀錄")
            }
            return
        }
        if (c.kind === "layout_save") {
            pendingText = ""
            try { GcpAgentState.saveLayout(c.name); messageText = qsTr("已儲存：%1").arg(c.name); recordChange(messageText) }
            catch (e) { messageText = qsTr("無法儲存版面，未變更設定") }
            return
        }
        if (c.kind === "undo") {
            const entry = GcpAgentState.undoStack[GcpAgentState.undoStack.length - 1]
            const beforeLayout = GcpAgentState.layoutFingerprint()
            const labels = GcpAgentState.undo(c.steps || 1)
            messageText = labels.length ? qsTr("已復原：%1").arg(labels.join("、")) + GcpAgentState.undoHint() : qsTr("目前沒有可復原的變更")
            pendingText = ""
            if (labels.length) { recordChange(messageText); showHistoryToast("redo", entry, beforeLayout) }
            return
        }
        if (c.kind === "redo") {
            const entry = GcpAgentState.redoStack[GcpAgentState.redoStack.length - 1]
            const beforeLayout = GcpAgentState.layoutFingerprint()
            const label = GcpAgentState.redo()
            messageText = label ? qsTr("已重做：%1").arg(label) : qsTr("沒有可重做的變更")
            pendingText = ""
            if (label) { recordChange(messageText); showHistoryToast("undo", entry, beforeLayout) }
            return
        }
        if (c.kind === "reset_all") {
            pendingText = ""
            const beforeLayout = GcpAgentState.layoutFingerprint()
            const ok = GcpAgentState.resetAll()
            messageText = ok ? qsTr("已全部復原到 agent 介入前（可再按復原取消）") : qsTr("目前沒有任何變更")
            if (ok) {
                recordChange(messageText)
                showToast(beforeLayout !== GcpAgentState.layoutFingerprint() ? "layout" : "navigation", "undo")
            }
            return
        }
        executeSteps([c], source)
    }

    property var _transaction: null
    property var _layoutJob: null
    function executeSteps(steps, source) {
        if (busy || _transaction || !Array.isArray(steps) || !steps.length ||
            steps.length > Core.MAX_PLAN_STEPS || steps.some(c => !c)) return
        if (steps.length === 1 && ["nav", "layout", "text_scale", "layout_load", "layout_default"].indexOf(steps[0].kind) < 0) {
            execute(steps[0], source)
            return
        }
        if (steps.some(c => ["nav", "layout", "text_scale", "layout_load", "layout_default"].indexOf(c.kind) < 0) ||
            (steps.length > 1 && steps.some(c => ["nav", "layout", "text_scale"].indexOf(c.kind) < 0))) {
            messageText = qsTr("這些動作必須分開操作")
            return
        }
        if (root._confirmation) root.clearConfirmation()
        choices = []
        const label = steps.map(c => c.label_zh).join("、")
        const checkpoint = GcpAgentState.beginGroup()
        _transaction = { steps: steps, index: 0, source: source, label: label,
                         checkpoint: checkpoint, layoutGroup: false,
                         beforeLayout: GcpAgentState.layoutFingerprint() }
        _transaction.layoutLabel = steps.filter(c => c.kind !== "nav").map(c => c.label_zh).join("、")
        busy = true
        advanceSteps()
    }

    function failSteps(reason) {
        layoutRetry.stop()
        _layoutJob = null
        if (_transaction) GcpAgentState.rollbackGroup(_transaction.checkpoint)
        _transaction = null
        busy = false
        statusText = ""
        messageText = reason
    }

    function navigateStep(page, section) {
        const loc = context()
        if (loc.page === page && (section < 0 || loc.section === section)) return true
        GcpAgentState.beginChange(qsTr("換頁：%1 → %2").arg(Core.pageName(loc.page)).arg(Core.pageName(page)), "navigation")
        if (!shell || !shell.agentGoTo(page, section)) return false
        _transaction.layoutGroup = false
        return true
    }
    function beginLayoutStep() {
        if (_transaction.layoutGroup) return
        GcpAgentState.beginChange(_transaction.layoutLabel, "layout")
        _transaction.layoutGroup = true
    }

    function advanceSteps() {
        const tx = _transaction
        if (!tx) return
        if (tx.index >= tx.steps.length) {
            const after = GcpAgentState.snapshot()
            const layoutChanged = tx.beforeLayout !== GcpAgentState.layoutFingerprint()
            const navigated = tx.checkpoint.snap.page !== after.page || tx.checkpoint.snap.section !== after.section
            GcpAgentState.commitGroup()
            _transaction = null
            busy = false
            statusText = ""
            done({ label_zh: tx.label }, tx.source, layoutChanged, navigated)
            return
        }
        const c = tx.steps[tx.index]
        try {
            if (c.kind === "text_scale") {
                beginLayoutStep()
                GcpAgentState.setTextScale(c.value)
                tx.index++
                Qt.callLater(advanceSteps)
            } else if (c.kind === "layout_load" || c.kind === "layout_default") {
                if (c.kind === "layout_load") {
                    const saved = GcpAgentState.namedLayout(c.name)
                    if (!navigateStep(saved.page, saved.section)) throw new Error("layout page denied")
                    beginLayoutStep()
                    GcpAgentState.applyLayout(c.name)
                } else { beginLayoutStep(); GcpAgentState.defaultLayout() }
                tx.index++
                Qt.callLater(advanceSteps)
            } else if (c.kind === "nav") {
                if (!navigateStep(c.page, c.section)) {
                    failSteps(qsTr("無法切換畫面（權限不足或畫面不存在），已還原整組"))
                    return
                }
                tx.index++
                Qt.callLater(advanceSteps)
            } else {
                const mod = Core.MODULES.filter(m => m.id === c.module)[0]
                if (!mod || !navigateStep(mod.page, -1)) {
                    failSteps(qsTr("無法開啟模組畫面，已還原整組"))
                    return
                }
                beginLayoutStep()
                _layoutJob = { c: c, tries: 0, page: mod.page }
                statusText = qsTr("等待版面模組…")
                layoutRetry.restart()
            }
        } catch (e) { failSteps(qsTr("動作失敗，已還原整組")) }
    }

    Timer {
        id: layoutRetry
        interval: 120
        repeat: false
        onTriggered: {
            const job = root._layoutJob
            if (!job || !root._transaction) return
            const c = job.c
            if (root.context().page !== job.page) {
                root.failSteps(qsTr("等待時畫面已改變，已還原整組"))
                return
            }
            const box = GcpAgentState.baseBox(c.module)
            if (!box || box.areaW <= 0 || box.areaH <= 0) {
                if (++job.tries < 20) { restart(); return }
                root.failSteps(qsTr("模組尚未就緒，已還原整組"))
                return
            }
            root._layoutJob = null
            try {
                const arg = c.op === "move" ? c.region : c.op === "nudge" ? c.dir : c.factor
                const next = Core.layoutTarget(c.op, box, { w: box.areaW, h: box.areaH }, GcpAgentState.overrideOf(c.module), arg,
                                                GcpAgentState.otherRects(c.module), Core.MODULES.filter(m => m.id === c.module)[0])
                GcpAgentState.setOverride(c.module, next)
                root._transaction.index++
                root.advanceSteps()
            } catch (e) { root.failSteps(qsTr("版面調整失敗，已還原整組")) }
        }
    }

    function done(c, source, layoutChanged, navigated) {
        pendingText = ""
        messageText = qsTr("已套用：%1（%2）").arg(c.label_zh).arg(source)
        recordChange(messageText)
        open = false
        if (layoutChanged) showToast("layout", "undo")
        else if (navigated) showToast("navigation", "undo")
        else dismissToast()
    }

    Component.onDestruction: {
        if (_cancelModel) _cancelModel()
        if (_transaction) { layoutRetry.stop(); GcpAgentState.rollbackGroup(_transaction.checkpoint) }
    }

    // ------------------------------------------------------------ 提示列（面板關閉時也能一鍵復原）
    function dismissToast() {
        toastTimer.stop()
        toast.opacity = 0
    }

    function showHistoryToast(action, entry, beforeLayout) {
        if ((entry && entry.kind === "layout") || beforeLayout !== GcpAgentState.layoutFingerprint())
            showToast("layout", action)
        else if (action === "undo") showToast("navigation", "undo")
        else dismissToast() // Returning from a navigation does not offer another navigation undo.
    }

    function showToast(mode, action) {
        toastTimer.stop()
        toast.mode = mode
        toast.action = action
        const stack = action === "redo" ? GcpAgentState.redoStack : GcpAgentState.undoStack
        toast.entryKey = stack.length ? JSON.stringify(stack[stack.length - 1]) : ""
        toast.snapshotKey = JSON.stringify(GcpAgentState.snapshot())
        toast.opacity = 1
        if (mode === "navigation") toastTimer.restart()
    }

    function toastActionAvailable() {
        const stack = toast.action === "redo" ? GcpAgentState.redoStack : GcpAgentState.undoStack
        return stack.length > 0 && toast.entryKey === JSON.stringify(stack[stack.length - 1]) &&
               toast.snapshotKey === JSON.stringify(GcpAgentState.snapshot())
    }

    function performToastAction() {
        if (busy || !toastActionAvailable()) return
        execute({ kind: toast.action, steps: 1 }, qsTr("提示列"))
    }
    Timer { id: toastTimer; interval: 7000; onTriggered: toast.opacity = 0 }

    Rectangle {
        id: toast
        objectName: "agentToast"
        property string mode: ""
        property string action: ""
        property string entryKey: ""
        property string snapshotKey: ""
        readonly property bool actionAvailable: GcpAgentState.revision >= 0 && !root.busy && root.toastActionAvailable()
        z: 3
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 120
        width: Math.min(Math.max(0, root.width - 40), toastRow.implicitWidth + 40)
        height: Math.max(64, toastRow.implicitHeight + 20)
        radius: 32
        color: root.cBg
        border.color: root.cLine
        RowLayout {
            id: toastRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            spacing: 20
            Button {
                objectName: "agentToastAction"
                text: toast.mode === "navigation" ? qsTr("返回") : toast.action === "redo" ? qsTr("重做") : qsTr("復原")
                enabled: toast.actionAvailable
                font.pixelSize: (20 * GcpTheme.font.textScale)
                onClicked: root.performToastAction()
            }
            Button {
                objectName: "agentToastSaveLayout"
                visible: toast.mode === "layout"
                text: qsTr("儲存")
                enabled: root.canSaveLayout
                font.pixelSize: (20 * GcpTheme.font.textScale)
                onClicked: root.execute({ kind: "layout_save_current" }, qsTr("使用者儲存"))
            }
        }
        Button {
            objectName: "agentToastClose"
            visible: toast.mode === "layout"
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: -8
            anchors.topMargin: -16
            text: "✕"
            Accessible.name: qsTr("關閉提示列")
            onClicked: root.dismissToast()
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
            font.pixelSize: (26 * GcpTheme.font.textScale); font.bold: true
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
                Text { text: qsTr("介面助理"); color: root.cText; font.pixelSize: (28 * GcpTheme.font.textScale); font.bold: true }
                Item { Layout.fillWidth: true }
                Text {
                    text: "⚙"; color: settingsForm.visible ? root.cAccent : root.cSub; font.pixelSize: (26 * GcpTheme.font.textScale)
                    MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: settingsForm.visible = !settingsForm.visible }
                }
                Item { Layout.preferredWidth: 18 }
                Text {
                    text: "✕"; color: root.cSub; font.pixelSize: (26 * GcpTheme.font.textScale)
                    MouseArea { anchors.fill: parent; anchors.margins: -12; onClicked: root.open = false }
                }
            }
            Text {
                Layout.fillWidth: true
                text: {
                    const page = root.shell ? root.shell.currentPage : -1
                    return qsTr("目前畫面：%1").arg(Core.PAGES.filter(p => p.page === page).map(p => p.name)[0] || "-")
                }
                color: root.cSub; font.pixelSize: (18 * GcpTheme.font.textScale)
            }

            // Bounded settings pane: timeout controls must not push the intent input off-screen.
            ScrollView {
                id: settingsForm
                visible: false
                enabled: !root.busy
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(settingsContent.implicitHeight, Math.max(140, panel.height * 0.32))
                contentWidth: availableWidth
                clip: true
                property string timeoutError: ""
                ColumnLayout {
                    id: settingsContent
                    width: settingsForm.availableWidth
                    spacing: 8
                    Repeater {
                        model: [
                            { key: "backend", label: qsTr("後端（openai／ollama／none）"), value: root.backend },
                            { key: "llmUrl", label: qsTr("模型網址（Ollama：http://Ubuntu位址:11434）"), value: root.modelUrl },
                            { key: "llmModel", label: qsTr("模型名稱（Ollama：qwen2.5:3b）"), value: root.modelName }
                        ]
                        delegate: TextField {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 48
                            font.pixelSize: (18 * GcpTheme.font.textScale)
                            color: root.cText
                            text: modelData.value
                            placeholderText: modelData.label
                            placeholderTextColor: root.cSub
                            background: Rectangle { radius: 8; color: "#33000000"; border.color: root.cLine }
                            onEditingFinished: agentSettings[modelData.key] = text.trim()
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("等待上限（毫秒，1–120000；留空採環境設定）")
                        color: root.cSub; font.pixelSize: (16 * GcpTheme.font.textScale)
                        wrapMode: Text.Wrap
                    }
                    TextField {
                        id: timeoutInput
                        objectName: "agentModelTimeoutInput"
                        Layout.fillWidth: true
                        Layout.preferredHeight: 48
                        text: agentSettings.llmTimeoutMs > 0 ? String(agentSettings.llmTimeoutMs) : ""
                        placeholderText: String(root.modelTimeoutMs)
                        inputMethodHints: Qt.ImhDigitsOnly
                        font.pixelSize: (18 * GcpTheme.font.textScale)
                        color: root.cText
                        placeholderTextColor: root.cSub
                        background: Rectangle { radius: 8; color: "#33000000"; border.color: settingsForm.timeoutError ? root.cWarn : root.cLine }
                        onEditingFinished: {
                            settingsForm.timeoutError = root.setModelTimeout(text) ? "" : qsTr("請填 1–120000 的整數，或留空；原設定保留")
                            if (settingsForm.timeoutError) text = agentSettings.llmTimeoutMs > 0 ? String(agentSettings.llmTimeoutMs) : ""
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: settingsForm.timeoutError || qsTr("目前上限：%1 秒（%2）").arg(root.modelTimeoutMs / 1000).arg(agentSettings.llmTimeoutMs > 0 ? qsTr("面板設定") : qsTr("環境設定／預設"))
                        color: settingsForm.timeoutError ? root.cWarn : root.cSub
                        font.pixelSize: (16 * GcpTheme.font.textScale)
                        wrapMode: Text.Wrap
                    }
                }
            }

            Text {
                objectName: "agentModelNotice"
                Layout.fillWidth: true
                visible: root.modelNotice !== ""
                text: root.modelNotice
                color: root.cWarn; font.pixelSize: (16 * GcpTheme.font.textScale)
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                TextField {
                    id: input
                    objectName: "agentInput"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 56
                    font.pixelSize: (22 * GcpTheme.font.textScale)
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
                    Text { anchors.centerIn: parent; text: qsTr("送出"); color: "#0B1220"; font.pixelSize: (22 * GcpTheme.font.textScale); font.bold: true }
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
                        Text { id: chipText; anchors.centerIn: parent; text: parent.modelData; color: root.cSub; font.pixelSize: (17 * GcpTheme.font.textScale) }
                        MouseArea { anchors.fill: parent; onClicked: root.submit(parent.modelData) }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                visible: text !== ""
                text: root.statusText
                color: root.cWarn; font.pixelSize: (20 * GcpTheme.font.textScale)
            }
            Button {
                objectName: "agentCancelModel"
                visible: root._cancelModel !== null || root.pendingText !== ""
                text: qsTr("取消")
                onClicked: root.cancelWaiting()
            }
            Text {
                objectName: "agentPendingRequest"
                Layout.fillWidth: true
                visible: root.pendingText !== ""
                text: qsTr("接續中：%1").arg(root.pendingText)
                wrapMode: Text.Wrap
                color: root.cWarn; font.pixelSize: (20 * GcpTheme.font.textScale)
            }
            Text {
                objectName: "agentMessage"
                Layout.fillWidth: true
                visible: text !== ""
                text: root.messageText
                wrapMode: Text.Wrap
                color: root.cText; font.pixelSize: (21 * GcpTheme.font.textScale)
            }
            Rectangle {
                objectName: "agentConfirmationCard"
                Layout.fillWidth: true
                Layout.preferredHeight: confirmationContent.implicitHeight + 24
                visible: root._confirmation !== null
                radius: 10
                color: "#1A22D3EE"
                border.color: root.cAccent
                ColumnLayout {
                    id: confirmationContent
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10
                    ScrollView {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(confirmationLabel.implicitHeight, 160)
                        clip: true
                        contentWidth: availableWidth
                        Text {
                            id: confirmationLabel
                            objectName: "agentConfirmationText"
                            width: parent.width
                            text: root.confirmationSummary()
                            wrapMode: Text.Wrap
                            color: root.cText
                            font.pixelSize: (20 * GcpTheme.font.textScale)
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Button {
                            objectName: "agentConfirmYes"
                            text: qsTr("對")
                            enabled: root._confirmation !== null && !root.busy
                            Layout.fillWidth: true
                            onClicked: root.confirmIntent()
                        }
                        Button {
                            objectName: "agentConfirmNo"
                            text: qsTr("不是")
                            enabled: root._confirmation !== null && !root.busy
                            Layout.fillWidth: true
                            onClicked: root.rejectIntent()
                        }
                    }
                }
            }
            ListView {
                id: choicesList
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 180)
                visible: count > 0
                clip: true
                spacing: 8
                ScrollBar.vertical: ScrollBar { }
                model: root.choices
                delegate: Rectangle {
                    required property var modelData
                    width: choicesList.width
                    height: 54
                    radius: 10
                    color: "#1A22D3EE"
                    border.color: root.cAccent
                    Text {
                        anchors.left: parent.left; anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 32; elide: Text.ElideRight
                        text: parent.modelData.label_zh; color: root.cText; font.pixelSize: (20 * GcpTheme.font.textScale)
                    }
                    MouseArea { anchors.fill: parent; onClicked: root.choose(parent.modelData) }
                }
            }

            Item { Layout.fillHeight: true }

            Text {
                objectName: "agentUnsavedLayout"
                Layout.fillWidth: true
                visible: GcpAgentState.hasUnsavedChanges
                text: qsTr("未儲存")
                color: root.cWarn; font.pixelSize: (20 * GcpTheme.font.textScale)
            }
            Button {
                objectName: "agentSaveLayout"
                text: qsTr("儲存版面")
                font.pixelSize: (20 * GcpTheme.font.textScale)
                enabled: root.canSaveLayout
                onClicked: root.execute({ kind: "layout_save_current" }, qsTr("使用者儲存"))
            }
            // 變更紀錄與復原
            Text { text: qsTr("變更紀錄"); color: root.cSub; font.pixelSize: (18 * GcpTheme.font.textScale) }
            ListView {
                id: historyList
                Layout.fillWidth: true
                Layout.preferredHeight: 190
                clip: true
                model: root.changeLog
                delegate: Text {
                    required property var modelData
                    required property int index
                    width: historyList.width
                    text: (index === 0 ? "● " : "○ ") + modelData.label
                    color: index === 0 ? root.cText : root.cSub
                    font.pixelSize: (18 * GcpTheme.font.textScale); elide: Text.ElideRight
                    height: 32
                }
                Text {
                    anchors.centerIn: parent
                    visible: historyList.count === 0
                    text: qsTr("尚無變更"); color: root.cSub; font.pixelSize: (18 * GcpTheme.font.textScale)
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Repeater {
                    model: [
                        { label: qsTr("復原"), kind: "undo", en: GcpAgentState.canUndo },
                        { label: qsTr("重做"), kind: "redo", en: GcpAgentState.canRedo },
                        { label: qsTr("全部復原"), kind: "reset_all", en: GcpAgentState.canUndo || GcpAgentState.textScale !== 1 || Object.keys(GcpAgentState._overrides).length > 0 }
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
                        Text { anchors.centerIn: parent; text: parent.modelData.label; color: root.cAccent; font.pixelSize: (20 * GcpTheme.font.textScale) }
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
                color: root.cSub; font.pixelSize: (15 * GcpTheme.font.textScale); elide: Text.ElideRight
            }
        }
    }
}
