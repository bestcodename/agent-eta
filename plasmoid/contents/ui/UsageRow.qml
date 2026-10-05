import QtQuick
import QtQuick.Layouts

import org.kde.plasma.components as PlasmaComponents3
import org.kde.kirigami as Kirigami

import "../code/logic.mjs" as Logic

// One agent's usage windows. Each bar fills with the used share, and its tick marks the share of
// the window that has passed, so a fill past the tick runs out before the reset. Red means the
// limit is reached, orange that the usage runs ahead of the time. Every reset carries its
// countdown, as in `resets 18:30 (in 49m)`.
ColumnLayout {
    id: usageRow

    property var group
    property real now

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
            text: usageRow.group.reached
                ? i18n("blocked until %1", Logic.resetText(usageRow.group.resetBy.resets_at, usageRow.now))
                : Logic.percent(usageRow.group.used)
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
                color: modelData.reached ? Kirigami.Theme.negativeTextColor
                    : modelData.ahead ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.positiveTextColor
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
