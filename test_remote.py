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


# A summary of a host with no session, as agent_eta_model.summary() writes it.
SUMMARY = {"waiting": 0, "working": 0, "idle": 0, "stopped": 0, "overdue": 0, "dormant": 0, "attention": 0,
           "live": 0, "progress_session_key": None, "light": "off", "badge_count": 0, "status": "passive"}


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
        self.assertEqual(merged["summary"]["headline"], "local")
        self.assertEqual((merged["summary"]["light"], merged["summary"]["badge_count"]), ("off", 0))
        self.assertEqual(merged["notification_signals"], [])

    def test_the_tray_summary_counts_every_fresh_host(self):
        local = listing([{"key": "claude:l", "agent": "claude", "tasks": [], "remaining": 600}],
                        summary=dict(SUMMARY, working=1, live=1, progress_session_key="claude:l",
                                     light="active", status="active"))
        other = dict(remote_listing(), summary=dict(SUMMARY, idle=1, working=1, dormant=1, live=2,
                                                    progress_session_key="claude:a"))
        other["sessions"][0]["remaining"] = 120
        cache = {"hosts": {"desktop": {"fetched_at": 990, "listing": other}}}
        found = remote.merge(local, cache, 1000)["summary"]
        self.assertEqual({name: found[name] for name in ("working", "idle", "dormant", "live")},
                         {"working": 2, "idle": 1, "dormant": 1, "live": 3})
        self.assertEqual((found["light"], found["badge_count"], found["status"]), ("caution", 1, "active"))
        self.assertEqual(found["progress_session_key"], "remote:desktop/claude:a")
        other["summary"]["waiting"] = 2
        found = remote.merge(local, cache, 1000)["summary"]
        self.assertEqual((found["light"], found["badge_count"], found["status"]), ("attention", 2, "attention"))

    def test_a_garbled_remote_summary_counts_as_empty(self):
        local = listing([{"key": "claude:l", "agent": "claude", "tasks": [], "remaining": 600}],
                        summary=dict(SUMMARY, working=1, live=1, progress_session_key="claude:l"))
        for garbled in ("x", {"idle": "3", "waiting": True, "live": -1, "progress_session_key": ["claude:a"]},
                        {"progress_session_key": "claude:gone"}):
            with self.subTest(garbled=garbled):
                cache = {"hosts": {"desktop": {"fetched_at": 990, "listing": dict(remote_listing(), summary=garbled)}}}
                found = remote.merge(local, cache, 1000)["summary"]
                self.assertEqual((found["light"], found["badge_count"], found["live"]), ("active", 0, 1))
                self.assertEqual(found["progress_session_key"], "claude:l")

    def test_remote_waits_and_overdue_runs_notify_with_their_host(self):
        local_wait = {"key": "waiting:claude:l", "kind": "waiting", "entity_key": "claude:l", "active": True,
                      "edge": "rising", "notify_on_new": True, "dedupe_key": "waiting:claude:l:5",
                      "message_params": {"name": "here"}}
        wait = dict(local_wait, key="waiting:claude:a", entity_key="claude:a", dedupe_key="waiting:claude:a:7",
                    message_params={"name": "there"})
        task = {"key": "overdue:task:t1", "kind": "overdue", "entity_key": "task:t1", "active": False,
                "edge": "rising", "notify_on_new": False, "dedupe_key": "overdue:task:t1:9", "message_params": None}
        reset = {"key": "reset:window:claude:300", "kind": "reset", "entity_key": "window:claude:300",
                 "active": False, "edge": "falling", "notify_on_new": False, "dedupe_key": "reset:x"}
        other = dict(remote_listing(), notification_signals=[wait, task, reset, "x", dict(wait, key=None)])
        merged = remote.merge(listing(notification_signals=[local_wait]),
                              {"hosts": {"desktop": {"fetched_at": 990, "listing": other}}}, 1000)
        signals = merged["notification_signals"]
        self.assertEqual([s["key"] for s in signals],
                         ["waiting:claude:l", "remote:desktop/waiting:claude:a", "remote:desktop/overdue:task:t1"])
        self.assertEqual(signals[0], local_wait)
        self.assertEqual((signals[1]["entity_key"], signals[1]["dedupe_key"], signals[1]["message_params"]),
                         ("remote:desktop/claude:a", "remote:desktop/waiting:claude:a:7",
                          {"name": "there", "host": "desktop"}))
        self.assertEqual(signals[2]["message_params"], {"host": "desktop"})
        self.assertEqual(wait["message_params"], {"name": "there"})

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

    def test_a_manual_viewer_accepts_the_cli_on_path_or_at_an_absolute_path(self):
        for cli in ("agent-eta", "/home/stefanr/.local/bin/agent-eta", "~/.local/bin/agent-eta"):
            with self.subTest(cli=cli), mock.patch.object(remote, "open_terminal") as open_terminal:
                path = self.proc / str(os.getpid())
                path.mkdir(exist_ok=True)
                argv = ["/usr/bin/ssh", "-t", "desktop", cli, "attach", "codex:t1"]
                (path / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
                self.assertEqual(remote.attach("desktop", "codex:t1", False, proc=str(self.proc)),
                                 {"opened": False, "pids": lineage(os.getpid())})
                open_terminal.assert_not_called()

    def test_a_manual_viewer_still_requires_the_same_ssh_host_command_and_source(self):
        changed = ((0, "/usr/bin/not-ssh"), (1, "-T"), (2, "other-host"),
                   (3, "/home/stefanr/.local/bin/not-agent-eta"), (4, "list"), (5, "codex:other"))
        candidates = []
        for index, value in changed:
            argv = list(self.argv)
            argv[index] = value
            candidates.append(argv)
        candidates.extend(([], self.argv[:3], self.argv + ["--json"]))
        for argv in candidates:
            with self.subTest(argv=argv):
                path = self.proc / str(os.getpid())
                path.mkdir(exist_ok=True)
                (path / "cmdline").write_bytes(b"".join(a.encode() + b"\0" for a in argv))
                self.assertIsNone(remote.viewer(self.argv, proc=str(self.proc)))

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
