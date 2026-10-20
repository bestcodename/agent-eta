import QtQuick

import org.kde.plasma.components as PlasmaComponents3

// A traffic-light dot, as the tray orb with a count and as the state marker of a session row. A
// plain dot instead of an icon, because nothing about it should look like a button. The light names
// come from logic.mjs, lightColour() of agent-eta's semantic lights.
Rectangle {
    id: dot

    property string light: "grey"
    property int count: 0

    width: Math.max(height, count > 0 ? label.implicitWidth + 4 : height)
    radius: height / 2
    color: lights.colorOf(light)

    Lights {
        id: lights
    }

    PlasmaComponents3.Label {
        id: label
        anchors.centerIn: parent
        visible: dot.count > 0
        text: dot.count
        // Dark text on yellow, white on red and green, so the count stays readable on each.
        color: dot.light === "yellow" ? "black" : "white"
        font.bold: true
        font.pixelSize: Math.max(8, Math.round(dot.height * 0.75))
        textFormat: Text.PlainText
    }
}
