import QtQuick
import QtQuick.Controls as QQC2

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

KCM.SimpleKCM {
    property alias cfg_command: command.text
    property alias cfg_pollClosed: pollClosed.value
    property alias cfg_pollOpen: pollOpen.value
    property alias cfg_showUsage: showUsage.checked
    property alias cfg_blendYellow: blendYellow.checked
    property alias cfg_blendWidth: blendWidth.value
    property alias cfg_notifyWaiting: notifyWaiting.checked
    property alias cfg_notifyOverdue: notifyOverdue.checked
    property alias cfg_notifyReset: notifyReset.checked
    // Plasma also hands every page the defaults, and warns about each one the page does not declare.
    property string cfg_commandDefault
    property int cfg_pollClosedDefault
    property int cfg_pollOpenDefault
    property bool cfg_showUsageDefault
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
        QQC2.CheckBox {
            id: showUsage
            Kirigami.FormData.label: i18nc("@title:group", "Show:")
            text: i18nc("@option:check", "Usage windows")
        }
        QQC2.CheckBox {
            id: blendYellow
            enabled: showUsage.checked
            text: i18nc("@option:check", "Blend the yellow band of a usage bar")
        }
        QQC2.SpinBox {
            id: blendWidth
            Kirigami.FormData.label: i18nc("@label:spinbox", "Fade width (% of each half of the yellow band):")
            enabled: showUsage.checked && blendYellow.checked
            from: 10
            to: 100
            stepSize: 10
        }
        QQC2.CheckBox {
            id: notifyWaiting
            Kirigami.FormData.label: i18nc("@title:group", "Notify when:")
            text: i18nc("@option:check", "A session starts waiting for you")
        }
        QQC2.CheckBox {
            id: notifyOverdue
            text: i18nc("@option:check", "An ETA runs over")
        }
        QQC2.CheckBox {
            id: notifyReset
            text: i18nc("@option:check", "A usage limit resets")
        }
    }
}
