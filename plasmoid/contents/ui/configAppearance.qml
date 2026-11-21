import QtQuick
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    id: config
    property string cfg_command
    property int cfg_pollClosed
    property int cfg_pollOpen
    property alias cfg_showUsage: showUsage.checked
    property alias cfg_showUsageTimeLabels: showUsageTimeLabels.checked
    property bool cfg_launchInCli
    property alias cfg_yellowWidth: yellowWidth.value
    property alias cfg_blendYellow: blendYellow.checked
    property alias cfg_blendWidth: blendWidth.value
    property bool cfg_notifyWaiting
    property bool cfg_notifyOverdue
    property bool cfg_notifyReset
    // The popup's usage headers set these; the page only declares them, so Plasma does not warn.
    property bool cfg_usageCollapsed
    property bool cfg_usageOpenCollapsed
    property bool cfg_usageBlockedCollapsed
    property bool cfg_usageCollapsedDefault
    property bool cfg_usageOpenCollapsedDefault
    property bool cfg_usageBlockedCollapsedDefault
    // Plasma also hands every page the defaults, and warns about each one the page does not declare.
    property string cfg_commandDefault
    property int cfg_pollClosedDefault
    property int cfg_pollOpenDefault
    property bool cfg_showUsageDefault
    property bool cfg_showUsageTimeLabelsDefault
    property bool cfg_launchInCliDefault
    property int cfg_yellowWidthDefault
    property bool cfg_blendYellowDefault
    property int cfg_blendWidthDefault
    property bool cfg_notifyWaitingDefault
    property bool cfg_notifyOverdueDefault
    property bool cfg_notifyResetDefault

    Kirigami.FormLayout {
        QQC2.CheckBox {
            id: showUsage
            objectName: "showUsage"
            Kirigami.FormData.label: i18nc("@title:group", "Show:")
            text: i18nc("@option:check", "Usage windows")
            QQC2.ToolTip.text: i18n("Show each account's usage windows as bars with their resets in the popup.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.CheckBox {
            id: showUsageTimeLabels
            objectName: "showUsageTimeLabels"
            enabled: showUsage.checked
            text: i18nc("@option:check", "Time labels on usage bars")
            QQC2.ToolTip.text: enabled
                ? i18n("Show local hours or weekdays along each usage window. Labels adapt to the available width.")
                : i18n("Enable usage windows to change their time labels.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.SpinBox {
            id: yellowWidth
            objectName: "yellowWidth"
            Kirigami.FormData.label: i18nc("@label:spinbox", "Yellow band (% of the usage past the tick, each side):")
            enabled: showUsage.checked
            from: 0
            to: 100
            QQC2.ToolTip.text: enabled
                ? i18n("Half-width of the yellow band around the pace tick, as a share of how far the usage runs past the tick. 0 leaves only green and red.")
                : i18n("Enable usage windows to change the yellow band.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.CheckBox {
            id: blendYellow
            objectName: "blendYellow"
            enabled: showUsage.checked
            text: i18nc("@option:check", "Blend the yellow band of a usage bar")
            QQC2.ToolTip.text: enabled
                ? i18n("Fade the yellow band into green and red instead of hard edges.")
                : i18n("Enable usage windows to change the yellow band.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.SpinBox {
            id: blendWidth
            objectName: "blendWidth"
            Kirigami.FormData.label: i18nc("@label:spinbox", "Fade width (% of each half of the yellow band):")
            enabled: showUsage.checked && blendYellow.checked
            from: 10
            to: 100
            stepSize: 10
            QQC2.ToolTip.text: enabled
                ? i18n("Share of each half of the yellow band that fades. 100 leaves pure yellow only at the tick.")
                : !showUsage.checked
                    ? i18n("Enable usage windows to change the fade.")
                    : i18n("Enable blending to change the fade width.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
    }
}