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
// carries its countdown, as in `resets in 49m (18:30)`, and the agent's own line names its highest
// share with the reset that comes first.
ColumnLayout {
    id: usageRow

    property var group
    property real now
    property real fade: 0
    property real yellow: 0.66

    spacing: Kirigami.Units.smallSpacing / 2

    RowLayout {
        Layout.fillWidth: true

        PlasmaComponents3.Label {
            Layout.fillWidth: true
            text: usageRow.group.agent
            font.bold: true
            textFormat: Text.PlainText
        }
        PlasmaComponents3.Label {
            text: Logic.usageHeadline(usageRow.group, usageRow.now)
            color: usageRow.group.reached ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            textFormat: Text.PlainText
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
