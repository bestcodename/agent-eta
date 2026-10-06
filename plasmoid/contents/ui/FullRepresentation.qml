import QtQuick
import QtQuick.Layouts

import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami

import "../code/logic.mjs" as Logic

// The popup. Sessions come in agent-eta's own order and sections, the ones that need you first and
// dormant ones folded away, followed by the usage windows of every agent.
PlasmaExtras.Representation {
    id: full

    readonly property var groups: Logic.groupSessions(root.listing, root.showDormant)
    readonly property var usage: Logic.usageGroups(root.listing ? root.listing.usage : [])
    readonly property real now: root.listing ? root.listing.now : Date.now() / 1000

    Layout.minimumWidth: Kirigami.Units.gridUnit * 24
    Layout.minimumHeight: Kirigami.Units.gridUnit * 14
    Layout.preferredWidth: Kirigami.Units.gridUnit * 30
    Layout.preferredHeight: Kirigami.Units.gridUnit * 32
    Layout.maximumWidth: Kirigami.Units.gridUnit * 60
    Layout.maximumHeight: Kirigami.Units.gridUnit * 60

    header: PlasmaExtras.PlasmoidHeading {
        RowLayout {
            anchors.fill: parent

            PlasmaExtras.Heading {
                Layout.fillWidth: true
                level: 4
                text: root.failure ? i18n("agent-eta failed") : root.summary.headline
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }
            PlasmaComponents3.ToolButton {
                icon.name: "view-refresh"
                display: PlasmaComponents3.AbstractButton.IconOnly
                text: i18n("Refresh")
                visible: !root.inPanel
                onClicked: root.refresh()
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
            }
            PlasmaComponents3.ToolButton {
                icon.name: "configure"
                display: PlasmaComponents3.AbstractButton.IconOnly
                text: i18n("Configure…")
                visible: !root.inPanel
                onClicked: Plasmoid.internalAction("configure").trigger()
                PlasmaComponents3.ToolTip.text: text
                PlasmaComponents3.ToolTip.visible: hovered
            }
        }
    }

    footer: PlasmaExtras.PlasmoidHeading {
        position: PlasmaComponents3.ToolBar.Footer

        PlasmaComponents3.Label {
            anchors.fill: parent
            text: root.failure ? root.failure
                : root.updatedAt ? i18n("Updated %1", Qt.formatTime(new Date(root.updatedAt), "HH:mm:ss"))
                : i18n("Loading…")
            elide: Text.ElideRight
            textFormat: Text.PlainText
            font: Kirigami.Theme.smallFont
            opacity: 0.7
        }
    }

    PlasmaComponents3.ScrollView {
        id: scroll
        anchors.fill: parent
        // Rows only ever wrap or elide, so nothing needs a horizontal bar. It showed anyway with the
        // content as wide as the view, which is QTBUG-83890, and Plasma's own Bluetooth applet works
        // around it the same way.
        PlasmaComponents3.ScrollBar.horizontal.policy: PlasmaComponents3.ScrollBar.AlwaysOff
        contentWidth: availableWidth - contentItem.leftMargin - contentItem.rightMargin

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 0

            Repeater {
                model: full.groups

                delegate: ColumnLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: 0

                    PlasmaExtras.ListSectionHeader {
                        Layout.fillWidth: true
                        text: modelData.title + " (" + modelData.count + ")"
                    }
                    PlasmaComponents3.ToolButton {
                        visible: modelData.section === Logic.DORMANT_SECTION
                        Layout.leftMargin: Kirigami.Units.largeSpacing
                        text: root.showDormant ? i18n("Hide dormant sessions") : i18n("Show sessions idle for more than 12 hours")
                        icon.name: root.showDormant ? "go-up" : "go-down"
                        onClicked: root.showDormant = !root.showDormant
                    }
                    Repeater {
                        model: modelData.sessions

                        delegate: SessionRow {
                            required property var modelData
                            session: modelData
                            now: full.now
                            onMenuRequested: (session, task, item, x, y) => actions.show(session, task, item, x, y)
                        }
                    }
                }
            }

            PlasmaExtras.ListSectionHeader {
                Layout.fillWidth: true
                visible: Plasmoid.configuration.showUsage && full.usage.length > 0
                text: i18n("Usage")
            }
            Repeater {
                model: Plasmoid.configuration.showUsage ? full.usage : []

                delegate: UsageRow {
                    required property var modelData
                    Layout.fillWidth: true
                    Layout.leftMargin: Kirigami.Units.largeSpacing
                    Layout.rightMargin: Kirigami.Units.largeSpacing
                    Layout.bottomMargin: Kirigami.Units.largeSpacing
                    group: modelData
                    now: full.now
                    fade: Plasmoid.configuration.blendYellow ? Plasmoid.configuration.blendWidth / 100 : 0
                }
            }
        }
    }

    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 4
        visible: root.listing !== null && full.groups.length === 0 && !root.failure
        iconName: "chronometer"
        text: i18n("No agent sessions")
        explanation: i18n("Claude Code, Codex and local runs show up here while they run.")
    }

    PlasmaExtras.PlaceholderMessage {
        anchors.centerIn: parent
        width: parent.width - Kirigami.Units.gridUnit * 4
        visible: root.failure !== "" && root.listing === null
        iconName: "dialog-error"
        text: i18n("agent-eta failed")
        explanation: root.failure
    }

    PlasmaExtras.Menu {
        id: actions

        property var session: null
        property var task: null
        property bool jumpable: false

        onStatusChanged: root.menuOpen = status !== PlasmaExtras.Menu.Closed

        function show(session, task, item, x, y) {
            this.session = session;
            this.task = task;
            jumpable = jumper.canJump(session);
            visualParent = item;
            root.menuOpen = true;
            open(x, y);
        }

        PlasmaExtras.MenuItem {
            text: actions.session && actions.session.agent === "codex" ? i18n("Open thread in Codex")
                : actions.session && actions.session.agent === "dsh" ? i18n("Open dsh web UI")
                : i18n("Jump to window")
            icon: "window"
            enabled: actions.jumpable
            onClicked: root.act("jump", actions.session, actions.task)
        }
        PlasmaExtras.MenuItem {
            text: i18n("Open in PhpStorm")
            icon: "document-open"
            visible: !!(actions.session && actions.session.project_root)
            onClicked: root.act("ide", actions.session, actions.task)
        }
        PlasmaExtras.MenuItem {
            text: i18n("Open folder")
            icon: "folder-open"
            visible: !!(actions.session && actions.session.cwd)
            onClicked: root.act("folder", actions.session, actions.task)
        }
        PlasmaExtras.MenuItem {
            text: actions.session && actions.session.agent === "codex" ? i18n("Copy thread link")
                : i18n("Copy resume command")
            icon: "edit-copy"
            visible: !!(actions.session && Logic.resumeCommand(actions.session))
            onClicked: root.act("copy", actions.session, actions.task)
        }
        PlasmaExtras.MenuItem {
            text: i18n("Mark done")
            icon: "checkmark"
            visible: !!(actions.task && actions.task.source === "add")
            onClicked: root.act("done", actions.session, actions.task)
        }
    }
}
