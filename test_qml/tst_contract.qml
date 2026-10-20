import QtQuick
import QtTest

import "../plasmoid/contents/ui" as UI
import "../plasmoid/contents/code/logic.mjs" as Logic

// The rows render what agent-eta's model decided, read from the contract fixtures test_model.py
// writes. Reading a local file through XMLHttpRequest needs QML_XHR_ALLOW_FILE_READ=1.
Item {
    id: root

    width: 400
    height: 300

    function act(action, session, task) {
    }

    function fixture(name) {
        const request = new XMLHttpRequest();
        request.open("GET", Qt.resolvedUrl("../test_fixtures/contract-v1/" + name + ".json"), false);
        request.send();
        return JSON.parse(request.responseText);
    }

    function texts(item) {
        let found = item.text !== undefined && typeof item.text === "string" ? [item.text] : [];
        for (let i = 0; i < item.children.length; i++) {
            found = found.concat(texts(item.children[i]));
        }
        if (item.contentItem && item.contentItem !== item) {
            found = found.concat(texts(item.contentItem));
        }
        return found;
    }

    Component {
        id: rowComponent

        UI.SessionRow {
            width: 400
        }
    }

    TestCase {
        name: "Contract"
        when: windowShown

        function row(session, now) {
            const item = createTemporaryObject(rowComponent, root, {session: session, now: now});
            verify(item);
            waitForRendering(item);
            return item;
        }

        function test_the_fixture_passes_the_contract_check() {
            compare(Logic.validateListing(root.fixture("mixed")).error, "");
        }

        function test_a_question_during_a_turn_reads_as_such() {
            const mixed = root.fixture("mixed");
            const [needs] = Logic.groupSessions(mixed, false, false);
            const item = row(needs.sessions[0], mixed.now);
            verify(root.texts(item).some(text => text.indexOf("working, question open (question)") >= 0),
                   root.texts(item).join(" | "));
        }

        function test_an_idle_owner_of_a_build_reads_working() {
            const mixed = root.fixture("mixed");
            const working = Logic.groupSessions(mixed, false, false)[1];
            const owner = working.sessions.find(session => session.key === "claude:1");
            const item = row(owner, mixed.now);
            const shown = root.texts(item);
            verify(shown.some(text => text.indexOf(" · working for ") >= 0), shown.join(" | "));
            verify(shown.indexOf("└ build") >= 0, shown.join(" | "));
        }
    }
}
