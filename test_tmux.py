"""Managed terminal ownership, attachment and cancellation regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
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

    def test_detached_navigation_opens_only_an_attachment(self):
        record = {"session": "$0"}
        with mock.patch.object(self.runtime, "select"), mock.patch.object(self.runtime, "clients", return_value=[]), \
                mock.patch("agent_eta_providers.executable", return_value="/usr/bin/konsole"), \
                mock.patch("agent_eta_providers.spawn") as spawn:
            self.assertEqual(self.runtime.attach(record), {"opened": True, "pids": []})
        self.assertEqual(spawn.call_args.args[0], ["/usr/bin/konsole", "--separate", "-e", "tmux", "-S", self.runtime.socket, "attach-session", "-t", "$0"])

    def test_existing_attachment_is_reused(self):
        record = {"session": "$0"}
        clients = [{"pid": 123, "tty": "/dev/pts/3", "session": "$0", "activity": 42}]
        with mock.patch.object(self.runtime, "select"), mock.patch.object(self.runtime, "clients", return_value=clients), \
                mock.patch.object(self.runtime, "tmux") as run, mock.patch.object(tmux, "lineage", return_value=[123, 100]):
            self.assertEqual(self.runtime.attach(record), {"opened": False, "pids": [123, 100]})
        run.assert_called_once_with("switch-client", "-c", "/dev/pts/3", "-t", "$0")

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


if __name__ == "__main__":
    unittest.main()
