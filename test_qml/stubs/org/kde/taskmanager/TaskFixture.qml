pragma Singleton

import QtQuick

// The windows every stub TasksModel lists, and the indexes the widget asked to activate. A test
// sets `windows` to [{pid, title, isWindow}] and calls reset() between cases.
QtObject {
    property var windows: []
    property var activated: []

    function reset() {
        windows = [];
        activated = [];
    }
}
