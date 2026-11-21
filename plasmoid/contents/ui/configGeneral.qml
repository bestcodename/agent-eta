import QtQuick
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    id: config
    property alias cfg_command: command.text
    property alias cfg_pollClosed: pollClosed.value
    property alias cfg_pollOpen: pollOpen.value
    property bool cfg_showUsage
    property bool cfg_showUsageTimeLabels
    property bool cfg_launchInCli
    property int cfg_yellowWidth
    property bool cfg_blendYellow
    property int cfg_blendWidth
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
        QQC2.TextField {
            id: command
            objectName: "command"
            Kirigami.FormData.label: i18nc("@label:textbox", "agent-eta command:")
            QQC2.ToolTip.text: i18n("The agent-eta command the widget runs for every refresh and action. Keep the full path, because plasmashell's PATH lacks ~/.local/bin.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.SpinBox {
            id: pollClosed
            objectName: "pollClosed"
            Kirigami.FormData.label: i18nc("@label:spinbox", "Refresh every (seconds), closed:")
            from: 1
            to: 300
            QQC2.ToolTip.text: i18n("How often the widget reads the sessions while the popup is closed.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.SpinBox {
            id: pollOpen
            objectName: "pollOpen"
            Kirigami.FormData.label: i18nc("@label:spinbox", "Refresh every (seconds), open:")
            from: 1
            to: 60
            QQC2.ToolTip.text: i18n("How often the widget reads the sessions while the popup is open.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
    }
}