pragma Singleton
import QtQuick
import QtQml
import QtCore
import "GcpAgentCore.js" as Core
import "GcpAgentThemePalette.js" as ThemePalette
import "GcpAgentThemeHostPolicy.js" as ThemeHostPolicy
import "GcpAgentSnapshot.js" as AgentSnapshot
import "GcpAgentHost.js" as AgentHost
import QGroundControl.GCP

// UI agent 的共用狀態：可調整模組的登記、版面覆寫值、復原／重做堆疊。
// 每次 agent 套用變更前先存一份快照（目前畫面＋子頁＋全部版面覆寫），復原就是把快照放回去。
QtObject {
    id: root

    // Trusted host configuration only. No model may supply policy or token maps.
    property var themePolicy: null
    property var _themeGroups: ({})
    readonly property var themeGroups: ThemePalette.checkedGroups(_themeGroups)
    property bool _themeLoadPending: false
    property var _pendingThemeLayout: null
    readonly property bool themeReady: themePolicy !== null && !_themeLoadPending

    function _requireThemeLayoutReady() {
        if (_themeLoadPending) throw new Error("saved theme awaits trusted host policy; original retained")
    }
    function _checkedTheme(groups, policy) {
        const clean = ThemePalette.checkedGroups(groups === undefined ? {} : groups)
        if (Object.keys(clean).length && (!policy || !ThemePalette.verify(clean, policy).pass))
            throw new Error("theme policy or contrast unavailable")
        return clean
    }
    function _writeThemeGroups(groups) {
        const clean = _checkedTheme(groups, themePolicy)
        // Theme never imports State; avoid a singleton construction cycle.
        GcpTheme.color.setAgentThemeGroups(clean)
        _themeGroups = clean
        revision++
    }
    // User-selected initial values (0392); host may explicitly adjust later.
    // Pair evidence and source identity are still required: defaults never enable alone.
    function configureHostThemePolicy(sourceThemeSha256, pairs, values) {
        const selected = values === undefined ? {} : values
        if (!selected || typeof selected !== "object" || Array.isArray(selected))
            throw new Error("host policy values object required")
        for (const key of Object.keys(selected))
            if (key !== "minimumHueDistance" && key !== "relativeAmount")
                throw new Error("unknown host policy value")
        configureThemePolicy({
            sourceThemeSha256: sourceThemeSha256,
            scope: "host-declared-static-pairs",
            pairs: pairs,
            minimumHueDistance: Object.prototype.hasOwnProperty.call(selected, "minimumHueDistance") ? selected.minimumHueDistance : 20,
            relativeAmount: Object.prototype.hasOwnProperty.call(selected, "relativeAmount") ? selected.relativeAmount : 0.03
        })
    }
    function configureThemePolicy(policy) {
        if (_groupActive) throw new Error("cannot replace theme policy during a transaction")
        ThemePalette.policyKey(policy)
        const cleanPolicy = JSON.parse(JSON.stringify(policy))
        _checkedTheme(_themeGroups, cleanPolicy)
        for (const entry of undoStack.concat(redoStack)) _checkedTheme(entry.snap.themeGroups, cleanPolicy)
        if (_pendingThemeLayout) _checkedTheme(_pendingThemeLayout.themeGroups, cleanPolicy)
        const oldPolicy = themePolicy
        const beforeResume = snapshot()
        themePolicy = cleanPolicy
        try {
            if (_pendingThemeLayout) {
                _restore(_pendingThemeLayout, true)
                _pendingThemeLayout = null
                _themeLoadPending = false
                _savedFingerprint = layoutFingerprint()
            }
        } catch (e) {
            themePolicy = oldPolicy
            _restore(beforeResume, true)
            throw e
        }
        revision++
    }
    function previewThemeAction(action) {
        _requireThemeLayoutReady()
        return ThemePalette.preview(_themeGroups, action, themePolicy)
    }
    function previewThemeInput(group, input) {
        _requireThemeLayoutReady()
        return ThemePalette.fromInput(_themeGroups, group, input, themePolicy)
    }
    function applyThemeProposal(proposal, confirmed) {
        _requireThemeLayoutReady()
        const groups = ThemePalette.validatedCommit(_themeGroups, proposal, themePolicy, confirmed)
        const checkpoint = beginGroup()
        try {
            _writeThemeGroups(groups)
            commitGroup(checkpoint, qsTr("調整主題色彩"), "theme")
        } catch (e) { rollbackGroup(checkpoint); throw e }
    }
    // Fixed app shortcut; model output cannot choose actions or policy for this bundle.
    function previewThemeHighContrast() {
        _requireThemeLayoutReady()
        let groups = ThemePalette.checkedGroups(_themeGroups)
        const actions = [{group:"background",color:"#000000"}, {group:"text",color:"#FFFFFF"}, {group:"accent",color:"#00FFFF"}]
        const rows = []
        for (const action of actions) {
            const value = ThemePalette.preview(groups, action, themePolicy)
            if (value.kind !== "confirm") throw new Error("high contrast shortcut unavailable")
            rows.push({group: action.group, requested: value.requested, actual: value.actual})
            groups = value.groups
        }
        const verified = ThemePalette.verify(groups, themePolicy)
        if (!verified.pass) throw new Error("high contrast final recheck failed")
        return {kind:"high_contrast", basis:ThemePalette.fingerprint(_themeGroups),
            policyKey:ThemePalette.policyKey(themePolicy), groups:groups, rows:rows}
    }
    function applyThemeHighContrast(proposal, confirmed) {
        _requireThemeLayoutReady()
        if (confirmed !== true || !proposal || proposal.kind !== "high_contrast") throw new Error("explicit confirmation required")
        const again = previewThemeHighContrast()
        if (proposal.basis !== again.basis || proposal.policyKey !== again.policyKey ||
            ThemePalette.fingerprint(proposal.groups) !== ThemePalette.fingerprint(again.groups) ||
            JSON.stringify(proposal.rows) !== JSON.stringify(again.rows)) throw new Error("stale or altered high contrast proposal")
        const checkpoint = beginGroup()
        try {
            _writeThemeGroups(again.groups)
            commitGroup(checkpoint, qsTr("高對比色彩"), "theme")
        } catch (e) { rollbackGroup(checkpoint); throw e }
    }
    function resetTheme(confirmed) {
        _requireThemeLayoutReady()
        if (confirmed !== true) throw new Error("explicit theme reset confirmation required")
        if (!Object.keys(_themeGroups).length) return false
        const checkpoint = beginGroup()
        try {
            _writeThemeGroups({})
            commitGroup(checkpoint, qsTr("復原預設色彩"), "theme")
        } catch (e) { rollbackGroup(checkpoint); throw e }
        return true
    }

    // 由 GcpMainShell 提供：agentLocation() → {page, section}；agentGoTo(page, section) → bool
    property var shell: null
    readonly property real textScale: GcpTheme.font.textScale
    function setTextScale(value) {
        _requireThemeLayoutReady()
        if (Core.TEXT_SCALES.indexOf(value) < 0) throw new Error("invalid text scale")
        GcpTheme.font.textScale = value
        revision++
    }
    property QtObject _layoutSettings: Settings {
        category: "GCP/AgentLayouts"
        property string layoutsJson: "{}"
        property string savedLayoutJson: ""
    }

    property bool _savedLoaded: false
    property bool _savedCorrupt: false
    property string _savedFingerprint: '{"overrides":{},"textScale":1,"themeGroups":{}}'
    readonly property bool hasUnsavedChanges: revision >= 0 && !_themeLoadPending && layoutFingerprint() !== _savedFingerprint
    function layoutFingerprint() {
        const ordered = {}
        for (const id of Object.keys(_overrides).sort()) {
            const o = _overrides[id]
            ordered[id] = { rx: o.rx, ry: o.ry, scale: o.scale, hidden: o.hidden }
        }
        return JSON.stringify({ overrides: ordered, textScale: textScale, themeGroups: ThemePalette.checkedGroups(_themeGroups) })
    }
    Component.onCompleted: {
        // Installed host policy only. Model values cannot supply pairs or thresholds.
        try { configureHostThemePolicy(ThemeHostPolicy.SOURCE_THEME_SHA256, ThemeHostPolicy.pairs()) }
        catch (e) { console.warn("Theme host policy unavailable: " + e.message) }
        loadSavedLayout()
    }
    function loadSavedLayout() {
        if (_savedLoaded) return
        _savedLoaded = true
        if (!_layoutSettings.savedLayoutJson) { _savedFingerprint = layoutFingerprint(); return }
        try {
            const saved = checkedLayout(JSON.parse(_layoutSettings.savedLayoutJson))
            if (Object.keys(saved.themeGroups).length && (!themePolicy || !ThemePalette.verify(saved.themeGroups, themePolicy).pass)) {
                _pendingThemeLayout = saved
                _themeLoadPending = true
                _savedFingerprint = layoutFingerprint()
                revision++
                return // Retain raw settings and defer, never label missing policy as corruption.
            }
            _writeThemeGroups(saved.themeGroups)
            // Restore layout only; opening a saved flight screen is not a startup side effect.
            _overrides = saved.overrides
            GcpTheme.font.textScale = saved.textScale
            for (const id in _modules) _apply(id)
            revision++
        } catch (e) {
            _savedCorrupt = true
            _overrides = {}
            GcpTheme.font.textScale = 1
            console.warn("[GcpAgent] Invalid GCP/AgentLayouts/savedLayoutJson; using defaults; original retained; save blocked pending recovery: " + e)
        }
        _savedFingerprint = layoutFingerprint()
    }
    function saveCurrentLayout() {
        loadSavedLayout()
        _requireThemeLayoutReady()
        if (_groupActive) throw new Error("change group still active")
        if (_savedCorrupt) throw new Error("saved layout is corrupt; original retained; recovery required")
        const snap = snapshot()
        if (snap.page < 0) { snap.page = 0; snap.section = -1 }
        _layoutSettings.savedLayoutJson = JSON.stringify(checkedLayout(snap))
        _layoutSettings.sync()
        _savedFingerprint = layoutFingerprint()
        revision++
    }

    function _layoutStore() {
        const value = JSON.parse(_layoutSettings.layoutsJson)
        if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("invalid layout store")
        return value
    }

    function layoutNames() {
        try { return Object.keys(_layoutStore()).filter(name => Core.validLayoutName(name)) }
        catch (e) { return [] } // Preserve corrupt storage for inspection; never silently overwrite it.
    }

    function checkedLayout(snap) {
        if (!snap || snap.layoutVersion !== 2 || !Number.isInteger(snap.page) || snap.page < 0 || snap.page > 13 ||
            !Number.isInteger(snap.section) || snap.section < -1 || snap.section > 14 ||
            !snap.overrides || typeof snap.overrides !== "object" || Array.isArray(snap.overrides)) throw new Error("invalid layout")
        const clean = {}
        for (const id of Object.keys(snap.overrides)) {
            const p = Core.MODULES.filter(m => m.id === id)[0], o = snap.overrides[id]
            if (!p || !o || typeof o.rx !== "number" || typeof o.ry !== "number" ||
                !isFinite(o.rx) || !isFinite(o.ry) || Math.abs(o.rx) > 4 || Math.abs(o.ry) > 4 ||
                p.scales.indexOf(o.scale) < 0 || typeof o.hidden !== "boolean" || (p.locked && o.hidden)) throw new Error("invalid module override")
            clean[id] = { rx: o.rx, ry: o.ry, scale: o.scale, hidden: o.hidden }
        }
        const scale = snap.textScale === undefined ? 1 : snap.textScale
        if (Core.TEXT_SCALES.indexOf(scale) < 0) throw new Error("invalid text scale")
        return { layoutVersion: 2, page: snap.page, section: snap.section, overrides: clean, textScale: scale,
                 themeGroups: ThemePalette.checkedGroups(snap.themeGroups === undefined ? {} : snap.themeGroups) }
    }

    function saveLayout(name) {
        if (!Core.validLayoutName(name)) throw new Error("invalid name")
        const store = _layoutStore()
        store[name] = checkedLayout(snapshot())
        saveCurrentLayout()
        _layoutSettings.layoutsJson = JSON.stringify(store)
        _layoutSettings.sync()
    }

    function namedLayout(name) {
        const store = _layoutStore()
        if (!Object.prototype.hasOwnProperty.call(store, name)) throw new Error("unknown layout")
        return checkedLayout(store[name])
    }
    function applyLayout(name) {
        _requireThemeLayoutReady()
        const snap = namedLayout(name)
        _checkedTheme(snap.themeGroups, themePolicy)
        if (!shell || !shell.agentGoTo(snap.page, snap.section)) throw new Error("layout page denied")
        _restore(snap, true)
    }

    function defaultLayout() {
        _requireThemeLayoutReady()
        const snap = snapshot()
        snap.overrides = {}
        snap.textScale = 1
        snap.themeGroups = {}
        _restore(snap)
    }

    property int revision: 0                 // 任何覆寫或堆疊變動都 +1，給 QML 綁定重算
    property var _modules: ({})              // id → { item, container }
    property var _overrides: ({})            // id → { rx, ry, scale, hidden } (container fractions)
    property var _cancelRedo: []             // 失敗交易不得丟失原本的重做堆疊
    property var undoStack: []               // [{ label, snap }]
    property var redoStack: []
    readonly property bool canUndo: revision >= 0 && undoStack.length > 0
    readonly property bool canRedo: revision >= 0 && redoStack.length > 0

    property Component _scaleComponent: Component { Scale { origin.x: 0; origin.y: 0 } }
    property Component _translateComponent: Component { Translate {} }
    // Binding 停用時恢復原本的 binding/value，避免隱藏破壞遙測綁定。
    property Component _opacityComponent: Component { Binding { property: "opacity"; value: 0; when: false } }
    property Component _enabledComponent: Component { Binding { property: "enabled"; value: false; when: false } }

    // ------------------------------------------------------------ 模組登記
    function register(id, item, container) {
        if (!id || !item) return
        loadSavedLayout()
        if (_modules[id]) unregister(id, _modules[id].item)
        _modules[id] = { item: item, container: container || item.parent,
                         scale: null, translate: null, opacityBinding: null, enabledBinding: null }
        _apply(id)
        revision++
    }

    function unregister(id, item) {
        if (_modules[id] && _modules[id].item === item) {
            const m = _modules[id]
            // 先停用 Binding，再銷毀；target 改指向時不把舊物件留在隱藏狀態。
            if (m.opacityBinding) { m.opacityBinding.when = false; m.opacityBinding.destroy() }
            if (m.enabledBinding) { m.enabledBinding.when = false; m.enabledBinding.destroy() }
            if (m.item) {
                const list = []
                for (let i = 0; i < m.item.transform.length; ++i) {
                    const t = m.item.transform[i]
                    if (t !== m.scale && t !== m.translate) list.push(t)
                }
                m.item.transform = list
            }
            if (m.scale) m.scale.destroy()
            if (m.translate) m.translate.destroy()
            delete _modules[id]
            revision++
        }
    }

    function moduleInfo() {
        const out = {}
        for (const id in _modules) {
            const m = _modules[id]
            out[id] = { registered: true, visible: !!(m.item && m.item.visible && !overrideOf(id).hidden) }
        }
        return out
    }

    // Read only. Host supplies the common viewport after Qt has settled its layout.
    function verificationSnapshot(viewport) {
        const loc = shell && shell.agentLocation ? shell.agentLocation() : { page: -1, section: -1 }
        return AgentSnapshot.capture(viewport, _modules, Core.MODULES, loc, overrideOf)
    }

    // Read only; goal minimums and permissions must come from host policy shown on the card.
    // Overlay wiring is a separate increment. No default minimum or repair permission.
    function readableHostInput(viewport, goal, candidates) {
        const before = revision
        const loc = shell && shell.agentLocation ? shell.agentLocation() : { page: -1, section: -1 }
        const input = AgentHost.captureReadable(viewport, _modules, Core.MODULES, loc, overrideOf,
                                                before, goal, candidates, AgentSnapshot)
        const after = shell && shell.agentLocation ? shell.agentLocation() : { page: -1, section: -1 }
        if (revision !== before || loc.page !== after.page || loc.section !== after.section)
            throw new Error("host changed during readability capture")
        return input
    }

    // 模組在容器座標中的原始位置（不含 agent 變換）
    function baseBox(id) {
        const m = _modules[id]
        if (!m || !m.item || !m.container || !m.item.parent) return null
        const p = m.item.parent.mapToItem(m.container, m.item.x, m.item.y)
        return { x: p.x, y: p.y, w: m.item.width, h: m.item.height,
                 areaW: m.container.width, areaH: m.container.height }
    }

    // 其他可見模組目前（含 agent 變換）的矩形，給移動時避開重疊
    function otherRects(exceptId) {
        const out = []
        if (!_modules[exceptId]) return out
        for (const id in _modules) {
            if (id === exceptId || _modules[id].container !== _modules[exceptId].container) continue
            const m = _modules[id]
            const b = baseBox(id)
            const o = overrideOf(id)
            if (!b || !m.item.visible || o.hidden) continue
            out.push({ x: b.x + o.dx, y: b.y + o.dy, w: b.w * o.scale, h: b.h * o.scale })
        }
        return out
    }

    function overrideOf(id) {
        const o = _overrides[id], b = baseBox(id)
        if (!o) return { dx: 0, dy: 0, scale: 1, hidden: false }
        const dx = b ? o.rx * b.areaW : 0, dy = b ? o.ry * b.areaH : 0
        return { dx: b ? Math.max(-b.x, Math.min(b.areaW - Math.min(b.w * o.scale, b.areaW) - b.x, dx)) : dx,
                 dy: b ? Math.max(-b.y, Math.min(b.areaH - Math.min(b.h * o.scale, b.areaH) - b.y, dy)) : dy,
                 scale: o.scale, hidden: o.hidden }
    }

    function setOverride(id, ov) {
        _requireThemeLayoutReady()
        const policy = Core.MODULES.filter(m => m.id === id)[0]
        const b = baseBox(id)
        if (!policy || (policy.locked && ov.hidden)) throw new Error("invalid or locked module")
        if (!b || b.areaW <= 0 || b.areaH <= 0 || !isFinite(ov.dx) || !isFinite(ov.dy) || !isFinite(ov.scale))
            throw new Error("invalid module dimensions")
        ov = Object.assign({}, ov, { scale: Core.nearestScale(ov.scale, policy) })
        const copy = Object.assign({}, _overrides)
        if (ov.dx === 0 && ov.dy === 0 && ov.scale === 1 && !ov.hidden) delete copy[id]
        else copy[id] = { rx: ov.dx / b.areaW, ry: ov.dy / b.areaH, scale: ov.scale, hidden: !!ov.hidden }
        _overrides = copy
        _apply(id)
        revision++
    }

    function reflow(id) {
        if (!_modules[id]) return
        _apply(id)
        revision++
    }

    function _apply(id) {
        const m = _modules[id]
        if (!m || !m.item) return
        const o = overrideOf(id)
        const identity = o.dx === 0 && o.dy === 0 && o.scale === 1
        if (!m.scale && !identity) {
            // 第一次調整時才掛上變換，並保留模組原有的變換（例如進場動畫）
            m.scale = _scaleComponent.createObject(m.item)
            m.translate = _translateComponent.createObject(m.item)
            const list = []
            for (let i = 0; i < m.item.transform.length; ++i) list.push(m.item.transform[i])
            list.push(m.scale)
            list.push(m.translate)
            m.item.transform = list
        }
        if (m.scale) {
            m.scale.xScale = o.scale
            m.scale.yScale = o.scale
            m.translate.x = o.dx
            m.translate.y = o.dy
        }
        if (o.hidden && !m.opacityBinding) {
            m.opacityBinding = _opacityComponent.createObject(m.item, { target: m.item })
            m.enabledBinding = _enabledComponent.createObject(m.item, { target: m.item })
        }
        if (m.opacityBinding) m.opacityBinding.when = o.hidden
        if (m.enabledBinding) m.enabledBinding.when = o.hidden
    }

    // ------------------------------------------------------------ 快照與復原
    function snapshot() {
        const loc = shell && shell.agentLocation ? shell.agentLocation() : { page: -1, section: -1 }
        return { layoutVersion: 2, page: loc.page, section: loc.section, overrides: JSON.parse(JSON.stringify(_overrides)), textScale: textScale,
                 themeGroups: ThemePalette.checkedGroups(_themeGroups) }
    }

    function _restore(snap, skipNavigation) {
        _writeThemeGroups(snap.themeGroups === undefined ? {} : snap.themeGroups)
        const ids = {}
        for (const id in _overrides) ids[id] = true
        for (const id in snap.overrides) ids[id] = true
        _overrides = JSON.parse(JSON.stringify(snap.overrides))
        GcpTheme.font.textScale = snap.textScale === undefined ? 1 : snap.textScale
        for (const id in ids) _apply(id)
        if (!skipNavigation && shell && shell.agentGoTo && snap.page >= 0) shell.agentGoTo(snap.page, snap.section)
        revision++
    }

    // 套用一個變更前呼叫：記下目前狀態，並清掉重做堆疊
    function beginChange(label, kind) {
        _requireThemeLayoutReady()
        _cancelRedo = redoStack.slice()
        undoStack = undoStack.concat([{ label: label, kind: kind || "layout", snap: snapshot() }])
        redoStack = []
        revision++
    }

    property bool _groupActive: false
    property var _activeGroupCheckpoint: null
    function beginGroup() {
        _requireThemeLayoutReady()
        if (_groupActive) throw new Error("nested change group")
        const checkpoint = { snap: snapshot(), undo: undoStack.slice(), redo: redoStack.slice() }
        _activeGroupCheckpoint = checkpoint
        _groupActive = true
        return checkpoint
    }
    function commitGroup(checkpoint, label, kind) {
        // No-argument legacy calls keep their existing per-action undo behavior.
        // The bounded loop passes the original token and creates exactly one entry.
        if (checkpoint !== undefined) {
            if (!_groupActive || checkpoint !== _activeGroupCheckpoint || !label)
                throw new Error("invalid atomic group commit")
            undoStack = checkpoint.undo.concat([{label: String(label), kind: kind || "layout", snap: checkpoint.snap}])
            redoStack = []
            revision++
        }
        _groupActive = false
        _activeGroupCheckpoint = null
    }
    function rollbackGroup(checkpoint) {
        if (!_groupActive || !checkpoint || checkpoint !== _activeGroupCheckpoint)
            throw new Error("invalid group rollback")
        _restore(checkpoint.snap)
        undoStack = checkpoint.undo.slice()
        redoStack = checkpoint.redo.slice()
        _groupActive = false
        _activeGroupCheckpoint = null
        revision++
    }
    function undoHint() {
        const next = undoStack.length ? undoStack[undoStack.length - 1] : null
        return next && next.kind === "navigation" ? qsTr("（再按一次復原回%1）").arg(Core.pageName(next.snap.page)) : ""
    }

    // 套用失敗時撤回剛剛的 beginChange（狀態沒有變，不留下空的復原步驟）
    function cancelChange() {
        if (!undoStack.length) return
        const entry = undoStack[undoStack.length - 1]
        undoStack = undoStack.slice(0, -1)
        _restore(entry.snap)
        redoStack = _cancelRedo.slice()
        revision++
    }

    function undo(steps) {
        _requireThemeLayoutReady()
        let n = Math.max(1, steps || 1)
        const labels = []
        while (n-- > 0 && undoStack.length) {
            const entry = undoStack[undoStack.length - 1]
            undoStack = undoStack.slice(0, -1)
            redoStack = redoStack.concat([{ label: entry.label, kind: entry.kind, snap: snapshot() }])
            _restore(entry.snap)
            labels.push(entry.label)
        }
        revision++
        return labels
    }

    function redo() {
        _requireThemeLayoutReady()
        if (!redoStack.length) return ""
        const entry = redoStack[redoStack.length - 1]
        redoStack = redoStack.slice(0, -1)
        undoStack = undoStack.concat([{ label: entry.label, kind: entry.kind, snap: snapshot() }])
        _restore(entry.snap)
        revision++
        return entry.label
    }

    // 回到 agent 第一次介入前；這個動作本身也能再復原
    function resetAll() {
        _requireThemeLayoutReady()
        if (!undoStack.length && Object.keys(_overrides).length === 0 && textScale === 1 && !Object.keys(_themeGroups).length) return false
        const first = undoStack.length ? JSON.parse(JSON.stringify(undoStack[0].snap)) : { page: -1, section: -1, overrides: {}, textScale: 1 }
        first.themeGroups = {}
        beginChange(qsTr("全部復原"))
        _restore(first)
        return true
    }
}
