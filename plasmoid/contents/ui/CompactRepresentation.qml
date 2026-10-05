import QtQuick

import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

// The tray icon. A badge counts the sessions that need you now, red once one of them ran over, and
// a bar along the bottom fills with the working session whose ETA comes soonest. The root is a
// MouseArea, because the system tray forwards its clicks to the first one it finds.
MouseArea {
    id: compact

    property bool wasExpanded: false
    readonly property var next: root.summary.next

    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    activeFocusOnTab: true

    Accessible.name: Plasmoid.title
    Accessible.description: root.toolTipMainText
    Accessible.role: Accessible.Button

    onPressed: wasExpanded = root.expanded
    onClicked: mouse => {
        if (mouse.button === Qt.MiddleButton) {
            root.refresh();
        } else {
            root.expanded = !wasExpanded;
        }
    }

    Kirigami.Icon {
        id: icon
        anchors.fill: parent
        source: root.failure ? "dialog-error" : Plasmoid.icon
        active: compact.containsMouse
    }

    Rectangle {
        id: badge
        visible: root.summary.attention > 0
        anchors.right: parent.right
        anchors.top: parent.top
        width: Math.max(height, count.implicitWidth + 4)
        height: Math.max(Kirigami.Units.gridUnit * 0.6, Math.round(icon.height * 0.5))
        radius: height / 2
        color: root.summary.overdue > 0 ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.neutralTextColor

        PlasmaComponents3.Label {
            id: count
            anchors.centerIn: parent
            text: root.summary.attention
            color: "white"
            font.bold: true
            font.pixelSize: Math.max(8, Math.round(badge.height * 0.75))
            textFormat: Text.PlainText
        }
    }

    Item {
        visible: compact.next !== null
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: Math.max(2, Math.round(icon.height / 10))

        Rectangle {
            anchors.fill: parent
            color: Kirigami.Theme.textColor
            opacity: 0.25
        }
        Rectangle {
            width: parent.width * (compact.next ? compact.next.progress : 0)
            height: parent.height
            color: compact.next && compact.next.overdue ? Kirigami.Theme.negativeTextColor
                : Kirigami.Theme.highlightColor
        }
    }
}
