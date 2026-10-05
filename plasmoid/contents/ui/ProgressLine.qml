import QtQuick

import org.kde.kirigami as Kirigami

// A thin bar. `value` fills it from 0 to 1, and `marker`, when 0 or more, draws a tick there, which
// the usage rows use for the share of the window that has passed.
Item {
    id: line

    property real value: 0
    property real marker: -1
    property color color: Kirigami.Theme.highlightColor

    implicitHeight: Math.max(3, Math.round(Kirigami.Units.smallSpacing * 1.5))

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Kirigami.Theme.textColor
        opacity: 0.15
    }
    Rectangle {
        width: parent.width * Math.max(0, Math.min(1, line.value))
        height: parent.height
        radius: height / 2
        color: line.color
    }
    Rectangle {
        visible: line.marker >= 0
        x: Math.round(parent.width * Math.min(1, line.marker)) - 1
        y: -2
        width: 2
        height: parent.height + 4
        color: Kirigami.Theme.textColor
    }
}
