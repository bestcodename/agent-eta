#!/usr/bin/env python3
"""Tests for agent-eta.

Run with:  python3 -m unittest discover -s scripts/agent-eta -v

Every test works in its own state directory and its own fake Claude Code and Codex
homes, so nothing here touches /tmp/agent-eta-<uid> or a live session registry. The hook
tests start a real process with fd 1 on a fake tasks/<id>.output, because finding that
process is the part a payload alone cannot prove.
"""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest

_SRC = pathlib.Path(__file__).with_name("agent-eta")
_spec = importlib.util.spec_from_loader(
    "agent_eta",
    importlib.machinery.SourceFileLoader("agent_eta", str(_SRC)),
)
eta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eta)

AGENT_VARS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SANDBOX",
              "CODEX_SANDBOX_NETWORK_DISABLED", "AGENT_ETA_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME")


class Durations(unittest.TestCase):
    def test_eta_arguments(self):
        for text, seconds in (("7200", 7200), ("25m", 1500), ("1h30m", 5400), ("1h 30m", 5400),
                              ("1h05", 3900), ("90s", 90), ("2d", 172800), ("ca. 10 minutes", 600),
                              ("1 Stunde 30 Minuten", 5400), ("1 Stunde und 30 Minuten", 5400),
                              ("2 Std.", 7200), ("ETA 25m", 1500), ("1.5h", 5400)):
            with self.subTest(text=text):
                self.assertEqual(eta.parse_eta_arg(text), seconds)

    def test_invalid_eta_arguments(self):
        for text in ("bogus", "10 apples", "", "10m and soon", "-5m"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    eta.parse_eta_arg(text)

    def test_eta_in_free_text(self):
        for text, seconds in (("Run the test suite (ETA ca. 10 minutes)", 600),
                              ("composer test  # ETA ca. 1 Stunde und 30 Minuten", 5400),
                              ("Warten, ungefähr 45 Minuten", 2700),
                              ("Deploy (ETA: 25m)", 1500),
                              ("Build ETA ~3 min", 180),
                              ("Run the test suite", None),
                              ("Copy ca. 300 files", None),
                              ("", None)):
            with self.subTest(text=text):
                found = eta.find_eta(text)
                self.assertEqual(found[0] if found else None, seconds)

    def test_labels_lose_their_eta(self):
        self.assertEqual(eta.strip_eta("Run the test suite (ETA ca. 10 minutes)"), "Run the test suite")
        self.assertEqual(eta.strip_eta("Run the test suite - ETA 10m"), "Run the test suite")
        self.assertEqual(eta.command_label("sleep 120  # ETA ca. 2 minutes"), "sleep 120")
        self.assertEqual(eta.command_label("grep -c '#' file"), "grep -c '#' file")
        self.assertEqual(len(eta.clip("x" * 200)), eta.LABEL_MAX)

    def test_spans(self):
        for seconds, text in ((None, "?"), (30, "<1m"), (240, "4m"), (3900, "1h05"),
                              (-720, "-12m"), (-30, "-0m"), (97200, "1d3h")):
            with self.subTest(seconds=seconds):
                self.assertEqual(eta.format_span(seconds), text)


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-eta-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.dir = str(self.root / "state")
        self.claude = self.root / "claude"
        (self.claude / "sessions").mkdir(parents=True)
        self.codex = self.root / "codex"
        self.codex.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in AGENT_VARS}
        self.env.update(AGENT_ETA_DIR=self.dir, CLAUDE_CONFIG_DIR=str(self.claude),
                        CODEX_HOME=str(self.codex), PYTHONDONTWRITEBYTECODE="1")
        self.saved = {k: os.environ.get(k) for k in AGENT_VARS}
        for key in AGENT_VARS:
            os.environ.pop(key, None)
        os.environ.update(AGENT_ETA_DIR=self.dir, CLAUDE_CONFIG_DIR=str(self.claude), CODEX_HOME=str(self.codex))
        self.addCleanup(self.restore)
        eta.state_dir()

    def restore(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def put(self, entry_id, **fields):
        entry = eta.make_entry(entry_id, fields.pop("agent", "other"), fields.pop("label", entry_id),
                               fields.pop("eta", None), fields.pop("holder", None), fields.pop("source", "add"),
                               fields.pop("session", None), "/work", fields.pop("now", None))
        entry.update(fields)
        eta.write_atomic(eta.entry_path(self.dir, entry_id), entry)
        return entry

    def ids(self, now=None):
        return [row["id"] for row in eta.rows(self.dir, time.time() if now is None else now)]

    def cli(self, *args, stdin=None, env=None):
        return subprocess.run([sys.executable, str(_SRC), *args], input=stdin, capture_output=True,
                              text=True, env=env or self.env, timeout=30)

    def dead_pid(self):
        child = subprocess.Popen(["true"])
        child.wait()
        return child.pid


class Holders(StateTest):
    def test_sorting_puts_overdue_first_and_unknown_last(self):
        now = time.time()
        self.put("later", eta=3600, now=now)
        self.put("soon", eta=60, now=now)
        self.put("late", eta=60, now=now - 600)
        self.put("unknown", holder={"type": "pid", "pid": os.getpid(), "start": eta.proc_start(os.getpid())})
        self.assertEqual(self.ids(now), ["late", "soon", "later", "unknown"])

    def test_pid_holder(self):
        start = eta.proc_start(os.getpid())
        self.put("live", holder={"type": "pid", "pid": os.getpid(), "start": start})
        self.put("reused", holder={"type": "pid", "pid": os.getpid(), "start": str(int(start) + 1)})
        self.put("dead", holder={"type": "pid", "pid": self.dead_pid(), "start": "1"})
        self.assertEqual(self.ids(), ["live"])
        self.assertEqual(sorted(os.listdir(self.dir)), ["live.json"])

    def test_lock_holder(self):
        entry = eta.make_entry("locked", "other", "x", 60, {"type": "lock"}, "run")
        handle = eta.write_locked(eta.entry_path(self.dir, "locked"), entry)
        self.assertEqual(self.ids(), ["locked"])
        handle.close()
        self.assertEqual(self.ids(), [])

    def test_entries_without_holder_expire(self):
        now = time.time()
        self.put("fresh", eta=600, now=now - 1200)
        self.put("stale", eta=600, now=now - 7200)
        self.put("long", eta=3 * 3600, now=now - 5 * 3600)
        self.assertEqual(sorted(self.ids(now)), ["fresh", "long"])

    def test_pair_dies_with_its_app_server(self):
        self.put("orphan", agent="codex", eta=600, holder={"type": "pair", "app": {"pid": self.dead_pid()}})
        self.put("kept", agent="codex", eta=600, holder={"type": "pair", "app": {}})
        self.assertEqual(self.ids(), ["kept"])

    def test_unreadable_entries_are_dropped(self):
        pathlib.Path(self.dir, "broken.json").write_text("{half")
        pathlib.Path(self.dir, "list.json").write_text("[]")
        self.assertEqual(self.ids(), [])
        self.assertEqual(os.listdir(self.dir), [])

    def test_state_dir_must_be_a_directory(self):
        blocker = self.root / "file"
        blocker.write_text("")
        os.environ["AGENT_ETA_DIR"] = str(blocker)
        with self.assertRaises(eta.StateDirError):
            eta.state_dir()


class Commands(StateTest):
    def test_run_lists_the_command_while_it_runs(self):
        listing = "import subprocess,sys; print(subprocess.run([sys.executable, %r, '--json'], " \
                  "capture_output=True, text=True).stdout)" % str(_SRC)
        done = self.cli("run", "--eta", "5m", "--label", "probe", "--", sys.executable, "-c", listing)
        self.assertEqual(done.returncode, 0, done.stderr)
        tasks = json.loads(done.stdout)["tasks"]
        self.assertEqual([t["label"] for t in tasks], ["probe"])
        self.assertEqual(tasks[0]["holder"], {"type": "lock"})
        self.assertEqual(os.listdir(self.dir), [])

    def test_run_passes_the_exit_code_through(self):
        self.assertEqual(self.cli("run", "--eta", "1m", "--", sys.executable, "-c",
                                  "raise SystemExit(7)").returncode, 7)
        self.assertEqual(self.cli("run", "--eta", "1m", "--", "/nonexistent/cmd").returncode, 127)
        self.assertEqual(os.listdir(self.dir), [])

    def test_run_forwards_sigterm(self):
        child = subprocess.Popen([sys.executable, str(_SRC), "run", "--eta", "1m", "--", "sleep", "30"],
                                 env=self.env)
        deadline = time.time() + 10
        while not os.listdir(self.dir) and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.2)
        child.send_signal(signal.SIGTERM)
        self.assertEqual(child.wait(timeout=10), 128 + signal.SIGTERM)
        self.assertEqual(os.listdir(self.dir), [])

    def test_add_and_done(self):
        added = self.cli("add", "--eta", "10m", "--label", "CI pipeline")
        self.assertEqual(added.returncode, 0, added.stderr)
        entry_id = added.stdout.strip()
        self.assertIn("CI pipeline", self.cli().stdout)
        self.assertEqual(self.cli("done", entry_id).returncode, 0)
        self.assertEqual(self.cli("done", entry_id).returncode, 1)
        self.assertEqual(self.cli().stdout, "No background tasks.\n")

    def test_add_with_a_pid_ends_with_that_process(self):
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        self.cli("add", "--eta", "2h", "--label", "local run", "--agent", "local", "--pid", str(sleeper.pid))
        self.assertEqual(len(self.ids()), 1)
        sleeper.kill()
        sleeper.wait()
        self.assertEqual(self.ids(), [])


