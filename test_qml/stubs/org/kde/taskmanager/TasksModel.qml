import QtQuick

// Stands in for libtaskmanager's TasksModel, which needs a live KWin. It serves TaskFixture.windows
// and records requestActivate in TaskFixture.activated.
QtObject {
    enum GroupMode {
        GroupDisabled,
        GroupApplications
    }

    property int groupMode: 0
    readonly property int count: TaskFixture.windows.length

    function makeModelIndex(row) {
        return row;
    }

    function data(index, role) {
        const window = TaskFixture.windows[index];
        if (role === AbstractTasksModel.AppPid) {
            return window.pid;
        }
        if (role === AbstractTasksModel.IsWindow) {
            return window.isWindow !== false;
        }
        return role === Qt.DisplayRole ? window.title : undefined;
    }

    function requestActivate(index) {
        TaskFixture.activated = TaskFixture.activated.concat([index]);
    }
}
