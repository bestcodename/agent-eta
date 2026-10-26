"""Managed terminal ownership, attachment and cancellation regressions."""
import json
import os
from pathlib import Path
import pty
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import agent_eta_tmux as tmux


class RuntimeUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eta-tmux-")
        self.addCleanup(self.tmp.cleanup)
        self.runtime = tmux.Runtime(self.tmp.name)

    def test_exposed_or_symlinked_runtime_is_refused(self):
        root = Path(self.tmp.name) / "exposed"
        root.mkdir(mode=0o755)
        with self.assertRaisesRegex(tmux.TmuxError, "0700"):
            tmux.Runtime(root)
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.runtime.root, target_is_directory=True)
        with self.assertRaises(tmux.TmuxError):
            tmux.Runtime(link)

    def test_an_existing_file_is_reported_as_a_runtime_error(self):
        path = Path(self.tmp.name) / "file"
        path.write_text("existing")
        with self.assertRaisesRegex(tmux.TmuxError, "cannot prepare"):
            tmux.Runtime(path)

    def test_a_foreign_server_is_refused_before_any_window_is_created(self):
        def query(*args, **kwargs):
            output = "$0\n" if args[0] == "list-sessions" else "123\n"
            return subprocess.CompletedProcess([], 0, output, "")
        with mock.patch.object(self.runtime, "tmux", side_effect=query) as run, \
                mock.patch.object(tmux, "proc_start", return_value="start"), \
                mock.patch.object(tmux, "cgroup", return_value="/unrelated.service"), \
                self.assertRaisesRegex(tmux.TmuxError, "outside its managed service"):
            self.runtime.start(["sleep", "1"], self.tmp.name)
        self.assertFalse(any(call.args[0] == "new-window" for call in run.call_args_list))

    def test_launcher_clears_inherited_markers_then_applies_selected_account(self):
        command = [sys.executable, "-c", "import os,sys,json;print(json.dumps([sys.argv[1],os.getenv('CLAUDECODE'),os.getenv('CODEX_THREAD_ID'),os.getenv('INVOCATION_ID'),os.getenv('CLAUDE_CONFIG_DIR'),os.getenv('TERM')]))", "spaces ' $(touch never) %s"]
        script = Path(self.tmp.name) / "launch.sh"
        script.write_text(tmux.launcher(command, {"CLAUDE_CONFIG_DIR": "/chosen account"}))
        env = dict(os.environ, CLAUDECODE="old", CODEX_THREAD_ID="old", INVOCATION_ID="old", TERM="tmux-256color")
        for _ in range(2):
            result = subprocess.run(["sh", str(script)], env=env, check=True, text=True, capture_output=True)
            self.assertEqual(json.loads(result.stdout), [command[-1], None, None, None, "/chosen account", "tmux-256color"])
        self.assertFalse((Path(self.tmp.name) / "never").exists())

    def test_stale_agent_or_server_identity_cannot_supply_a_target(self):
        with mock.patch.object(tmux, "proc_start", return_value="new"):
            self.assertIsNone(self.runtime.find(123, "old"))
            self.assertIsNone(self.runtime.pane({"server_pid": 123, "server_start": "old"}))

    def test_an_unconfirmed_launcher_exit_does_not_claim_cancellation(self):
        record = {"id": "a" * 32, "scope": "agent-eta-agent-a.scope", "pane": "%1", "pane_pid": 123, "pane_start": "old"}
        self.runtime.write(record)
        with mock.patch.object(self.runtime, "pane", return_value=record), \
                mock.patch.object(self.runtime, "tmux"), mock.patch.object(tmux, "proc_start", return_value="old"), \
                mock.patch.object(tmux.os, "getpgid", return_value=123), mock.patch.object(tmux.os, "killpg"), \
                mock.patch.object(tmux.time, "monotonic", side_effect=[0, 10]), \
                mock.patch.object(self.runtime, "run") as run:
            self.assertFalse(self.runtime.stop(record["id"]))
        run.assert_called_once_with(["systemctl", "--user", "kill", "--signal=SIGKILL", "--kill-whom=all", record["scope"]], check=False)

    def test_unidentified_launcher_intent_cannot_confirm_cancellation(self):
        record = {"id": "b" * 32, "scope": "agent-eta-agent-b.scope", "target": "agents:pending"}
        self.runtime.write(record)
        with mock.patch.object(self.runtime, "pane", return_value=None), mock.patch.object(self.runtime, "run"):
            self.assertFalse(self.runtime.stop(record["id"]))

    def test_an_orphaned_launcher_group_keeps_cancellation_unconfirmed(self):
        record = {"id": "c" * 32, "scope": "agent-eta-agent-c.scope", "pane_pid": 123, "pane_start": "old"}
        self.runtime.write(record)
        with mock.patch.object(self.runtime, "pane", return_value=None), \
                mock.patch.object(tmux, "proc_start", return_value=None), \
                mock.patch.object(tmux, "group_alive", return_value=True), \
                mock.patch.object(tmux.time, "monotonic", side_effect=[0, 10]), \
                mock.patch.object(self.runtime, "run"):
            self.assertFalse(self.runtime.stop(record["id"]))

    PANE = {"session": "$0", "window": "@1", "pane": "%1", "pane_pid": 123, "pane_start": "start"}

    def test_detached_navigation_opens_only_an_attachment(self):
        with mock.patch.object(self.runtime, "pane", return_value=self.PANE), \
                mock.patch.object(self.runtime, "clients", return_value=[]), \
                mock.patch.object(tmux.uuid, "uuid4", return_value=mock.Mock(hex="f" * 32)), \
                mock.patch("agent_eta_providers.executable", return_value="/usr/bin/konsole"), \
                mock.patch("agent_eta_providers.spawn") as spawn:
            self.assertEqual(self.runtime.attach({}), {"opened": True, "pids": []})
        name = "view-" + "f" * 12
        self.assertEqual(spawn.call_args.args[0], [
            "/usr/bin/konsole", "--separate", "-e", "tmux", "-f", tmux.CONFIG, "-S", self.runtime.socket,
            "new-session", "-t", "$0", "-s", name, ";", "set-option", "-t", name, "destroy-unattached", "on", ";",
            "select-window", "-t", name + ":@1"])

    def test_existing_attachment_is_reused(self):
        clients = [{"pid": 123, "tty": "/dev/pts/3", "session": "$4", "window": "@1", "activity": 42}]
        with mock.patch.object(self.runtime, "pane", return_value=self.PANE), \
                mock.patch.object(self.runtime, "clients", return_value=clients), \
                mock.patch.object(self.runtime, "tmux") as run, mock.patch.object(tmux, "lineage", return_value=[123, 100]):
            self.assertEqual(self.runtime.attach({}), {"opened": False, "pids": [123, 100]})
        run.assert_not_called()

    def test_a_viewer_of_another_agent_is_left_alone(self):
        clients = [{"pid": 123, "tty": "/dev/pts/3", "session": "$4", "window": "@2", "activity": 42}]
        with mock.patch.object(self.runtime, "pane", return_value=self.PANE), \
                mock.patch.object(self.runtime, "clients", return_value=clients), \
                mock.patch.object(self.runtime, "tmux") as run, \
                mock.patch("agent_eta_providers.executable", return_value="/usr/bin/konsole"), \
                mock.patch("agent_eta_providers.spawn") as spawn:
            self.assertEqual(self.runtime.attach({}), {"opened": True, "pids": []})
        run.assert_not_called()
        spawn.assert_called_once()

    def test_interactive_attach_inside_tmux_switches_only_the_calling_viewer(self):
        with mock.patch.object(self.runtime, "pane", return_value=self.PANE), \
                mock.patch.dict(os.environ, {"TMUX": self.runtime.socket + ",1,0"}), \
                mock.patch.object(self.runtime, "tmux", return_value=subprocess.CompletedProcess([], 0, "$5\n", "")) as run:
            self.assertEqual(self.runtime.attach({}, interactive=True), {"opened": False, "pids": []})
        self.assertEqual(run.call_args_list, [mock.call("display-message", "-p", "#{session_id}"),
                                              mock.call("select-window", "-t", "$5:@1")])

    def test_navigation_to_an_ended_terminal_is_refused(self):
        with mock.patch.object(self.runtime, "pane", return_value=None), \
                self.assertRaisesRegex(tmux.TmuxError, "has ended"):
            self.runtime.attach({})

    def test_account_migration_adapter_reuses_native_launch_script(self):
        tabs = Path(self.tmp.name) / "tabs.txt"
        tabs.write_text("title: native;; workdir: /project with spaces;; command: /bin/sh /private/launch.sh\n")
        with mock.patch.object(tmux, "Runtime") as runtime:
            tmux.account_tabs(tabs)
        call = runtime.return_value.start.call_args
        self.assertEqual(call.args, (["/bin/sh", "/private/launch.sh"], "/project with spaces"))
        self.assertRegex(call.kwargs["identifier"], r"^[a-f0-9]{32}$")
        runtime.return_value.attach.assert_called_once()

    def test_account_adapter_confirms_launch_failure_cleanup(self):
        tabs = Path(self.tmp.name) / "tabs.txt"
        tabs.write_text("workdir: /project;; command: /bin/sh /private/launch.sh\n")
        with mock.patch.object(tmux, "Runtime") as runtime:
            runtime.return_value.start.side_effect = tmux.TmuxError("launch failed")
            runtime.return_value.stop.return_value = False
            with self.assertRaisesRegex(tmux.TmuxError, "cleanup is unconfirmed"):
                tmux.account_tabs(tabs)
        runtime.return_value.stop.assert_called_once()
        runtime.return_value.attach.assert_not_called()


