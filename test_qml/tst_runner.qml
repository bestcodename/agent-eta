import QtQuick
import QtTest

import "../plasmoid/contents/ui" as UI

// Runner.qml through the real executable engine. A run that timed out answers with exit code 124,
// and its late answer never reaches the run after it.
Item {
    id: root

    property var results: []

    UI.Runner {
        id: runner
        timeout: 300
    }

    TestCase {
        name: "Runner"

        function init() {
            root.results = [];
        }

        function record(label) {
            return (code, stdout, stderr) => {
                root.results = root.results.concat([{label: label, code: code, stdout: stdout.trim(), stderr: stderr}]);
            };
        }

        function test_a_pending_run_is_not_started_twice() {
            verify(runner.run("sleep 0.2; echo once", record("first")));
            verify(!runner.run("sleep 0.2; echo once", record("second")));
            tryVerify(() => root.results.length === 1, 5000);
            compare(root.results[0].label, "first");
            compare(root.results[0].stdout, "once");
        }

        function test_a_late_answer_never_reaches_the_next_run() {
            const slow = "sleep 1; echo late";
            verify(runner.run(slow, record("slow")));
            wait(400);
            verify(runner.run(slow, record("again")));
            compare(root.results.length, 1);
            compare(root.results[0].label, "slow");
            compare(root.results[0].code, 124);
            tryVerify(() => root.results.length === 2, 5000);
            compare(root.results[1].label, "again");
            compare(root.results[1].stdout, "late");
            wait(1200);
            compare(root.results.length, 2);
        }
    }
}
