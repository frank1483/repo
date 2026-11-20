// 「查看手冊引文」視窗（說明 citation_viewer_v1，使用者 11/21 03:08「引文視窗照建議」）。骨架元件，只蓋工作區（V2）。
// 內容＝開啟當下 W5 綁定的引文快照，依原順序：出處一行（文件 › 章節，版本）＋引文全文（不縮短、不加「…」）。超過高度可捲動（V1）。
// 關閉：按鈕、返回鍵（Escape／Back）、新回答、critical（由工作區呼叫）。開關不觸發轉場。viewer-m1-0.1
import QtQuick
import QGroundControl.GCP

Rectangle {
    id: root
    property var citations: []          // [{doc, heading, doc_version, text}]
    property bool ok: true
    signal closeRequested(string reason)
    color: GcpTheme.color.panelFill
    border.color: GcpTheme.color.panelBorder; border.width: 1
    focus: visible
    Keys.onEscapePressed: root.closeRequested("back")
    Keys.onBackPressed: root.closeRequested("back")
    readonly property real titleH: Math.ceil(GcpTheme.font.sectionTitle * 1.5)
    function backPressed() { root.closeRequested("back") }
    function scrollToEnd() { flick.contentY = Math.max(0, flick.contentHeight - flick.height) }
    readonly property alias flick: flick
    Item {
        id: header
        x: 0; y: 0; width: root.width; height: 56
        Text { x: 16; anchors.verticalCenter: parent.verticalCenter; text: "手冊引文（" + root.citations.length + " 段）"
               font.pixelSize: GcpTheme.font.sectionTitle; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
        Rectangle {
            id: closeBtn
            width: 96; height: 40; radius: GcpTheme.radius.small; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
            color: GcpTheme.color.primary
            Text { anchors.centerIn: parent; text: "關閉"; font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: "#ffffff" }
            MouseArea { anchors.fill: parent; onClicked: root.closeRequested("button") }
        }
    }
    Flickable {
        id: flick
        x: 12; y: header.height; width: root.width - 24; height: root.height - header.height - 12
        clip: true; contentWidth: width; contentHeight: col.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        Column {
            id: col
            width: flick.width; spacing: 8
            Text { visible: !root.ok; text: "資料無法顯示"; font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textSecondary }
            Repeater {
                model: root.ok ? root.citations : []
                Rectangle {
                    required property var modelData
                    width: col.width; height: inner.implicitHeight + 16; radius: GcpTheme.radius.medium
                    color: GcpTheme.color.bgCard; border.color: GcpTheme.color.borderDefault; border.width: 1
                    Column {
                        id: inner
                        x: 12; y: 8; width: parent.width - 24; spacing: 4
                        Text { width: inner.width; wrapMode: Text.Wrap; text: "出處：" + modelData.doc + " › " + modelData.heading + "，" + modelData.doc_version
                               font.pixelSize: GcpTheme.font.scale13; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textLabel }
                        Text { width: inner.width; wrapMode: Text.Wrap; text: modelData.text
                               font.pixelSize: GcpTheme.font.scale16; font.family: GcpTheme.font.chineseFamily; color: GcpTheme.color.textPrimary }
                    }
                }
            }
        }
    }
}
