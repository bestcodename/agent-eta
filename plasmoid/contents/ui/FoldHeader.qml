import QtQuick
import QtQuick.Layouts

import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami

// A section header that folds what follows it. A click, Space or Enter emits foldRequested; the owner
// keeps the state and hands it back as `collapsed`, which turns the arrow.
PlasmaExtras.ListSectionHeader {
    id: header

    property bool collapsed: false
    signal foldRequested()

    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.description: collapsed ? i18n("Folded, click to unfold") : i18n("Unfolded, click to fold")
    onClicked: header.foldRequested()
    Keys.onReturnPressed: header.foldRequested()
    Keys.onEnterPressed: header.foldRequested()

    HoverHandler {
        cursorShape: Qt.PointingHandCursor
    }

    Kirigami.Icon {
        objectName: "foldArrow"
        Layout.preferredWidth: Kirigami.Units.iconSizes.small
        Layout.preferredHeight: Kirigami.Units.iconSizes.small
        Layout.alignment: Qt.AlignVCenter
        source: header.collapsed ? (header.mirrored ? "go-previous" : "go-next") : "go-down"
        opacity: header.hovered || header.activeFocus ? 1 : 0.7
    }
}
