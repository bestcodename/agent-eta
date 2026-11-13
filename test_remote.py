"""Tests for agent_eta_remote: the merge into the listing, the SSH fetch and the viewer lookup.

Run with:  python3 -m unittest test_remote -v
A fake `ssh` first on PATH stands in for the remote host, so no test opens a connection.
"""

import copy
import json
import os
import shutil
import pathlib
import tempfile
import time
import unittest
from unittest import mock

import agent_eta_accounts as accounts
import agent_eta_handoff as handoff
import agent_eta_remote as remote
from agent_eta_tmux import lineage

FAKE_SSH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_SSH_LOG"
case "$FAKE_SSH_MODE" in
    listing) cat "$FAKE_SSH_LISTING" ;;
    down) exit 255 ;;
    slow) exec sleep 5 ;;
    old) echo "agent-eta: error: unrecognized arguments: --local" >&2; exit 2 ;;
    garbage) echo "not json" ;;
    fail) echo "secret-output" >&2; exit 3 ;;
esac
"""


def listing(sessions=(), tasks=(), sections=None, **fields):
    data = {"schema_version": 1, "now": 1000, "summary": {"headline": "local"}, "notification_signals": [],
            "usage": [], "accounts": [], "sessions": list(sessions), "tasks": list(tasks),
            "sections": sections if sections is not None else [{"index": 0, "title": "Needs you", "session_keys": []},
                                                              {"index": 1, "title": "Working", "session_keys": []}]}
    data.update(fields)
    return data


def remote_listing():
    managed = {"key": "claude:a", "agent": "claude", "id": "a", "tasks": ["t1"], "navigation": {"kind": "tmux"},
               "cwd": "/work/shop", "project_root": "/work/shop", "project_name": "shop", "pids": [10, 1],
               "handoff": {"available": True, "reason": None, "status": None, "targets": ["codex"]}}
    desktop = {"key": "codex:b", "agent": "codex", "id": "b", "tasks": [],
               "navigation": {"kind": "url", "url": "codex://threads/b"}, "pids": []}
    plain = {"key": "claude:c", "agent": "claude", "id": "c", "tasks": [], "pids": [12]}
    task = {"id": "t1", "key": "task:t1", "session": {"id": "a"}, "source": "add", "label": "CI"}
    return listing([managed, desktop, plain], [task],
                   [{"index": 1, "title": "Working", "session_keys": ["claude:a", "codex:b"]},
                    {"index": 5, "title": "Dormant", "session_keys": ["claude:c"]}],
                   summary={"headline": "remote"})


class MergeTest(unittest.TestCase):
    def test_fresh_host_rows_are_prefixed_and_stripped_of_local_actions(self):
        local = listing([{"key": "claude:l", "agent": "claude", "tasks": []}],
                        sections=[{"index": 0, "title": "Needs you", "session_keys": []},
                                  {"index": 1, "title": "Working", "session_keys": ["claude:l"]}])
        before = copy.deepcopy(local)
        merged = remote.merge(local, {"hosts": {"desktop": {"fetched_at": 990, "listing": remote_listing()}}}, 1000)
        self.assertEqual(local, before)
        rows = {s["key"]: s for s in merged["sessions"]}
        managed = rows["remote:desktop/claude:a"]
        self.assertEqual(managed["navigation"], {"kind": "tmux", "host": "desktop"})
        self.assertEqual((managed["host"], managed["cwd"], managed["project_root"], managed["pids"]),
                         ("desktop", None, None, []))
        self.assertEqual(managed["project_name"], "shop")
        self.assertEqual(managed["tasks"], ["remote:desktop/t1"])
        self.assertEqual(managed["handoff"], {"available": False, "reason": "runs on desktop", "status": None, "targets": []})
        for key in ("remote:desktop/codex:b", "remote:desktop/claude:c"):
            self.assertEqual(rows[key]["navigation"], {"kind": "unavailable", "reason": "Runs on desktop"})
        self.assertEqual(merged["tasks"], [{"id": "remote:desktop/t1", "key": "remote:desktop/task:t1",
                                            "session": {"id": "a"}, "source": "remote", "label": "CI"}])
        self.assertEqual([(s["index"], s["session_keys"]) for s in merged["sections"]],
                         [(0, []), (1, ["claude:l", "remote:desktop/claude:a", "remote:desktop/codex:b"]),
                          (5, ["remote:desktop/claude:c"])])
        self.assertEqual(merged["summary"], {"headline": "local"})

    def test_stale_invalid_and_unknown_hosts_are_left_out(self):
        local = listing()
        cache = {"hosts": {
            "stale": {"fetched_at": 1000 - remote.FRESH_SECONDS - 1, "listing": remote_listing()},
            "future": {"fetched_at": 2000, "listing": remote_listing()},
            "never": {"error": "unreachable"},
            "invalid": {"fetched_at": 1000, "listing": dict(remote_listing(), schema_version=2)},
            "broken": {"fetched_at": 1000, "listing": dict(remote_listing(), sessions=[{"agent": "claude"}])},
            "-oProxyCommand=x": {"fetched_at": 1000, "listing": remote_listing()},
        }}
        self.assertEqual(remote.merge(local, cache, 1000), local)
        self.assertEqual(remote.merge(local, {"hosts": []}, 1000), local)


class HostTest(unittest.TestCase):
    def test_only_host_names_and_aliases_pass(self):
        for host in ("desktop", "stefan-notebook.local", "10.0.0.2", "h_1"):
            self.assertEqual(remote.valid_host(host), host)
        for host in ("-oProxyCommand=x", "a b", "", None, "host;rm", "~x"):
            with self.subTest(host=host), self.assertRaises(remote.RemoteError):
                remote.valid_host(host)


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agent-eta-remote-")
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        ssh = bin_dir / "ssh"
        ssh.write_text(FAKE_SSH)
        ssh.chmod(0o755)
        self.log = self.root / "ssh.log"
        self.listing = self.root / "listing.json"
        self.listing.write_text(json.dumps(remote_listing()))
        patcher = mock.patch.dict(os.environ, {
            "AGENT_ETA_DIR": str(self.root / "state"), "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
            "FAKE_SSH_LOG": str(self.log), "FAKE_SSH_LISTING": str(self.listing), "FAKE_SSH_MODE": "listing"})
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("AGENT_ETA_CONFIG", "AGENT_ETA_CACHE_DIR", "AGENT_ETA_NO_REFRESH"):
            os.environ.pop(name, None)
        self.store = accounts.AccountStore()
        self.store.configure(lambda data: data.update(remote_hosts=["desktop"]))

    def entry(self):
        return remote.read_cache(self.store)["hosts"]["desktop"]

    def test_a_listing_is_fetched_with_batch_mode_and_the_local_guard(self):
        self.assertTrue(remote.refresh(self.store))
        self.assertEqual(self.entry()["listing"], remote_listing())
        self.assertIsNone(self.entry()["error"])
        self.assertLessEqual(abs(self.entry()["fetched_at"] - time.time()), 5)
        self.assertEqual(self.log.read_text(), "-T -o BatchMode=yes -o ConnectTimeout=3 desktop "
                                               "~/.local/bin/agent-eta list --json --all --local\n")

    def test_failures_are_named_without_remote_output_and_keep_the_last_listing(self):
        remote.refresh(self.store)
        fetched = self.entry()["fetched_at"]
        for mode, error in (("down", "unreachable"), ("old", "agent-eta on desktop is too old"),
                            ("garbage", "invalid listing"), ("fail", "exit 3")):
            with self.subTest(mode=mode), mock.patch.dict(os.environ, FAKE_SSH_MODE=mode):
                remote.refresh(self.store)
                self.assertEqual(self.entry()["error"], error)
                self.assertEqual((self.entry()["fetched_at"], self.entry()["listing"]), (fetched, remote_listing()))
        self.assertNotIn("secret-output", json.dumps(remote.read_cache(self.store)))

    def test_a_hanging_host_times_out_as_unreachable(self):
        with mock.patch.dict(os.environ, FAKE_SSH_MODE="slow"), mock.patch.object(remote, "FETCH_TIMEOUT", 1):
            remote.refresh(self.store)
        self.assertEqual(self.entry()["error"], "unreachable")

    def test_a_removed_host_leaves_the_cache(self):
        remote.refresh(self.store)
        self.store.configure(lambda data: data.update(remote_hosts=[]))
        remote.refresh(self.store)
        self.assertEqual(remote.read_cache(self.store)["hosts"], {})

    def test_the_background_fetch_is_throttled_and_needs_hosts(self):
        with mock.patch.object(accounts.subprocess, "Popen") as popen:
            self.assertTrue(remote.maybe_refresh(self.store, "/fake/agent-eta", 1000))
            self.assertFalse(remote.maybe_refresh(self.store, "/fake/agent-eta", 1000 + remote.THROTTLE_SECONDS - 1))
            self.assertTrue(remote.maybe_refresh(self.store, "/fake/agent-eta", 1000 + remote.THROTTLE_SECONDS))
            with mock.patch.dict(os.environ, AGENT_ETA_NO_REFRESH="1"):
                self.assertFalse(remote.maybe_refresh(self.store, "/fake/agent-eta", 5000))
            self.store.configure(lambda data: data.update(remote_hosts=[]))
            self.assertFalse(remote.maybe_refresh(self.store, "/fake/agent-eta", 9000))
        self.assertEqual(popen.call_count, 2)
        self.assertEqual(popen.call_args.args[0][-4:-2], ["remote", "refresh"])

    def test_a_worker_with_a_foreign_descriptor_is_refused(self):
        fd = os.open(self.root / "other.lock", os.O_CREAT | os.O_RDWR, 0o600)
        remote.lock_path(self.store).parent.mkdir(parents=True, exist_ok=True)
        remote.lock_path(self.store).touch()
        with self.assertRaises(accounts.AccountError):
            remote.refresh(self.store, fd)


class AttachTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agent-eta-attach-")
        self.addCleanup(tmp.cleanup)
        self.root = pathlib.Path(tmp.name)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.recorded = self.root / "terminal.args"
        terminal = self.root / "terminal"
        terminal.write_text('#!/bin/sh\nprintf "%%s\\n" "$@" > %s\n' % self.recorded)
        terminal.chmod(0o755)
        # A runner that drops systemd-run's own options and runs the terminal directly.
        runner = self.root / "systemd-run"
        runner.write_text('#!/bin/sh\nwhile [ "$1" != "--" ]; do shift; done\nshift\nexec "$@"\n')
        runner.chmod(0o755)
        patcher = mock.patch.dict(os.environ, AGENT_ETA_TERMINAL_BIN=str(terminal), AGENT_ETA_SYSTEMD_RUN_BIN=str(runner))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.argv = ["ssh", "-t", "desktop", "~/.local/bin/agent-eta", "attach", "codex:t1"]

    def fake_process(self, pid, argv):
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))

    def test_a_running_viewer_is_focused_through_its_lineage(self):
        self.fake_process(os.getpid(), self.argv)
        self.fake_process(1, self.argv[:-1] + ["codex:other"])
        result = remote.attach("desktop", "codex:t1", False, proc=str(self.proc))
        self.assertEqual(result, {"opened": False, "pids": lineage(os.getpid())})
        self.assertFalse(self.recorded.exists())

    def test_a_viewer_whose_terminal_resolved_ssh_through_path_is_found(self):
        self.fake_process(os.getpid(), ["/usr/bin/ssh"] + self.argv[1:])
        self.assertEqual(remote.attach("desktop", "codex:t1", False, proc=str(self.proc))["opened"], False)

    def open_viewer(self, argv):
        """A terminal whose ssh shows up as a process after its start returned."""
        self.opened = argv
        self.fake_process(os.getpid(), argv)

    def test_without_a_viewer_a_terminal_runs_the_remote_attach(self):
        self.fake_process(1, self.argv[:-1] + ["codex:other"])
        with mock.patch.object(remote, "open_terminal", side_effect=self.open_viewer), \
                mock.patch.object(remote, "REMOTE_SETTLE", 0):
            result = remote.attach("desktop", "codex:t1", False, proc=str(self.proc))
        self.assertEqual(result, {"opened": True, "pids": lineage(os.getpid())})
        self.assertEqual(self.opened, self.argv)

    def test_a_remote_attach_that_never_shows_or_ends_at_once_is_an_error(self):
        def gone(seconds):
            shutil.rmtree(self.proc / str(os.getpid()), ignore_errors=True)

        cases = (("never shows", lambda argv: None, None),
                 ("ends at once", self.open_viewer, gone))
        for name, opener, sleep in cases:
            with self.subTest(name), mock.patch.object(remote, "open_terminal", side_effect=opener), \
                    mock.patch.object(remote, "VIEWER_TIMEOUT", 0.2), \
                    mock.patch.object(remote.time, "sleep", side_effect=sleep), \
                    self.assertRaisesRegex(remote.RemoteError, "ended at once"):
                remote.attach("desktop", "codex:t1", False, proc=str(self.proc))

    def test_source_and_host_are_validated_before_ssh_sees_them(self):
        with self.assertRaises(handoff.HandoffError):
            remote.attach("desktop", "codex:t1; rm -rf ~", False, proc=str(self.proc))
        with self.assertRaises(remote.RemoteError):
            remote.attach("-oProxyCommand=x", "codex:t1", False, proc=str(self.proc))
        self.assertFalse(self.recorded.exists())


if __name__ == "__main__":
    unittest.main()
