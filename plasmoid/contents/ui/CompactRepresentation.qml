import QtQuick

import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

// The tray icon. An orb in traffic-light colours tells whether a session waits for you, red with
// their number, whether one is idle or ran over, yellow with their number, or whether all of them
// work, green. A bar along the bottom fills with the working session whose ETA comes soonest. The
// root is a MouseArea, because the system tray forwards its clicks to the first one it finds.
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

    StateDot {
        visible: root.summary.light !== "none"
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(Kirigami.Units.gridUnit * 0.6, Math.round(icon.height * 0.5))
        light: root.summary.light
        count: root.summary.orbCount
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
