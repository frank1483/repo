import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QGroundControl.GCP
import "GcpAgentThemePalette.js" as ThemePalette

ColumnLayout {
    id: root
    spacing: 8
    // Binding tracks shell page and loaded page section properties read by agentLocation().
    property var shell: null
    readonly property var shellLocation: shell && shell.agentLocation ? shell.agentLocation() : null
    readonly property real editorFontSize: 18 * GcpTheme.font.textScale
    property var highContrastProposal: null
    property bool resetPending: false
    property var proposal: null
    property string message: ""
    property var _request: null
    property int _serial: 0
    readonly property string group: ["accent", "background", "text"][groupBox.currentIndex]
    readonly property string pickedColor: "#" + channelHex(red.value) + channelHex(green.value) + channelHex(blue.value)
    readonly property var tokenRows: proposal && proposal.kind === "confirm" ? actualTokens(proposal) : []
    signal modelColorRequested(var request)
    signal modelColorCancelled()

    function locationSnapshot() {
        const loc = shellLocation
        if (!loc || typeof loc.page !== "number" || typeof loc.section !== "number" ||
            !isFinite(loc.page) || !isFinite(loc.section)) return null
        return {page: loc.page, section: loc.section}
    }
    function sameLocation(saved) {
        const now = locationSnapshot()
        return saved !== null && now !== null && saved.page === now.page && saved.section === now.section
    }
    function channelHex(value) { return ("0" + Math.round(value).toString(16)).slice(-2).toUpperCase() }
    function cancel() { _serial++; _request = null; proposal = null; highContrastProposal = null; resetPending = false; message = ""; modelColorCancelled() }
    function previewInput(text) {
        cancel()
        try {
            proposal = GcpAgentState.previewThemeInput(group, text)
            message = proposal.kind === "clarify" ? qsTr("請提供明確色碼，或請模型提議色值後再確認。") :
                proposal.kind === "confirm" ? "" : qsTr("找不到符合檢查的顏色，保留目前色彩。")
        } catch (e) { proposal = null; message = qsTr("無法預覽：%1").arg(e.message) }
    }
    function previewPicker() { previewInput(pickedColor) }
    function requestModelColor() {
        if (!GcpAgentState.themeReady || !proposal || proposal.kind !== "clarify") return false
        const location = locationSnapshot()
        if (!location) { cancel(); message = qsTr("無法確認目前畫面，請改用取色器。"); return false }
        const text = proposal.text
        cancel()
        const id = String(Date.now()) + ":" + String(_serial)
        _request = {id: id, group: group, text: text, revision: GcpAgentState.revision,
                    policyKey: ThemePalette.policyKey(GcpAgentState.themePolicy), location: location}
        message = qsTr("等待色值提議；可改用取色器，或取消。")
        modelColorRequested({id: id, group: group, text: text})
        return true
    }
    function receiveModelValue(action, requestId) {
        const request = _request
        if (!request || request.id !== requestId) return false
        _request = null // correlated reply is consumed even when malformed
        proposal = null
        try {
            if (!visible || !enabled || !sameLocation(request.location) || request.revision !== GcpAgentState.revision || request.group !== group ||
                request.policyKey !== ThemePalette.policyKey(GcpAgentState.themePolicy))
                throw new Error(qsTr("畫面或色彩設定已改變，請重新預覽"))
            const clean = ThemePalette.checkedAction(action)
            if (clean.group !== request.group) throw new Error(qsTr("提議的色彩群組不符"))
            proposal = GcpAgentState.previewThemeAction(clean)
            message = proposal.kind === "confirm" ? qsTr("模型只提議色值，請確認實際套用色。") :
                qsTr("提議無法通過檢查，保留目前色彩。")
            return proposal.kind === "confirm"
        } catch (e) { message = qsTr("未採用提議：%1").arg(e.message); return false }
    }
    function receiveModelError(requestId, reason) {
        if (!_request || _request.id !== requestId) return false
        _request = null; proposal = null
        message = reason
        return true
    }
    function previewHighContrast() {
        cancel()
        try { highContrastProposal = GcpAgentState.previewThemeHighContrast() }
        catch (e) { message = qsTr("高對比色彩目前無法通過檢查，保留目前設定。") }
    }
    function applyHighContrast() {
        try { GcpAgentState.applyThemeHighContrast(highContrastProposal, true); cancel(); return true }
        catch (e) { cancel(); message = qsTr("未套用高對比色彩，請重新預覽。"); return false }
    }
    function applyReset() {
        if (!resetPending) return false
        try { GcpAgentState.resetTheme(true); cancel(); return true }
        catch (e) { cancel(); message = qsTr("無法復原色彩，請稍後重試。"); return false }
    }
    function actualTokens(value) {
        const palette = ThemePalette.materialize(value.groups), rows = []
        for (const name of Object.keys(palette)) {
            if (ThemePalette.tokenGroup(name) !== value.action.group) continue
            const color = palette[name]
            rows.push({name: name, r: color.r, g: color.g, b: color.b, a: color.a})
        }
        return rows
    }
    function contrastSummary(value) {
        if (!value || value.kind !== "confirm") return ""
        const rows = value.contrast.rows
        let worst = rows[0]
        for (const row of rows) if (row.ratio / row.minimum < worst.ratio / worst.minimum) worst = row
        return qsTr("%1 組靜態配對通過；最低餘裕配對 %2：%3 / %4")
            .arg(rows.length).arg(worst.id).arg(worst.ratio.toFixed(3)).arg(worst.minimum)
    }
    function applyConfirmed() {
        const pending = proposal
        try {
            GcpAgentState.applyThemeProposal(pending, true)
            cancel()
            message = qsTr("已套用色彩；可使用助理的復原／重做。")
            return true
        } catch (e) { cancel(); message = qsTr("未套用：%1").arg(e.message); return false }
    }
    // Cancel on every observed navigation, including an away-and-back round trip.
    onShellLocationChanged: cancel()
    onShellChanged: cancel()
    onGroupChanged: cancel()
    onVisibleChanged: if (!visible) cancel()
    onEnabledChanged: if (!enabled) cancel()
    Connections {
        target: GcpAgentState
        function onRevisionChanged() { root.cancel() }
    }

    Label { font.pixelSize: root.editorFontSize; text: qsTr("介面色彩"); color: "#F3F4F6"; font.bold: true }
    ComboBox { font.pixelSize: root.editorFontSize;
        id: groupBox
        objectName: "theme_group"
        Layout.fillWidth: true
        model: [qsTr("主色"), qsTr("背景"), qsTr("文字")]
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            objectName: "theme_group_option_" + index
            width: groupBox.width
            text: modelData
            font.pixelSize: root.editorFontSize
            highlighted: groupBox.highlightedIndex === index
        }
    }
    Flow {
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: root.group === "accent" ? [{name:qsTr("青"),color:"#00FFFF"},{name:qsTr("藍"),color:"#0080FF"},{name:qsTr("紫"),color:"#A855F7"},{name:qsTr("白"),color:"#FFFFFF"}] :
                root.group === "background" ? [{name:qsTr("黑"),color:"#000000"},{name:qsTr("板岩"),color:"#0F172A"},{name:qsTr("石墨"),color:"#18181B"}] :
                [{name:qsTr("白"),color:"#FFFFFF"},{name:qsTr("暖白"),color:"#FFF4E0"}]
            delegate: Button {
                required property var modelData
                objectName: "theme_shortcut_" + modelData.color.substring(1)
                font.pixelSize: root.editorFontSize
                text: modelData.name
                enabled: GcpAgentState.themeReady
                onClicked: root.previewInput(modelData.color)
            }
        }
        Button { font.pixelSize: root.editorFontSize; objectName: "theme_high_contrast"; text: qsTr("高對比"); enabled: GcpAgentState.themeReady; onClicked: root.previewHighContrast() }
        Button { font.pixelSize: root.editorFontSize; objectName: "theme_reset"; text: qsTr("復原預設色彩"); enabled: GcpAgentState.themeReady; onClicked: { root.cancel(); root.resetPending = true } }
    }
    ColumnLayout {
        Layout.fillWidth: true
        visible: root.highContrastProposal !== null
        Label { font.pixelSize: root.editorFontSize; Layout.fillWidth: true; wrapMode: Text.Wrap; text: qsTr("高對比會調整背景、文字與主色；請確認實際色。僅檢查已列靜態配對。"); color: "#F3F4F6" }
        Repeater {
            model: root.highContrastProposal ? root.highContrastProposal.rows : []
            delegate: RowLayout {
                required property var modelData
                Label { font.pixelSize: root.editorFontSize; text: parent.modelData.group; color: "#F3F4F6" }
                Rectangle { implicitWidth: 28; implicitHeight: 24; color: parent.modelData.requested; border.color: "white" }
                Label { font.pixelSize: root.editorFontSize; text: "→"; color: "#F3F4F6" }
                Rectangle { implicitWidth: 28; implicitHeight: 24; color: parent.modelData.actual; border.color: "white" }
                Label { font.pixelSize: root.editorFontSize; text: parent.modelData.actual; color: "#F3F4F6" }
            }
        }
        Button { font.pixelSize: root.editorFontSize; objectName: "theme_apply_high_contrast"; text: qsTr("確認並套用高對比"); onClicked: root.applyHighContrast() }
    }
    ColumnLayout {
        visible: root.resetPending
        Layout.fillWidth: true
        Label { font.pixelSize: root.editorFontSize; Layout.fillWidth: true; wrapMode: Text.Wrap; text: qsTr("復原預設色彩？版面位置保持目前設定，之後可復原此操作。"); color: "#F3F4F6" }
        Button { font.pixelSize: root.editorFontSize; objectName: "theme_confirm_reset"; text: qsTr("確認復原預設色彩"); onClicked: root.applyReset() }
    }
    TextField { font.pixelSize: root.editorFontSize;
        id: colorInput
        objectName: "theme_input"
        Layout.fillWidth: true
        maximumLength: 256
        placeholderText: qsTr("粉紅、#FF69B4、rgb(0,120,200)、暗一點、海洋風")
        onTextChanged: root.cancel()
        onAccepted: root.previewInput(text)
    }
    Button { font.pixelSize: root.editorFontSize;
        objectName: "theme_preview_input"
        text: qsTr("預覽輸入色彩")
        enabled: GcpAgentState.themeReady && colorInput.text.trim().length > 0
        onClicked: root.previewInput(colorInput.text)
    }
    Label { font.pixelSize: root.editorFontSize; text: qsTr("取色器（RGB）"); color: "#F3F4F6" }
    RowLayout {
        Label { font.pixelSize: root.editorFontSize; text: qsTr("紅"); color: "#F3F4F6" }
        Slider { id: red; objectName: "theme_red"; Layout.fillWidth: true; from: 0; to: 255; stepSize: 1; value: 255; onValueChanged: root.cancel() }
        Label { font.pixelSize: root.editorFontSize; text: String(Math.round(red.value)); color: "#F3F4F6" }
    }
    RowLayout {
        Label { font.pixelSize: root.editorFontSize; text: qsTr("綠"); color: "#F3F4F6" }
        Slider { id: green; objectName: "theme_green"; Layout.fillWidth: true; from: 0; to: 255; stepSize: 1; value: 105; onValueChanged: root.cancel() }
        Label { font.pixelSize: root.editorFontSize; text: String(Math.round(green.value)); color: "#F3F4F6" }
    }
    RowLayout {
        Label { font.pixelSize: root.editorFontSize; text: qsTr("藍"); color: "#F3F4F6" }
        Slider { id: blue; objectName: "theme_blue"; Layout.fillWidth: true; from: 0; to: 255; stepSize: 1; value: 180; onValueChanged: root.cancel() }
        Label { font.pixelSize: root.editorFontSize; text: String(Math.round(blue.value)); color: "#F3F4F6" }
    }
    RowLayout {
        Rectangle { implicitWidth: 36; implicitHeight: 28; color: root.pickedColor; border.color: "#FFFFFF" }
        Label { font.pixelSize: root.editorFontSize; text: root.pickedColor; color: "#F3F4F6" }
        Button { font.pixelSize: root.editorFontSize; objectName: "theme_preview_picker"; text: qsTr("預覽取色"); enabled: GcpAgentState.themeReady; onClicked: root.previewPicker() }
    }
    Label { font.pixelSize: root.editorFontSize;
        Layout.fillWidth: true
        visible: !GcpAgentState.themeReady
        text: qsTr("色彩檢查尚未就緒，保留目前設定。")
        wrapMode: Text.Wrap
        color: "#FBBF24"
    }
    Label { font.pixelSize: root.editorFontSize; Layout.fillWidth: true; visible: root.message !== ""; text: root.message; wrapMode: Text.Wrap; color: "#F3F4F6" }
    Button { font.pixelSize: root.editorFontSize;
        objectName: "theme_model_request"
        visible: root.proposal !== null && root.proposal.kind === "clarify"
        text: qsTr("請模型提議色值")
        enabled: GcpAgentState.themeReady
        onClicked: root.requestModelColor()
    }
    ColumnLayout {
        objectName: "theme_confirmation"
        Layout.fillWidth: true
        visible: root.proposal !== null && root.proposal.kind === "confirm"
        Label { font.pixelSize: root.editorFontSize; Layout.fillWidth: true; text: root.proposal && root.proposal.adjusted ? qsTr("為符合配色檢查，實際色已調整。") : qsTr("請確認色彩"); wrapMode: Text.Wrap; color: "#F3F4F6" }
        RowLayout {
            Label { font.pixelSize: root.editorFontSize; text: qsTr("你要的"); color: "#F3F4F6" }
            Rectangle { objectName: "theme_requested_swatch"; implicitWidth: 32; implicitHeight: 28; color: root.proposal && root.proposal.kind === "confirm" ? root.proposal.requested : "transparent"; border.color: "#FFFFFF" }
            Label { font.pixelSize: root.editorFontSize; text: root.proposal && root.proposal.kind === "confirm" ? root.proposal.requested : ""; color: "#F3F4F6" }
        }
        RowLayout {
            Label { font.pixelSize: root.editorFontSize; text: qsTr("實際套用"); color: "#F3F4F6" }
            Rectangle { objectName: "theme_actual_swatch"; implicitWidth: 32; implicitHeight: 28; color: root.proposal && root.proposal.kind === "confirm" ? root.proposal.actual : "transparent"; border.color: "#FFFFFF" }
            Label { font.pixelSize: root.editorFontSize; text: root.proposal && root.proposal.kind === "confirm" ? root.proposal.actual : ""; color: "#F3F4F6" }
        }
        Label { font.pixelSize: root.editorFontSize; Layout.fillWidth: true; text: root.contrastSummary(root.proposal); wrapMode: Text.Wrap; color: "#F3F4F6" }
        Label { font.pixelSize: root.editorFontSize; Layout.fillWidth: true; text: qsTr("僅檢查已列靜態配對；地圖與影像底色未涵蓋。"); wrapMode: Text.Wrap; color: "#FBBF24" }
        Flow {
            Layout.fillWidth: true
            spacing: 5
            Repeater {
                model: root.tokenRows
                delegate: Rectangle {
                    required property var modelData
                    width: 30; height: 24
                    color: Qt.rgba(modelData.r, modelData.g, modelData.b, modelData.a)
                    border.color: "#FFFFFF"
                    ToolTip.visible: tokenHover.hovered
                    ToolTip.text: modelData.name
                    HoverHandler { id: tokenHover }
                    Accessible.name: modelData.name
                }
            }
        }
        Button { font.pixelSize: root.editorFontSize; objectName: "theme_apply"; text: qsTr("確認並套用實際色"); onClicked: root.applyConfirmed() }
    }
    Button { font.pixelSize: root.editorFontSize; objectName: "theme_cancel"; text: qsTr("取消色彩提議"); visible: root.proposal !== null || root._request !== null || root.highContrastProposal !== null || root.resetPending; onClicked: root.cancel() }
}
