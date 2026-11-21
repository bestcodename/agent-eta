import QtQuick
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    id: config
    property string cfg_command
    property int cfg_pollClosed
    property int cfg_pollOpen
    property bool cfg_showUsage
    property bool cfg_showUsageTimeLabels
    property bool cfg_launchInCli
    property int cfg_yellowWidth
    property bool cfg_blendYellow
    property int cfg_blendWidth
    property alias cfg_notifyWaiting: notifyWaiting.checked
    property alias cfg_notifyOverdue: notifyOverdue.checked
    property alias cfg_notifyReset: notifyReset.checked
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
            id: notifyWaiting
            objectName: "notifyWaiting"
            Kirigami.FormData.label: i18nc("@title:group", "Notify when:")
            text: i18nc("@option:check", "A session starts waiting for you")
            QQC2.ToolTip.text: i18n("Notify when a session ends its turn and waits for you. The red pulsing orb shows this as well.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.CheckBox {
            id: notifyOverdue
            objectName: "notifyOverdue"
            text: i18nc("@option:check", "An ETA runs over")
            QQC2.ToolTip.text: i18n("Notify when a session or task is still running after its ETA.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
        QQC2.CheckBox {
            id: notifyReset
            objectName: "notifyReset"
            text: i18nc("@option:check", "A usage limit resets")
            QQC2.ToolTip.text: i18n("Notify when a reached usage limit resets and the account works again.")
            QQC2.ToolTip.visible: hovered || activeFocus
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            Accessible.description: QQC2.ToolTip.text
        }
    }
}