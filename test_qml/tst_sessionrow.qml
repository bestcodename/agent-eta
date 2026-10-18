import QtQuick
import QtTest

import "../plasmoid/contents/ui" as UI

// SessionRow with the real Plasma components, clicked through QtTest instead of xdotool. The row
// calls `root.act` from the context it was created in, which here is this file.
Item {
    id: root

    width: 400
    height: 300

    property var acts: []
    property var menus: []

    function act(action, session, task) {
        acts = acts.concat([{action: action, session: session, task: task}]);
    }

    Component {
        id: rowComponent

        UI.SessionRow {
            width: 400
            now: Date.now() / 1000
            onMenuRequested: (session, task, item, x, y) => {
                root.menus = root.menus.concat([{session: session, task: task}]);
            }
        }
    }

    TestCase {
        name: "SessionRow"
        when: windowShown

        readonly property var session: ({
            id: "34f80958", agent: "claude", state: "working", title: "merged todo list", pids: [58107, 58086],
            taskItems: [{id: "b1", label: "Run the test suite", state: "working"}],
        })

        function init() {
            root.acts = [];
            root.menus = [];
        }

        function row(data) {
            const item = createTemporaryObject(rowComponent, root, {session: data});
            verify(item);
            waitForRendering(item);
            return item;
        }

        function test_a_click_jumps_to_the_session() {
            const item = row(session);
            mouseClick(item, 5, 5);
            compare(root.acts.length, 1);
            compare(root.acts[0].action, "jump");
            compare(root.acts[0].session.id, "34f80958");
            compare(root.acts[0].task, null);
        }

        function test_hovering_marks_the_row() {
            const item = row(session);
            mouseMove(item, 5, 5);
            tryVerify(() => item.hovered);
        }

        function test_a_right_click_opens_the_menu_without_jumping() {
            const item = row(session);
            mouseClick(item, 5, 5, Qt.RightButton);
            compare(root.menus.length, 1);
            compare(root.menus[0].session.id, "34f80958");
            compare(root.menus[0].task, null);
            compare(root.acts, []);
        }

        function test_a_right_click_on_a_task_offers_that_task() {
            const item = row(session);
            mouseClick(item, 40, item.height - 4, Qt.RightButton);
            compare(root.menus.length, 1);
            compare(root.menus[0].task.id, "b1");
        }

        function test_a_session_without_an_id_offers_its_only_task_anywhere() {
            const item = row({agent: "eta", state: "working", title: "Deploy", taskItems: [{id: "a7", label: "Deploy"}]});
            mouseClick(item, 5, 5, Qt.RightButton);
            compare(root.menus[0].task.id, "a7");
        }
    }
}
