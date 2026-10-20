import QtQuick

import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.kquickcontrolsaddons as KQuickControlsAddons
import org.kde.notification

import "../code/logic.mjs" as Logic
import "../code/shared.js" as Shared

// The agent-eta tray widget. It polls `agent-eta list --json --all` and shows the result as a tray
// icon with a badge, a tooltip on hover and the full overview in a popup. A listing that fails the
// contract check leaves the last valid one in place with its update time, and notifications only
// compare two valid listings. See docs/agent-eta.md, section "Tray widget".
PlasmoidItem {
    id: root

    property var listing: null
    property string failure: ""
    property real updatedAt: 0
    property bool showDormant: false
    property bool showStopped: false
    property string actionFailure: ""
    // A poll rebuilds every row, which would close an open context menu, so polling pauses meanwhile.
    property bool menuOpen: false
    readonly property var summary: Logic.summary(listing)
    // In a panel, and so in the system tray, whose popup header brings the Refresh and Configure buttons.
    readonly property bool inPanel: [PlasmaCore.Types.Horizontal, PlasmaCore.Types.Vertical].includes(Plasmoid.formFactor)
    readonly property string command: Plasmoid.configuration.command || "\"$HOME/.local/bin/agent-eta\""

    Plasmoid.icon: "chronometer"
    Plasmoid.status: summary.status === "attention" ? PlasmaCore.Types.NeedsAttentionStatus
        : summary.status === "active" ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus

    toolTipMainText: failure ? i18n("agent-eta failed") : summary.headline
    toolTipSubText: failure ? failure : Logic.tooltipLines(listing, 7).join("<br>")
    toolTipTextFormat: Text.StyledText

    // On the desktop or in plasmawindowed the overview itself. In a panel it stays unset, because the
    // system tray only shows the popup of an applet without a preferred representation, and Plasma
    // then picks the icon on its own.
    preferredRepresentation: inPanel ? null : fullRepresentation
    compactRepresentation: CompactRepresentation {}
    fullRepresentation: FullRepresentation {}

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Refresh")
            icon.name: "view-refresh"
            onTriggered: root.refresh()
        }
    ]

    Runner {
        id: runner
    }

    WindowJumper {
        id: jumper
        launcher: runner
        command: root.command
    }

    KQuickControlsAddons.Clipboard {
        id: clipboard
    }

    Timer {
        interval: Math.max(1, root.expanded ? Plasmoid.configuration.pollOpen : Plasmoid.configuration.pollClosed) * 1000
        running: !root.menuOpen
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }

    onExpandedChanged: isExpanded => {
        if (isExpanded) {
            refresh();
        }
    }

    function refresh() {
        runner.run(command + " list --json --all", (code, stdout, stderr) => {
            const checked = code === 0 ? Logic.validateListing(stdout) : null;
            if (!checked || !checked.listing) {
                failure = checked ? checked.error
                    : (stderr || stdout || i18n("exit code %1", code)).trim().split("\n").pop();
                return;
            }
            failure = "";
            for (const event of Logic.signalEvents(listing, checked.listing)) {
                notify(event);
            }
            listing = checked.listing;
            updatedAt = Date.now();
        });
    }

    function notify(event) {
        const wanted = {
            waiting: Plasmoid.configuration.notifyWaiting,
            overdue: Plasmoid.configuration.notifyOverdue,
            reset: Plasmoid.configuration.notifyReset,
        };
        if (!wanted[event.kind] || !Shared.claim(event.key, Date.now() / 1000)) {
            return;
        }
        const notification = notificationComponent.createObject(root, {
            title: event.title,
            text: event.text,
            urgency: event.kind === "waiting" ? Notification.HighUrgency : Notification.NormalUrgency,
        });
        notification.sendEvent();
    }

    // Runs one of the row actions on a session or task. See SessionRow.qml for the menu.
    function act(action, session, task) {
        if (action === "jump") {
            jumper.jump(session);
        } else if (action === "ide") {
            runner.detach("phpstorm " + Logic.shellQuote(session.project_root));
        } else if (action === "folder") {
            Qt.openUrlExternally("file://" + encodeURI(session.cwd));
        } else if (action === "copy") {
            clipboard.content = Logic.resumeCommand(session);
        } else if (action === "done" && task) {
            runner.run(command + " done " + Logic.shellQuote(task.id), () => refresh());
        }
        if (action !== "copy" && action !== "done") {
            expanded = false;
        }
    }

    // Account actions have one implementation in the CLI. Errors survive ordinary polls.
    function accountAction(action, account, directory) {
        let args = " account " + action + " " + Logic.shellQuote(account.id);
        if (directory !== undefined && directory !== null)
            args += action === "launch" ? " --directory " + Logic.shellQuote(directory) : " " + Logic.shellQuote(directory);
        runner.run(command + args, (code, stdout, stderr) => {
            actionFailure = code === 0 ? "" : (stderr || i18n("Account action failed")).trim();
            refresh();
            if (code === 0 && (action === "login" || action === "launch")) expanded = false;
        });
    }

    Component {
        id: notificationComponent

        Notification {
            componentName: "plasma_workspace"
            eventId: "notification"
            iconName: "chronometer"
            defaultAction: NotificationAction {
                label: i18n("Show sessions")
                onActivated: root.expanded = true
            }
            onClosed: destroy()
        }
    }
}
