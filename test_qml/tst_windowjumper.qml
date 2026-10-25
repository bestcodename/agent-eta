import QtQuick
import QtTest

import org.kde.taskmanager

import "../plasmoid/contents/ui" as UI

// WindowJumper against the stub TasksModel and a launcher that records its commands. The launcher
// answers only when a test calls `answer`, the way the executable engine answers later.
TestCase {
    id: suite
    name: "WindowJumper"
    property var urls: []

    QtObject {
        id: launcher

        property var commands: []
        property var callbacks: []

        function run(command, callback) {
            commands = commands.concat([command]);
            callbacks = callbacks.concat([callback]);
            return true;
        }

        function answer(code, stdout) {
            callbacks[callbacks.length - 1](code, stdout, "");
        }
    }

    UI.WindowJumper {
        id: jumper
        launcher: launcher
        command: "agent-eta"
        openUrl: url => {
            suite.urls = suite.urls.concat([url]);
            return true;
        }
    }

    // Konsole 58086 with two windows, the way a tab dragged out of the SEC window leaves it.
    readonly property var konsole: [
        {pid: 58086, title: "sec — Konsole"},
        {pid: 7, title: "Panel", isWindow: false},
        {pid: 58086, title: "Handoff 3d — Konsole"},
    ]
    readonly property var session: ({agent: "claude", pids: [58107, 58086], project_name: "stefanr"})

    function init() {
        TaskFixture.reset();
        TaskFixture.windows = konsole;
        launcher.commands = [];
        launcher.callbacks = [];
        urls = [];
    }

    function test_konsole_tab_titles_pick_the_window() {
        verify(jumper.jump(session));
        compare(launcher.commands, ["agent-eta tab 58107 58086"]);
        compare(TaskFixture.activated, [], "nothing is raised before the tab call answers");
        launcher.answer(0, '{"window": "/Windows/3", "titles": ["Handoff 3d", "Handoff 3d"]}\n');
        compare(TaskFixture.activated, [2]);
    }

    function test_a_failed_tab_call_falls_back_to_the_first_window() {
        verify(jumper.jump(session));
        launcher.answer(1, "");
        compare(TaskFixture.activated, [0]);
    }

    function test_a_session_without_a_window_neither_calls_nor_raises() {
        const lost = {agent: "claude", pids: [11, 12], project_name: "x"};
        verify(!jumper.canJump(lost));
        verify(!jumper.jump(lost));
        compare(launcher.commands, []);
        compare(TaskFixture.activated, []);
    }

    function test_phpstorm_windows_are_picked_by_project_without_a_tab_answer() {
        TaskFixture.windows = [{pid: 55593, title: "sdwa5 – checkout.php"}, {pid: 55593, title: "ai – TODO.md"}];
        verify(jumper.jump({agent: "claude", pids: [791258, 55593], project_name: "ai"}));
        launcher.answer(1, "");
        compare(TaskFixture.activated, [1]);
    }

    function test_codex_cli_selects_its_tab_and_window_without_opening_the_app() {
        const cli = {agent: "codex", navigation: {kind: "window"}, id: "t1", pids: session.pids};
        verify(jumper.canJump(cli));
        verify(jumper.jump(cli));
        compare(launcher.commands, ["agent-eta tab 58107 58086"]);
        launcher.answer(0, '{"titles": ["Handoff 3d"]}');
        compare(TaskFixture.activated, [2]);
        compare(urls, []);
    }

    function test_codex_cli_without_a_window_does_not_open_a_desktop_thread() {
        const cli = {agent: "codex", navigation: {kind: "window"}, id: "t1", pids: [11, 12]};
        verify(!jumper.canJump(cli));
        verify(!jumper.jump(cli));
        verify(jumper.unavailableReason(cli).indexOf("window") >= 0);
        compare(urls, []);
        compare(launcher.commands, []);
        compare(TaskFixture.activated, []);
    }

    function test_desktop_and_older_codex_rows_open_their_thread_links() {
        for (const navigation of [{kind: "url", url: "codex://threads/t%2F1"}, undefined]) {
            const desktop = {agent: "codex", navigation: navigation, id: "t/1", pids: session.pids};
            verify(jumper.canJump(desktop));
            verify(jumper.jump(desktop));
        }
        compare(urls, ["codex://threads/t%2F1", "codex://threads/t%2F1"]);
        verify(!jumper.canJump({agent: "codex"}));
        compare(launcher.commands, []);
        compare(TaskFixture.activated, []);
    }

    function test_unavailable_or_unknown_targets_never_fall_back_to_a_desktop_link() {
        for (const navigation of [{kind: "unavailable", reason: "No linked terminal."},
                                  {kind: "future-kind"}, {kind: "url", url: ""}, null]) {
            const unknown = {agent: "codex", navigation: navigation, id: "t1", pids: session.pids};
            verify(!jumper.canJump(unknown));
            verify(!jumper.jump(unknown));
            verify(jumper.unavailableReason(unknown).length > 0);
        }
        compare(jumper.unavailableReason({agent: "codex", navigation: {kind: "unavailable", reason: "No linked terminal."}}),
                "No linked terminal.");
        compare(urls, []);
        compare(launcher.commands, []);
        compare(TaskFixture.activated, []);
    }

    function test_dsh_opens_its_web_link_and_runs_nothing() {
        verify(!jumper.canJump({agent: "dsh"}));
        verify(!jumper.jump({agent: "dsh"}));
        verify(jumper.canJump({agent: "dsh", web_url: "http://127.0.0.1:3080/"}));
        verify(jumper.jump({agent: "dsh", web_url: "http://127.0.0.1:3080/"}));
        compare(urls, ["http://127.0.0.1:3080/"]);
        compare(launcher.commands, []);
        compare(TaskFixture.activated, []);
    }
}
