import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts

import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

import "../code/logic.mjs" as Logic

// The usage block cutoffs and handoff thresholds, which live in ~/.config/agent-eta/config.json
// rather than in the widget's own settings, because the CLI, the hooks and bestcodename/ai's usage
// guard read them too. The page loads them with `agent-eta config get --json` and saves the whole
// form with `agent-eta config set`. Plasma closes the dialog right after saveConfig() on OK, so the
// save runs detached and cannot be cut short with the page.
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

    signal configurationChanged

    // Null until the CLI answered, which keeps every control disabled.
    property var form: null
    // Set once on load, so the repeaters keep their rows while the form changes.
    property var agentKeys: ({})
    property var agentList: []
    readonly property var modes: ["default", "off", "own"]
    readonly property var windowKeys: ["five_hour_percent", "weekly_percent", "monthly_percent"]
    readonly property var windowLabels: ({five_hour_percent: i18nc("@label:spinbox", "5 h"),
                                          weekly_percent: i18nc("@label:spinbox", "7 d"),
                                          monthly_percent: i18nc("@label:spinbox", "30 d")})
    readonly property var titles: ({usage_block: i18nc("@title:group", "Count as blocked"),
                                    handoff: i18nc("@title:group", "Hand over")})
    readonly property var switches: ({usage_block: i18nc("@option:check", "Count accounts as blocked at a cutoff"),
                                      handoff: i18nc("@option:check", "Hand sessions over at a threshold")})
    readonly property var switchTips: ({
        usage_block: i18n("Count an account as blocked once a window reaches its cutoff, before the provider's own limit. Off: only the provider limit blocks."),
        handoff: i18n("Hand sessions over when a window reaches its threshold: Claude Code through the usage guard, Codex at the end of a turn, PhpStorm chats get a warning. Off: no handoffs and no usage-guard warnings.")
    })
    readonly property string valueTip: i18n("Usage in percent for this window, for every agent on Default. Built-in: block at 99 %; hand over at 100 % (5 h), 98 % (7 d) and 98 % (30 d).")
    readonly property string modeTip: i18n("Default uses the values above; Off disables this for the agent; Own values sets its own.")

    function edit(section, agent, key, value) {
        form = Logic.limitsWith(form, section, agent, key, value);
        configurationChanged();
    }

    function saveConfig() {
        if (form) {
            runner.detach(cfg_command + " config set " + Logic.limitsArguments(form).join(" "));
        }
    }

    Runner { id: runner }

    Component.onCompleted: runner.run(cfg_command + " config get --json", (code, stdout, stderr) => {
        try {
            if (code !== 0) {
                throw new Error(stderr.trim() || "exit code " + code);
            }
            const loaded = Logic.limitsForm(JSON.parse(stdout));
            agentKeys = loaded.agents;
            agentList = Object.keys(loaded.agents);
            form = loaded;
            status.text = "";
        } catch (error) {
            status.text = i18n("Could not read the usage limits: %1", String(error.message || error));
        }
    })

    ColumnLayout {
        spacing: Kirigami.Units.largeSpacing

        QQC2.Label {
            id: status
            Layout.fillWidth: true
            text: i18n("Loading…")
            visible: text !== ""
            wrapMode: Text.Wrap
            color: config.form ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
        }

        Repeater {
            model: Logic.LIMIT_SECTIONS

            delegate: ColumnLayout {
                id: sectionColumn
                required property string modelData
                readonly property var section: config.form ? config.form.sections[modelData] : null
                Layout.fillWidth: true
                enabled: !!config.form

                Kirigami.Heading {
                    level: 3
                    text: config.titles[sectionColumn.modelData]
                }
                QQC2.CheckBox {
                    objectName: sectionColumn.modelData + ".enabled"
                    text: config.switches[sectionColumn.modelData]
                    checked: !!sectionColumn.section && sectionColumn.section.enabled
                    onToggled: config.edit(sectionColumn.modelData, null, "enabled", checked)
                    QQC2.ToolTip.text: config.switchTips[sectionColumn.modelData]
                    QQC2.ToolTip.visible: hovered || activeFocus
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    Accessible.description: QQC2.ToolTip.text
                }
                RowLayout {
                    enabled: !!sectionColumn.section && sectionColumn.section.enabled
                    QQC2.Label {
                        text: i18nc("@label", "Default:")
                        Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                    }
                    Repeater {
                        model: config.windowKeys

                        delegate: RowLayout {
                            id: defaultValue
                            required property string modelData
                            QQC2.Label { text: config.windowLabels[defaultValue.modelData] }
                            QQC2.SpinBox {
                                objectName: sectionColumn.modelData + "." + defaultValue.modelData
                                from: 1
                                to: 100
                                editable: true
                                value: sectionColumn.section ? sectionColumn.section.defaults[defaultValue.modelData] : 1
                                onValueModified: config.edit(sectionColumn.modelData, null, defaultValue.modelData, value)
                                QQC2.ToolTip.text: config.valueTip
                                QQC2.ToolTip.visible: hovered || activeFocus
                                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                                Accessible.description: QQC2.ToolTip.text
                            }
                        }
                    }
                }
                Repeater {
                    model: config.agentList

                    delegate: RowLayout {
                        id: agentRow
                        required property string modelData
                        readonly property var agent: sectionColumn.section ? sectionColumn.section.agents[modelData] : null
                        enabled: !!sectionColumn.section && sectionColumn.section.enabled

                        QQC2.Label {
                            text: config.form ? config.form.names[agentRow.modelData] : agentRow.modelData
                            Layout.preferredWidth: Kirigami.Units.gridUnit * 7
                        }
                        QQC2.ComboBox {
                            objectName: sectionColumn.modelData + "." + agentRow.modelData + ".mode"
                            model: [i18nc("@item:inlistbox", "Default"), i18nc("@item:inlistbox", "Off"),
                                    i18nc("@item:inlistbox", "Own values")]
                            currentIndex: agentRow.agent ? config.modes.indexOf(agentRow.agent.mode) : 0
                            onActivated: index => config.edit(sectionColumn.modelData, agentRow.modelData, "mode", config.modes[index])
                            QQC2.ToolTip.text: config.modeTip
                            QQC2.ToolTip.visible: hovered || activeFocus
                            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                            Accessible.description: QQC2.ToolTip.text
                        }
                        Repeater {
                            model: config.agentKeys[agentRow.modelData] || []

                            delegate: RowLayout {
                                id: ownValue
                                required property string modelData
                                visible: !!agentRow.agent && agentRow.agent.mode === "own"
                                QQC2.Label { text: config.windowLabels[ownValue.modelData] }
                                QQC2.SpinBox {
                                    objectName: sectionColumn.modelData + "." + agentRow.modelData + "." + ownValue.modelData
                                    from: 1
                                    to: 100
                                    editable: true
                                    value: agentRow.agent ? agentRow.agent.values[ownValue.modelData] : 1
                                    onValueModified: config.edit(sectionColumn.modelData, agentRow.modelData, ownValue.modelData, value)
                                    QQC2.ToolTip.text: config.valueTip
                                    QQC2.ToolTip.visible: hovered || activeFocus
                                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                                    Accessible.description: QQC2.ToolTip.text
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