@unittest.skipUnless(shutil.which("tmux"), "tmux is required")
class ServerUnit(unittest.TestCase):
    """The private configuration and grouped viewers against a real tmux server, without systemd."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eta-tmux-")
        self.addCleanup(self.tmp.cleanup)
        self.runtime = tmux.Runtime(self.tmp.name)
        self.env = {name: value for name, value in os.environ.items() if name not in ("TMUX", "TMUX_PANE")}
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmux("new-session", "-d", "-s", "agents", "-n", "a", "-c", self.tmp.name, "--", "sleep", "60")
        self.addCleanup(self.tmux, "kill-server")
        self.tmux("new-window", "-d", "-t", "agents:", "-n", "b", "-c", self.tmp.name, "--", "sleep", "60")
        pid = int(self.tmux("display-message", "-p", "#{pid}"))
        self.a, self.b = ({"pane": pane, "server_pid": pid, "server_start": tmux.proc_start(pid)}
                          for pane in self.tmux("list-panes", "-s", "-t", "agents", "-F", "#{pane_id}").split())

    def tmux(self, *args):
        return self.runtime.tmux(*args).stdout.strip()

    def window(self, record):
        return self.runtime.pane(record)["window"]

    def until(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            self.assertLess(time.monotonic(), deadline, "tmux did not reach the expected state")
            time.sleep(.05)

    def view(self, record):
        child, fd = pty.fork()
        if child == 0:
            os.environ["TERM"] = "xterm-256color"
            argv = self.runtime.viewer(self.runtime.pane(record))
            try:
                os.execvp(argv[0], argv)
            finally:
                os._exit(127)
        self.until(self.runtime.clients)
        return child, fd

    def close(self, child, fd):
        os.kill(child, signal.SIGTERM)
        os.waitpid(child, 0)
        os.close(fd)

    def test_the_private_configuration_enables_mouse_scrollback_and_titles(self):
        self.assertEqual(self.tmux("show-options", "-gv", "mouse"), "on")
        self.assertEqual(self.tmux("display-message", "-p", "-t", self.a["pane"], "#{history_limit}"), "50000")
        self.tmux("select-pane", "-t", self.a["pane"], "-T", "✳ Plan")
        self.assertIn("✳ Plan", self.tmux("display-message", "-p", "-t", self.a["pane"], "#{E:window-status-format}"))
        self.assertIn(Path(self.tmp.name).name,
                      self.tmux("display-message", "-p", "-t", self.b["pane"], "#{E:window-status-format}"))

    def test_a_viewer_keeps_its_own_window_and_disappears_when_closed(self):
        child, fd = self.view(self.b)
        try:
            self.assertEqual([c["window"] for c in self.runtime.clients()], [self.window(self.b)])
            self.assertEqual(self.tmux("display-message", "-p", "-t", "agents", "#{window_id}"), self.window(self.a))
            self.assertEqual(self.runtime.attach(self.b)["opened"], False)
            with mock.patch("agent_eta_providers.executable", return_value="/usr/bin/konsole"), \
                    mock.patch("agent_eta_providers.spawn") as spawn:
                self.assertEqual(self.runtime.attach(self.a), {"opened": True, "pids": []})
            spawn.assert_called_once()
        finally:
            self.close(child, fd)
        self.until(lambda: self.tmux("list-sessions", "-F", "#{session_name}") == "agents")

    def test_a_handoff_moves_each_view_of_its_source(self):
        child, fd = self.view(self.a)
        try:
            self.runtime.follow(self.a, self.b)
            self.assertEqual([c["window"] for c in self.runtime.clients()], [self.window(self.b)])
            self.assertEqual(self.tmux("display-message", "-p", "-t", "agents", "#{window_id}"), self.window(self.b))
        finally:
            self.close(child, fd)


if __name__ == "__main__":
    unittest.main()
