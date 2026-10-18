import QtQuick

// The roles of libtaskmanager the widget reads. Values only have to differ from Qt.DisplayRole (0).
QtObject {
    enum Role {
        AppPid = 300,
        IsWindow = 301
    }
}
