import QtQuick

import org.kde.taskmanager as TaskManager

import "../code/logic.mjs" as Logic

// Raises the window a session runs in. A Codex thread opens through its link in the Codex app.
// Any other session is matched by the pids agent-eta lists for it, its own and its ancestors',
// against the pid of every window, since a terminal or an IDE owns the window. PhpStorm owns all
// its project windows in one process, so the project name picks among them. A terminal tab inside
// a window cannot be chosen from outside.
Item {
    id: jumper

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

    function find(session) {
        return Logic.pickWindow(windows(), session.pids || [], session.project_name || "");
    }

    function canJump(session) {
        return session.agent === "codex" ? !!session.id : find(session) >= 0;
    }

    function jump(session) {
        if (session.agent === "codex" && session.id) {
            Qt.openUrlExternally("codex://threads/" + encodeURIComponent(session.id));
            return true;
        }
        const index = find(session);
        if (index < 0) {
            return false;
        }
        tasks.requestActivate(tasks.makeModelIndex(index));
        return true;
    }
}
