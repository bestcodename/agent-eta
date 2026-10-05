import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

import "../code/logic.mjs" as Logic

// One session with its tasks underneath. A click raises the window it runs in, and a right click
// opens the action menu of FullRepresentation.qml, for a task with the task's own actions.
PlasmaComponents3.ItemDelegate {
    id: row

    required property var session
    required property real now
    signal menuRequested(var session, var task, Item item, real x, real y)

    Layout.fillWidth: true
    hoverEnabled: true

    onClicked: root.act("jump", session, null)

    // The only right-click handler of the row. A handler on each task row as well would fire next to
    // this one, and whichever came last decided the menu. A session without an id of its own, such as
    // one made up of `agent-eta add` entries, offers its only task from anywhere on the row.
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: eventPoint => {
            const x = eventPoint.position.x, y = eventPoint.position.y;
            let task = row.taskAt(x, y);
            if (!task && !row.session.id && (row.session.taskItems || []).length === 1) {
                task = row.session.taskItems[0];
            }
            row.menuRequested(row.session, task, row, x, y);
        }
    }

    function taskAt(x, y) {
        for (let i = 0; i < tasks.count; i++) {
            const item = tasks.itemAt(i);
            if (item && item.contains(row.mapToItem(item, x, y))) {
                return item.task;
            }
        }
        return null;
    }

    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing * 2

        // The dot sits in a box of icon size, so the titles line up as they did with icons.
        Item {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            Accessible.name: row.session.state

            StateDot {
                anchors.centerIn: parent
                height: Math.round(parent.height * 0.6)
                light: Logic.stateLight(row.session)
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing / 2

            RowLayout {
                Layout.fillWidth: true

                PlasmaComponents3.Label {
                    Layout.fillWidth: true
                    text: Logic.title(row.session)
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                    font.bold: row.session.state === "waiting"
                }
                PlasmaComponents3.Label {
                    text: Logic.etaText(row.session)
                    visible: text !== ""
                    color: row.session.overdue ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
                    textFormat: Text.PlainText
                }
            }

            PlasmaComponents3.Label {
                Layout.fillWidth: true
                text: Logic.detailLine(row.session, row.now)
                elide: Text.ElideRight
                textFormat: Text.PlainText
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }

            ProgressLine {
                Layout.fillWidth: true
                visible: row.session.progress !== null && row.session.progress !== undefined
                value: row.session.progress || 0
                color: row.session.overdue ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor
            }

            Repeater {
                id: tasks
                model: row.session.taskItems

                delegate: TaskRow {
                    required property var modelData
                    Layout.fillWidth: true
                    task: modelData
                    now: row.now
                }
            }
        }
    }
}
