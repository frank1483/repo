pragma Singleton
import QtQuick
import QtQml

// UI agent 的共用狀態：可調整模組的登記、版面覆寫值、復原／重做堆疊。
// 每次 agent 套用變更前先存一份快照（目前畫面＋子頁＋全部版面覆寫），復原就是把快照放回去。
QtObject {
    id: root

    // 由 GcpMainShell 提供：agentLocation() → {page, section}；agentGoTo(page, section) → bool
    property var shell: null

    property int revision: 0                 // 任何覆寫或堆疊變動都 +1，給 QML 綁定重算
    property var _modules: ({})              // id → { item, container }
    property var _overrides: ({})            // id → { dx, dy, scale, hidden }
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
        const o = _overrides[id]
        return o ? { dx: o.dx, dy: o.dy, scale: o.scale, hidden: o.hidden } : { dx: 0, dy: 0, scale: 1, hidden: false }
    }

    function setOverride(id, ov) {
        const copy = Object.assign({}, _overrides)
        if (ov.dx === 0 && ov.dy === 0 && ov.scale === 1 && !ov.hidden) delete copy[id]
        else copy[id] = { dx: ov.dx, dy: ov.dy, scale: ov.scale, hidden: !!ov.hidden }
        _overrides = copy
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
        return { page: loc.page, section: loc.section, overrides: JSON.parse(JSON.stringify(_overrides)) }
    }

    function _restore(snap) {
        const ids = {}
        for (const id in _overrides) ids[id] = true
        for (const id in snap.overrides) ids[id] = true
        _overrides = JSON.parse(JSON.stringify(snap.overrides))
        for (const id in ids) _apply(id)
        if (shell && shell.agentGoTo && snap.page >= 0) shell.agentGoTo(snap.page, snap.section)
        revision++
    }

    // 套用一個變更前呼叫：記下目前狀態，並清掉重做堆疊
    function beginChange(label) {
        _cancelRedo = redoStack.slice()
        undoStack = undoStack.concat([{ label: label, snap: snapshot() }])
        redoStack = []
        revision++
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
        let n = Math.max(1, steps || 1)
        const labels = []
        while (n-- > 0 && undoStack.length) {
            const entry = undoStack[undoStack.length - 1]
            undoStack = undoStack.slice(0, -1)
            redoStack = redoStack.concat([{ label: entry.label, snap: snapshot() }])
            _restore(entry.snap)
            labels.push(entry.label)
        }
        revision++
        return labels
    }

    function redo() {
        if (!redoStack.length) return ""
        const entry = redoStack[redoStack.length - 1]
        redoStack = redoStack.slice(0, -1)
        undoStack = undoStack.concat([{ label: entry.label, snap: snapshot() }])
        _restore(entry.snap)
        revision++
        return entry.label
    }

    // 回到 agent 第一次介入前；這個動作本身也能再復原
    function resetAll() {
        if (!undoStack.length && Object.keys(_overrides).length === 0) return false
        const first = undoStack.length ? undoStack[0].snap : { page: -1, section: -1, overrides: {} }
        beginChange(qsTr("全部復原"))
        _restore(first)
        return true
    }
}
