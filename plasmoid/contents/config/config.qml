import QtQuick

import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: i18nc("@title", "General")
        icon: "chronometer"
        source: "configGeneral.qml"
    }
    ConfigCategory {
        name: i18nc("@title", "Sessions and Launching")
        icon: "system-run"
        source: "configSessions.qml"
    }
    ConfigCategory {
        name: i18nc("@title", "Appearance")
        icon: "preferences-desktop-color"
        source: "configAppearance.qml"
    }
    ConfigCategory {
        name: i18nc("@title", "Notifications")
        icon: "preferences-desktop-notification"
        source: "configNotifications.qml"
    }
}