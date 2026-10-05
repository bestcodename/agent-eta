import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

import "../code/logic.mjs" as Logic

// A background task under its session, with its own bar. SessionRow.qml handles the right click on
// it, so the menu can offer to mark a wait recorded with `agent-eta add` done.
ColumnLayout {
    id: taskRow

    property var task
    property real now

    spacing: 0

    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: Kirigami.Units.smallSpacing

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: "└ " + (taskRow.task.label || "-")
            elide: Text.ElideRight
            textFormat: Text.PlainText
            font: Kirigami.Theme.smallFont
        }
        PlasmaComponents3.Label {
            text: taskRow.task.due ? Logic.etaText(taskRow.task) + " · " + Logic.formatClock(taskRow.task.due, taskRow.now)
                                   : i18n("no ETA")
            color: taskRow.task.overdue ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            textFormat: Text.PlainText
            font: Kirigami.Theme.smallFont
        }
    }

    ProgressLine {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.gridUnit
        visible: taskRow.task.progress !== null && taskRow.task.progress !== undefined
        value: taskRow.task.progress || 0
        color: taskRow.task.overdue ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor
    }
}
