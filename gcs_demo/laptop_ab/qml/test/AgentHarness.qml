import QtQuick
import QtPositioning
import "../Agent/GcpAgentCore.js" as AgentCore
import "../Agent/GcpAgentThemePalette.js" as Palette
import "../Agent/GcpAgentThemeHostPolicy.js" as HostPolicy

// 離屏測試用：假 shell、假 UI agent 狀態（真的 Core／Palette 規則）、假 missionController。
Item {
    id: root
    width: 1600; height: 1000
    property string api: "http://127.0.0.1:1"
    property int page: 1
    property int section: -1
    property bool pageReady: true

    QtObject {
        id: shell
        function agentLocation() { return { page: root.page, section: root.section } }
        function agentGoTo(p, s) { root.page = p; root.section = s === undefined ? -1 : s; return true }
    }

    // UI agent 狀態的最小替身：beginGroup/commitGroup/rollbackGroup/undo 與 GcpAgentState 相同語意
    QtObject {
        id: state
        objectName: "fakeState"
        property real textScale: 1.0
        property var overrides: ({})
        property var undoStack: []
        property var _cp: null
        property var themeGroups: ({})
        property var themePolicy: ({ sourceThemeSha256: HostPolicy.SOURCE_THEME_SHA256, scope: "host-declared-static-pairs",
                                     pairs: HostPolicy.pairs(), minimumHueDistance: 20, relativeAmount: 0.03 })
        property bool themeReady: true
        function snap() { return { textScale: textScale, overrides: JSON.parse(JSON.stringify(overrides)), theme: JSON.parse(JSON.stringify(themeGroups)), page: root.page } }
        function restore(s) { textScale = s.textScale; overrides = s.overrides; themeGroups = s.theme; root.page = s.page }
        function beginGroup() { if (_cp) throw new Error("nested change group"); _cp = { snap: snap(), undo: undoStack.slice() }; return _cp }
        function commitGroup(cp, label, kind) { if (cp !== _cp) throw new Error("bad commit"); undoStack = cp.undo.concat([{ label: label, kind: kind, snap: cp.snap }]); _cp = null }
        function rollbackGroup(cp) { if (cp !== _cp) throw new Error("bad rollback"); restore(cp.snap); undoStack = cp.undo; _cp = null }
        function undo(n) { const e = undoStack[undoStack.length - 1]; undoStack = undoStack.slice(0, -1); restore(e.snap); return [e.label] }
        function setTextScale(v) { if (AgentCore.TEXT_SCALES.indexOf(v) < 0) throw new Error("invalid text scale"); textScale = v }
        function moduleInfo() { const o = {}; for (const m of AgentCore.MODULES) o[m.id] = { registered: true, visible: true }; return o }
        function baseBox(id) { return root.page === 1 && root.pageReady ? { x: 100, y: 100, w: 200, h: 120, areaW: 1600, areaH: 1000 } : null }
        function overrideOf(id) { return overrides[id] || { dx: 0, dy: 0, scale: 1, hidden: false } }
        function otherRects(id) { return [] }
        function setOverride(id, ov) { const c = Object.assign({}, overrides); c[id] = ov; overrides = c }
        function resetTheme(confirmed) { if (!Object.keys(themeGroups).length) return false; const cp = beginGroup(); themeGroups = ({}); commitGroup(cp, "復原預設色彩", "theme"); return true }
        function previewThemeHighContrast() { return { kind: "high_contrast", groups: { background: "#000000", text: "#FFFFFF", accent: "#00FFFF" } } }
        function applyThemeHighContrast(p, confirmed) { if (confirmed !== true) throw new Error("confirm"); const cp = beginGroup(); themeGroups = p.groups; commitGroup(cp, "高對比色彩", "theme") }
        function _writeThemeGroups(g) { if (!Palette.verify(g, themePolicy).pass) throw new Error("contrast"); themeGroups = g }
    }

    // 假 missionController：只有 visualItems／removeVisualItem／insertSimpleMissionItem
    Component { id: wpComp; QtObject { property bool isSimpleItem: true; property bool specifiesCoordinate: true; property int command: 16
                                        property var coordinate; property QtObject altitude: QtObject { property real rawValue: 50 } } }
    QtObject {
        id: mc
        property var list: []
        property QtObject visualItems: QtObject {
            property int count: mc.list.length
            function get(i) { return mc.list[i] }
            function indexOf(x) { return mc.list.indexOf(x) }
        }
        function removeVisualItem(i) { const l = list.slice(); l.splice(i, 1); list = l }
        function insertSimpleMissionItem(coord, i, b) { const l = list.slice(); l.splice(i, 0, wpComp.createObject(mc, { coordinate: coord })); list = l }
    }
    function coords() { return mc.list.map(it => [it.coordinate.latitude, it.coordinate.longitude, it.altitude.rawValue]) }
    function seed(n) { for (let i = 0; i < n; i++) mc.insertSimpleMissionItem(QtPositioning.coordinate(25 + i, 121), i, false) }

    Loader { id: sinkLoader; active: root.page === 2; source: "../AiAgent/GcpAiAgentRouteSink.qml"; onLoaded: item.missionController = mc }

    Loader {
        id: panelLoader
        anchors.fill: parent
        source: "../AiAgent/GcpAiAgentPanel.qml"
        onLoaded: { item.shell = shell; item.agentState = state; item.apiBase = Qt.binding(function () { return root.api }) }
    }
    property alias panel: panelLoader.item
    function st() { return state }
}
