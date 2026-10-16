import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

import "../code/logic.mjs" as Logic

// One agent's usage windows. Each bar fills with the used share, and its tick marks the share of
// the window that has passed, so a fill past the tick runs out before the reset. Fainter ticks from
// windowTicks() mark every hour of the 5-hour window and every day of the 7-day one. The fill comes in
// traffic-light bands from usageBands() in logic.mjs, green below the tick, yellow around it and
// red where the usage runs far ahead of the time, `yellow` sets the half-width
// of the yellow band and `fade` blends it. Every reset
// carries its countdown, as in `resets in 49m (18:30)`, and the status line under the agent's name
// names its highest share with the reset that comes first, beside the freshness of the reading. A click
// anywhere on the row opens the account menu of FullRepresentation.qml.
ColumnLayout {
    id: usageRow

    property var group
    property real now
    property real fade: 0
    property real yellow: 0.66
    signal accountActionRequested(string action, var account)
    signal menuRequested(var account, var item, real x, real y)

    spacing: Kirigami.Units.smallSpacing / 2

    // The whole row opens the account menu, with either button, because nothing else on it takes a
    // click apart from its own buttons, which keep theirs. The hand cursor shows where that works.
    TapHandler {
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        enabled: !!usageRow.group.account
        onTapped: eventPoint => usageRow.menuRequested(usageRow.group.account, usageRow,
                                                       eventPoint.position.x, eventPoint.position.y)
    }
    HoverHandler {
        enabled: !!usageRow.group.account
        cursorShape: Qt.PointingHandCursor
    }

    PlasmaComponents3.Label {
        Layout.fillWidth: true
        text: usageRow.group.agent
        font.bold: true
        textFormat: Text.PlainText
    }

    RowLayout {
        Layout.fillWidth: true
        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: Logic.accountStatus(usageRow.group.account, usageRow.now)
            wrapMode: Text.Wrap
            textFormat: Text.PlainText
            opacity: 0.7
        }
        PlasmaComponents3.Label {
            text: Logic.usageHeadline(usageRow.group, usageRow.now)
            color: usageRow.group.reached ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            textFormat: Text.PlainText
        }
        PlasmaComponents3.ToolButton {
            text: i18n("Log in")
            visible: !!usageRow.group.account && ["logged_out", "mismatch"].includes(usageRow.group.account.auth_state)
            onClicked: usageRow.accountActionRequested("login", usageRow.group.account)
        }
        PlasmaComponents3.ToolButton {
            text: i18n("Remove")
            icon.name: "edit-delete"
            visible: !!usageRow.group.account && usageRow.group.account.can_remove && usageRow.group.account.auth_state === "logged_out"
            onClicked: usageRow.accountActionRequested("remove", usageRow.group.account)
        }
    }

    Repeater {
        model: usageRow.group.windows

        delegate: RowLayout {
            required property var modelData
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing

            PlasmaComponents3.Label {
                Layout.preferredWidth: Kirigami.Units.gridUnit * 1.5
                text: Logic.formatWindow(modelData.minutes)
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }
            ProgressLine {
                Layout.fillWidth: true
                value: (modelData.used || 0) / 100
                marker: modelData.elapsed === null || modelData.elapsed === undefined ? -1 : modelData.elapsed / 100
                bands: Logic.usageBands(modelData, usageRow.fade, usageRow.yellow)
                ticks: Logic.windowTicks(modelData.minutes)
            }
            PlasmaComponents3.Label {
                Layout.minimumWidth: Kirigami.Units.gridUnit * 12
                horizontalAlignment: Text.AlignRight
                text: modelData.remaining === null || modelData.remaining === undefined
                    ? i18n("%1 · no reading", Logic.percent(modelData.used))
                    : i18n("%1 · resets %2", Logic.percent(modelData.used),
                           Logic.resetText(modelData.resets_at, usageRow.now))
                font: Kirigami.Theme.smallFont
                textFormat: Text.PlainText
            }
        }
    }
}
