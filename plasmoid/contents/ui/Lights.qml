import QtQuick

import org.kde.kirigami as Kirigami

// The traffic-light colours by the names logic.mjs hands out, for the state dots and the usage bars.
// An Item rather than a QtObject, so Kirigami.Theme follows the colour set of where it sits.
Item {
    // Breeze's warning yellow. The theme's neutral colour is orange, which reads as a second red
    // next to a real one.
    readonly property color yellow: "#fdbc4b"

    function colorOf(light) {
        return light === "red" ? Kirigami.Theme.negativeTextColor
            : light === "yellow" ? yellow
            : light === "green" ? Kirigami.Theme.positiveTextColor
            : Kirigami.Theme.disabledTextColor;
    }
}