class Hooks(StateTest):
    def hook(self, payload, env=None):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        done = self.cli("hook", stdin=text, env=env)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, "")
        return done

    def claude_env(self):
        env = dict(self.env, CLAUDECODE="1", CLAUDE_PID=str(os.getpid()))
        (self.claude / "sessions" / ("%d.json" % os.getpid())).write_text(json.dumps(
            {"pid": os.getpid(), "name": "fake-session", "procStart": eta.proc_start(os.getpid())}))
        return env

    def background(self, task_id):
        tasks = self.root / "tasks"
        tasks.mkdir(exist_ok=True)
        output = open(tasks / ("%s.output" % task_id), "w")
        self.addCleanup(output.close)
        child = subprocess.Popen(["sleep", "30"], stdout=output)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        return child

    def claude_payload(self, task_id, description="Wait two minutes (ETA ca. 2 minutes)", command="sleep 30"):
        return {"hook_event_name": "PostToolUse", "tool_name": "Bash", "session_id": "s-1", "cwd": "/work",
                "tool_input": {"command": command, "description": description, "run_in_background": True},
                "tool_response": {"backgroundTaskId": task_id, "stdout": ""}}

    def test_claude_background_command_is_recorded(self):
        child = self.background("btest1")
        self.hook(self.claude_payload("btest1"), self.claude_env())
        rows = eta.rows(self.dir, time.time())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["agent"], row["label"], row["session_name"]), ("claude", "Wait two minutes",
                                                                              "fake-session"))
        self.assertEqual(row["holder"]["pid"], child.pid)
        self.assertAlmostEqual(row["remaining"], 120, delta=5)
        child.kill()
        child.wait()
        self.assertEqual(eta.rows(self.dir, time.time()), [])

    def test_claude_without_eta_is_listed_as_unknown(self):
        self.background("btest2")
        self.hook(self.claude_payload("btest2", description="Regenerate all scenes"), self.claude_env())
        self.assertEqual([r["remaining"] for r in eta.rows(self.dir, time.time())], [None])

    def test_claude_hook_skips_what_it_must_not_record(self):
        env = self.claude_env()
        foreground = self.claude_payload("x")
        foreground["tool_response"] = {"stdout": "done"}
        self.hook(foreground, env)
        self.background("bwrapped")
        self.hook(self.claude_payload("bwrapped", command="agent-eta run --eta 5m -- make"), env)
        self.hook(self.claude_payload("bgone"), env)
        self.assertEqual(os.listdir(self.dir), ["hook.log"])
        actions = [line.split("\t")[-1] for line in pathlib.Path(self.dir, "hook.log").read_text().splitlines()]
        self.assertEqual(actions, ["foreground", "wrapped", "already-exited"])

    def codex_payload(self, event, use_id="call_1", command="sleep 120  # ETA ca. 2 minutes"):
        return {"hook_event_name": event, "tool_name": "Bash", "session_id": "thread-1", "turn_id": "t-1",
                "cwd": "/work", "tool_use_id": use_id, "tool_input": {"command": command},
                "model": "m", "permission_mode": "default", "transcript_path": None}

    def test_codex_pre_and_post_pair_up(self):
        (self.codex / "session_index.jsonl").write_text(
            json.dumps({"id": "thread-1", "thread_name": "old name"}) + "\n" +
            json.dumps({"id": "thread-1", "thread_name": "Fix checkout"}) + "\n")
        self.hook(self.codex_payload("PreToolUse"))
        entry = json.loads(pathlib.Path(self.dir, "codex-call_1.json").read_text())
        self.assertEqual((entry["label"], entry["due"] - entry["started"]), ("sleep 120", 120))
        started = entry["started"]
        self.assertEqual(eta.rows(self.dir, started + 5), [])
        rows = eta.rows(self.dir, started + 11)
        self.assertEqual([r["session_name"] for r in rows], ["Fix checkout"])
        self.hook(self.codex_payload("PostToolUse"))
        self.assertEqual(eta.rows(self.dir, started + 11), [])

    def test_codex_skips_a_wrapped_command(self):
        self.hook(self.codex_payload("PreToolUse", command="~/.local/bin/agent-eta run --eta 2m -- make"))
        self.assertEqual(os.listdir(self.dir), ["hook.log"])

    def test_codex_wins_over_a_leaked_claude_environment(self):
        self.hook(self.codex_payload("PreToolUse"), self.claude_env())
        self.assertTrue(pathlib.Path(self.dir, "codex-call_1.json").exists())

    def test_garbage_input_is_silent(self):
        for text in ("", "not json", "[]", "null", '{"tool_name": "Bash"}',
                     '{"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_response": "x"}'):
            with self.subTest(text=text):
                self.hook(text, self.claude_env())
        self.assertEqual(sorted(os.listdir(self.dir)), ["hook.log"])

    def test_hook_log_carries_no_command_text(self):
        self.hook(self.codex_payload("PreToolUse", command="curl -H 'secret-token' x  # ETA 1m"))
        self.assertNotIn("secret-token", pathlib.Path(self.dir, "hook.log").read_text())


if __name__ == "__main__":
    unittest.main()
