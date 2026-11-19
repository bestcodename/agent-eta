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
            Kirigami.FormData.label: i18nc("@label:textbox", "agent-eta command:")
        }
        QQC2.SpinBox {
            id: pollClosed
            Kirigami.FormData.label: i18nc("@label:spinbox", "Refresh every (seconds), closed:")
            from: 1
            to: 300
        }
        QQC2.SpinBox {
            id: pollOpen
            Kirigami.FormData.label: i18nc("@label:spinbox", "Refresh every (seconds), open:")
            from: 1
            to: 60
        }
    }
}