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

    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: eventPoint => row.menuRequested(row.session, null, row, eventPoint.position.x,
                                                   eventPoint.position.y)
    }

    contentItem: RowLayout {
        spacing: Kirigami.Units.smallSpacing * 2

        Kirigami.Icon {
            Layout.alignment: Qt.AlignTop
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
            source: Logic.stateIcon(row.session)
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
                model: row.session.taskItems

                delegate: TaskRow {
                    required property var modelData
                    Layout.fillWidth: true
                    task: modelData
                    now: row.now
                    onMenuRequested: (item, x, y) => row.menuRequested(row.session, modelData, item, x, y)
                }
            }
        }
    }
}
