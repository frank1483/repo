// 依 component_id 選 W1～W5（只允許目錄內 5 個；未知 ID 不建立任何元件）。
import QtQuick

Loader {
    id: root
    property var bound: null
    readonly property var srcMap: ({ W1_FACT: "GenuiW1Fact.qml", W2_SERIES: "GenuiW2Series.qml", W3_TABLE: "GenuiW3Table.qml", W4_DIAG: "GenuiW4Diag.qml", W5_DOC: "GenuiW5Doc.qml" })
    property string componentId: ""
    source: Object.prototype.hasOwnProperty.call(srcMap, componentId) ? srcMap[componentId] : ""
    onLoaded: item.bound = Qt.binding(function () { return root.bound })
}
