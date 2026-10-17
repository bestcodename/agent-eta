import QtQuick

import org.kde.taskmanager as TaskManager

import "../code/logic.mjs" as Logic

// Raises the window a session runs in. A Codex thread opens through its link in the Codex app, and a
// dsh session opens the dsh web UI.
// Any other session is matched by the pids agent-eta lists for it, its own and its ancestors',
// against the pid of every window, since a terminal or an IDE owns the window. Konsole owns all its
// windows in one process, so `agent-eta tab` first makes the session's tab current over D-Bus and
// reports the caption titles that pick its window. PhpStorm owns all its project windows in one
// process, so the project name picks among them. A tab in PhpStorm's terminal cannot be chosen from
// outside.
Item {
    id: jumper

    // The Runner and the agent-eta command line, from main.qml.
    property var launcher
    property string command

    TaskManager.TasksModel {
        id: tasks
        groupMode: TaskManager.TasksModel.GroupDisabled
    }

    function windows() {
        const found = [];
        for (let i = 0; i < tasks.count; i++) {
            const index = tasks.makeModelIndex(i);
            if (!tasks.data(index, TaskManager.AbstractTasksModel.IsWindow)) {
                continue;
            }
            found.push({
                index: i,
                pid: tasks.data(index, TaskManager.AbstractTasksModel.AppPid),
                title: tasks.data(index, Qt.DisplayRole) || "",
            });
        }
        return found;
    }

    function find(session, titles) {
        return Logic.pickWindow(windows(), session.pids || [], session.project_name || "", titles || []);
    }

    function raise(session, titles) {
        const index = find(session, titles);
        if (index >= 0) {
            tasks.requestActivate(tasks.makeModelIndex(index));
        }
    }

    function canJump(session) {
        if (session.agent === "codex") {
            return !!session.id;
        }
        return session.agent === "dsh" ? !!session.web_url : find(session) >= 0;
    }

    // dsh serves no link to a single session, so its jump opens the web UI, which keeps its sign-in
    // in a browser cookie for 30 days.
    function jump(session) {
        if (session.agent === "codex" && session.id) {
            Qt.openUrlExternally("codex://threads/" + encodeURIComponent(session.id));
            return true;
        }
        if (session.agent === "dsh") {
            return !!session.web_url && Qt.openUrlExternally(session.web_url);
        }
        if (find(session) < 0) {
            return false;
        }
        // Outside Konsole the tab call fails fast and the jump runs on pids and the project name.
        const tab = launcher && command ? Logic.tabCommand(command, session.pids) : "";
        if (!tab) {
            raise(session, []);
            return true;
        }
        launcher.run(tab, (code, stdout) => raise(session, Logic.tabTitles(code, stdout)));
        return true;
    }
}
