import QtQuick

import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

import "../code/logic.mjs" as Logic

// A compact local-time axis. Font measurements decide which labels fit; thinning never moves ticks.
Item {
    id: axis

    property var marks: []
    readonly property var labels: Logic.fitTimeLabels(marks.map(mark => {
        const text = Qt.formatDateTime(new Date(mark.at * 1000), mark.days ? "ddd" : "HH:mm");
        return Object.assign({}, mark, {text: text, width: Math.ceil(metrics.advanceWidth(text))});
    }), width, Kirigami.Units.smallSpacing)
    implicitHeight: labels.length ? Math.ceil(metrics.height) : 0

    FontMetrics {
        id: metrics
        font: Kirigami.Theme.smallFont
    }
    Repeater {
        model: axis.labels

        delegate: PlasmaComponents3.Label {
            required property var modelData
            objectName: "usageTimeLabel"
            x: modelData.x
            width: modelData.width
            text: modelData.text
            textFormat: Text.PlainText
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            Accessible.name: Qt.formatDateTime(new Date(modelData.at * 1000), "dddd, dd MMM yyyy HH:mm t")
            HoverHandler { id: hover }
            PlasmaComponents3.ToolTip.text: Accessible.name
            PlasmaComponents3.ToolTip.visible: hover.hovered
        }
    }
}
