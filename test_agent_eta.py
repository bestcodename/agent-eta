#!/usr/bin/env python3
"""Tests for agent-eta.

Run with:  python3 -m unittest discover -s . -v

Every test works in its own state directory and its own fake Claude Code and Codex
homes, so nothing here touches /tmp/agent-eta-<uid> or a live session registry. The hook
tests start a real process with fd 1 on a fake tasks/<id>.output, because finding that
process is the part a payload alone cannot prove.
"""

import datetime
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
import unittest.mock

_SRC = pathlib.Path(__file__).with_name("agent-eta")
_spec = importlib.util.spec_from_loader(
    "agent_eta",
    importlib.machinery.SourceFileLoader("agent_eta", str(_SRC)),
)
eta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eta)

AGENT_VARS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SANDBOX",
              "CODEX_SANDBOX_NETWORK_DISABLED", "AGENT_ETA_DIR", "CLAUDE_CONFIG_DIR", "CODEX_HOME",
              "CLAUDE_ACCOUNTS_FILE", "DSH_HOME", "DSH_SESSION_ID", "AGENT_ETA_NO_REFRESH",
              "AGENT_ETA_CONFIG", "AGENT_ETA_CACHE_DIR")


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

    def test_progress_is_the_elapsed_share_of_the_eta(self):
        for started, due, now, share in ((100, 200, 150, 0.5), (100, 200, 250, 1.0), (100, 200, 50, 0.0),
                                         (100, None, 150, None), (None, 200, 150, 0.0), (200, 200, 200, 1.0)):
            with self.subTest(started=started, due=due, now=now):
                self.assertEqual(eta.progress(started, due, now), share)

    def test_spans(self):
        for seconds, text in ((None, "?"), (30, "<1m"), (240, "4m"), (3900, "1h05"),
                              (-720, "-12m"), (-30, "-0m"), (97200, "1d3h")):
            with self.subTest(seconds=seconds):
                self.assertEqual(eta.format_span(seconds), text)

    def test_a_countdown_is_the_difference_of_the_two_clock_times(self):
        # Measured on 2026-10-20: the Codex 5-hour window reset at 06:55:06, and at 04:22:30 the modal
        # read "resets in 2h 32m" while both clocks said 2h 33m.
        resets_at, now = 1792472106, 1792462950
        [window] = eta.usage_view(now, [eta.usage_window("codex", 300, 79.0, resets_at, now - 60)])
        self.assertEqual(eta.usage_cells(window, now)[3:], ("2h33", "06:55"))
        session = {"agent": "claude", "account": None, "name": "shop", "state": "working", "since": now - 3890,
                   "due": resets_at, "remaining": int(resets_at - now),
                   "tasks": [{"label": "ci", "due": resets_at, "remaining": int(resets_at - now)}]}
        # FOR runs from 03:17:40, 65 minutes on the clock and 64 minutes 50 seconds in seconds.
        lines = eta.session_lines([session], now)
        self.assertEqual(lines[1][:4], ("working", "1h05", "2h33", "06:55"))
        self.assertEqual(lines[2][2:4], ("2h33", "06:55"))
        self.assertEqual(eta.render([dict(session["tasks"][0], id="ci", agent="claude", session_name="shop")], now)
                         .splitlines()[1].split()[:2], ["2h33", "06:55"])

    def test_countdowns_follow_the_clock_for_every_second(self):
        resets_at = 1792472106
        def minute(epoch):
            return datetime.datetime.fromtimestamp(epoch, eta.BERLIN).replace(second=0, microsecond=0)
        for now in range(resets_at - 7200, resets_at):
            minutes = int((minute(resets_at) - minute(now)).total_seconds() // 60)
            with self.subTest(now=now):
                self.assertEqual(eta.format_span(eta.clock_span(resets_at, now)),
                                 "<1m" if minutes < 1 else eta.format_span(minutes * 60))


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
        # Its own dsh home, so a dsh process running on this machine never shows in a test.
        self.dsh = self.root / "dsh"
        (self.dsh / "sessions").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if k not in AGENT_VARS}
        self.accounts = self.root / "accounts.json"
        self.env.update(AGENT_ETA_DIR=self.dir, CLAUDE_CONFIG_DIR=str(self.claude),
                        CODEX_HOME=str(self.codex), CLAUDE_ACCOUNTS_FILE=str(self.accounts),
                        DSH_HOME=str(self.dsh), PYTHONDONTWRITEBYTECODE="1", AGENT_ETA_NO_REFRESH="1")
        self.saved = {k: os.environ.get(k) for k in AGENT_VARS}
        for key in AGENT_VARS:
            os.environ.pop(key, None)
        os.environ.update(AGENT_ETA_DIR=self.dir, CLAUDE_CONFIG_DIR=str(self.claude), CODEX_HOME=str(self.codex),
                          CLAUDE_ACCOUNTS_FILE=str(self.accounts), DSH_HOME=str(self.dsh), AGENT_ETA_NO_REFRESH="1")
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

    def second_account(self):
        """Register the fixture's directory as account work and a second one as private, the way
        claude-account (bestcodename/ai) writes its registry, and return the second directory."""
        private = self.root / "claude-private"
        (private / "sessions").mkdir(parents=True)
        self.accounts.write_text(json.dumps({"accounts": [
            {"name": "work", "email": "w@example.com", "dir": str(self.claude)},
            {"name": "private", "email": "p@example.org", "dir": str(private)}]}))
        return private

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
        self.assertEqual(self.cli().stdout.splitlines()[1:], [
            eta.EMPTY_SECTIONS[0], "---", eta.EMPTY_SECTIONS[1], "---", eta.EMPTY_SECTIONS[2], "---",
            eta.EMPTY_SECTIONS[3], "", "USAGE   USED  ELAPSED  PACE  REMAINING  DUE  READ  NOTE",
            eta.EMPTY_USAGE[0], "---", eta.EMPTY_USAGE[1], "---",
            "claude  -     -        -     -          -    -     Authentication unknown · Usage unavailable",
            "codex   -     -        -     -          -    -     Authentication unknown · Usage unavailable"])
        self.assertEqual(self.cli("--tasks").stdout, "No background tasks.\n")

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
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".json")], [])

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


class Sessions(StateTest):
    def register(self, pid=None, status="busy", since=None, **fields):
        """A Claude Code registry record for a live pid, as Claude Code 2.1.288 writes it."""
        pid = os.getpid() if pid is None else pid
        record = {"pid": pid, "sessionId": "s-%d" % pid, "name": "session-%d" % pid, "cwd": "/work",
                  "procStart": eta.proc_start(pid), "status": status,
                  "statusUpdatedAt": int((time.time() if since is None else since) * 1000)}
        record.update(fields)
        (self.claude / "sessions" / ("%d.json" % pid)).write_text(json.dumps(record))
        return record

    def sleeper(self):
        child = subprocess.Popen(["sleep", "30"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        return child

    def view(self, now=None):
        return eta.sessions_view(self.dir, time.time() if now is None else now)

    def hook(self, payload, env=None):
        done = self.cli("hook", stdin=json.dumps(payload), env=env)
        self.assertEqual((done.returncode, done.stdout), (0, ""))

    def codex_event(self, event, thread="thread-1", **fields):
        payload = {"hook_event_name": event, "session_id": thread, "turn_id": "t-1", "cwd": "/work/shop"}
        payload.update(fields)
        return payload

    def test_claude_sessions_come_from_the_registry(self):
        self.register(status="waiting", waitingFor="dialog open")
        dead = self.dead_pid()
        (self.claude / "sessions" / ("%d.json" % dead)).write_text(json.dumps({"pid": dead, "status": "busy"}))
        sessions = self.view()
        self.assertEqual([(s["agent"], s["state"], s["waiting_for"]) for s in sessions],
                         [("claude", "waiting", "dialog open")])

    def test_every_registered_account_is_read_and_labelled(self):
        self.register(status="idle")
        self.assertEqual(eta.render_sessions(self.view(), time.time()).splitlines()[1].split()[4], "claude")
        private = self.second_account()
        other = self.sleeper()
        record = self.register(other.pid, "waiting", name="x", nameSource="derived")
        os.rename(self.claude / "sessions" / ("%d.json" % other.pid), private / "sessions" / ("%d.json" % other.pid))
        folder = private / "projects" / "-work"
        folder.mkdir(parents=True)
        (folder / ("%s.jsonl" % record["sessionId"])).write_text(json.dumps({"type": "custom-title",
                                                                             "customTitle": "Private chat"}) + "\n")
        sessions = self.view()
        self.assertEqual([(s["account"], s["name"]) for s in sessions],
                         [("private", "Private chat"), ("work", "session-%d" % os.getpid())])
        agents = [line.split()[4] for line in eta.render_sessions(sessions, time.time()).splitlines()[1:]
                  if line != eta.SECTION_RULE and line not in eta.EMPTY_SECTIONS]
        self.assertEqual(agents, ["claude/private", "claude/work"])
        self.assertEqual(eta.claude_session(other.pid)["sessionId"], record["sessionId"])
        self.assertEqual(eta.claude_session(other.pid, str(self.claude)), {})

    def test_order_is_waiting_then_idle_then_working_by_eta_then_stopped(self):
        now = time.time()
        idle, working, waiting = self.sleeper(), self.sleeper(), self.sleeper()
        self.register(idle.pid, "idle", now - 600)
        self.register(working.pid, "busy", now - 60)
        self.register(waiting.pid, "waiting", now - 30)
        self.register(status="busy", since=now - 60)
        self.put("ci", agent="claude", eta=300, session={"pid": working.pid}, now=now)
        names = [s["name"] for s in self.view(now)]
        self.assertEqual(names, ["session-%d" % waiting.pid, "session-%d" % idle.pid,
                                 "session-%d" % working.pid, "session-%d" % os.getpid()])
        self.assertEqual(self.view(now)[2]["eta_source"], "tasks")

    def test_sections_split_attention_work_and_usage_limits(self):
        def session(name, state, remaining=None, due=None):
            return {"name": name, "state": state, "remaining": remaining, "since": 0, "due": due, "tasks": [],
                    "agent": "codex", "turn_label": None, "waiting_for": None}
        sessions = [session("ask", "waiting"), session("rest", "idle"),
                    session("work", "working", 600, 1600), session("limit", "stopped", 60, 1060)]
        def names(chosen):
            return [line if line in (eta.SECTION_RULE,) + eta.EMPTY_SECTIONS else line.split()[-1]
                    for line in eta.render_sessions(chosen, 1000).splitlines()[1:]]
        self.assertEqual(names(sessions), ["ask", "rest", "---", "work", "---", "limit", "---", eta.EMPTY_SECTIONS[3]])
        self.assertEqual(names(sessions[2:3]), [eta.EMPTY_SECTIONS[0], "---", "work", "---", eta.EMPTY_SECTIONS[2],
                                                "---", eta.EMPTY_SECTIONS[3]])

    def test_a_usage_limit_sorts_after_work_and_a_reset_one_with_idle(self):
        def session(name, state, remaining=None, since=0, due=None):
            return {"name": name, "state": state, "remaining": remaining, "since": since, "due": due, "tasks": []}
        sessions = [session("limit", "stopped", 60, due=1), session("reset", "stopped", since=5),
                    session("work", "working", 600), session("idle", "idle", since=1),
                    session("ask", "waiting")]
        self.assertEqual([s["name"] for s in sorted(sessions, key=eta.session_sort_key)],
                         ["ask", "reset", "idle", "work", "limit"])

    def test_a_task_without_a_known_session_stands_alone(self):
        self.put("local-run", agent="local", eta=600, label="qwen on ai",
                 holder={"type": "pid", "pid": os.getpid(), "start": eta.proc_start(os.getpid())})
        sessions = self.view()
        self.assertEqual([(s["agent"], s["state"], len(s["tasks"])) for s in sessions], [("local", "working", 1)])
        self.assertIn("└ qwen on ai", eta.render_sessions(sessions, time.time()))

    def test_sec_manual_reminder_without_owner_is_unknown_and_preserved(self):
        now = time.time()
        entry = self.put("add-afa18602", agent="claude", eta=13 * 3600 + 37 * 60,
                         label="SEC-28 check-in", now=now - 14 * 3600,
                         session={"id": "sec-ended", "name": "SEC", "pid": self.dead_pid()})
        path = pathlib.Path(self.dir, "add-afa18602.json")
        original = path.read_bytes()
        [session] = self.view(now)
        self.assertEqual((session["state"], eta.section(session)), ("unknown", 0))
        self.assertEqual(session["tasks"][0]["id"], entry["id"])
        self.assertEqual(session["due"], entry["due"])
        self.assertTrue(session["overdue"])
        self.assertEqual(path.read_bytes(), original)
        self.put("keep", eta=600)
        self.assertEqual(self.cli("done", entry["id"]).returncode, 0)
        self.assertEqual(self.ids(), ["keep"])

    def test_idle_owner_with_only_a_manual_wait_stays_in_nonworking_group(self):
        owner = self.register(status="idle")
        self.put("ci-wait", agent="claude", eta=600,
                 session={"id": owner["sessionId"], "pid": owner["pid"]})
        [session] = self.view()
        self.assertEqual((session["state"], eta.section(session)), ("idle", 0))

    def test_codex_session_end_preserves_manual_wait_without_inventing_work(self):
        self.hook(self.codex_event("UserPromptSubmit"))
        self.put("external-ci", agent="codex", eta=600, session={"id": "thread-1"})
        self.hook(self.codex_event("SessionEnd"))
        [session] = self.view()
        self.assertEqual((session["state"], eta.section(session)), ("unknown", 0))
        self.assertTrue(pathlib.Path(self.dir, "external-ci.json").is_file())

    def test_manual_reminder_is_not_replaced_by_an_account_usage_limit(self):
        self.put("reminder", agent="codex", eta=600, session={"id": "ended"})
        usage = [{"agent": "codex", "used": 100, "remaining": 3600, "reached": True, "resets_at": int(time.time()) + 3600,
                  "minutes": 300}]
        [session] = eta.sessions_view(self.dir, time.time(), usage=usage)
        self.assertEqual(session["state"], "unknown")
        self.assertIsNone(session.get("resume_at"))
        self.assertEqual(session["due"], session["tasks"][0]["due"])

    def test_locked_background_task_remains_working_beside_an_orphan_wait(self):
        self.put("manual", agent="claude", eta=600, session={"id": "gone"})
        entry = eta.make_entry("local-work", "local", "build", 600, {"type": "lock"}, "run")
        with eta.write_locked(eta.entry_path(self.dir, entry["id"]), entry):
            by_agent = {s["agent"]: s for s in self.view()}
            self.assertEqual(by_agent["local"]["state"], "working")
            self.assertEqual(eta.section(by_agent["local"]), 1)
            self.assertEqual(by_agent["claude"]["state"], "unknown")
            self.assertEqual(eta.section(by_agent["claude"]), 0)

    def test_codex_thread_state_follows_its_hooks(self):
        (self.codex / "session_index.jsonl").write_text(json.dumps({"id": "thread-1", "thread_name": "Shop"}) + "\n")
        expected = (("UserPromptSubmit", "working", None), ("PermissionRequest", "waiting", "permission"),
                    ("PreToolUse", "working", None), ("Stop", "idle", None))
        for event, state, reason in expected:
            with self.subTest(event=event):
                self.hook(self.codex_event(event, tool_name="Bash", tool_use_id="call_9",
                                     tool_input={"command": "sleep 1"}))
                [session] = self.view()
                self.assertEqual((session["name"], session["state"], session["waiting_for"]), ("Shop", state, reason))
        self.hook(self.codex_event("SessionEnd"))
        self.assertEqual(self.view(), [])

    def test_codex_open_question_in_the_transcript_means_waiting(self):
        folder = self.codex / "sessions" / "2026" / "10" / "03"
        folder.mkdir(parents=True)
        rollout = folder / "rollout-2026-10-03T03-19-50-thread-1.jsonl"
        def item(**payload):
            return json.dumps({"timestamp": "2026-10-03T21:59:39.000Z", "type": "response_item", "payload": payload})
        rollout.write_text("\n".join([
            item(type="custom_tool_call", name="exec", call_id="c1"),
            item(type="custom_tool_call_output", call_id="c1"),
            item(type="function_call", name="request_user_input", call_id="q1")]) + "\n")
        self.hook(self.codex_event("PreToolUse", tool_name="Bash", tool_use_id="c1", tool_input={"command": "ls"}))
        [session] = self.view()
        self.assertEqual((session["state"], session["waiting_for"]), ("waiting", "question"))
        self.assertEqual(session["since"], eta.parse_stamp("2026-10-03T21:59:39.000Z"))
        with rollout.open("a") as handle:
            handle.write(item(type="function_call_output", call_id="q1") + "\n")
        self.assertEqual([s["state"] for s in self.view()], ["working"])
        rollout.write_text(item(type="function_call", name="request_user_input", call_id="q2") + "\n")
        self.hook(self.codex_event("Stop"))
        self.assertEqual([s["state"] for s in self.view()], ["idle"])

    def test_codex_end_discards_unpaired_command_but_keeps_reminder_and_live_job(self):
        for event in ("Stop", "Interrupt"):
            with self.subTest(event=event):
                self.hook(self.codex_event("UserPromptSubmit"))
                self.hook(self.codex_event("PreToolUse", tool_name="Bash", tool_use_id="rejected",
                                           tool_input={"command": "rejected command"}))
                self.put("manual", agent="codex", eta=600, session={"id": "thread-1"})
                self.hook(self.codex_event(event))
                [session] = self.view(time.time() + 11)
                self.assertEqual((session["state"], eta.section(session)), ("idle", 0))
                self.assertEqual([t["id"] for t in session["tasks"]], ["manual"])
                self.assertFalse(pathlib.Path(self.dir, "codex-rejected.json").exists())
                self.put("live", agent="codex", eta=600, session={"id": "thread-1"},
                         holder={"type": "pid", "pid": os.getpid(), "start": eta.proc_start(os.getpid())})
                [session] = self.view(time.time() + 11)
                self.assertEqual(eta.section(session), 1)
                self.assertEqual(sorted(t["id"] for t in session["tasks"]), ["live", "manual"])
                pathlib.Path(self.dir, "live.json").unlink()

    def test_async_question_waits_past_ack_and_stop_until_every_answer(self):
        rollout = self.codex / "async.jsonl"
        stamp = "2026-10-18T19:00:00.000Z"
        def append(**payload):
            with rollout.open("a") as handle:
                handle.write(json.dumps({"timestamp": stamp, "type": "response_item", "payload": payload}) + "\n")
        def answer(call, index):
            replies = [{"questionItemId": json.dumps(["request_user_input_async", call, index]), "answer": "yes"}]
            append(type="message", role="user", content=[{"type": "input_text", "text":
                   "<send_user_message_question_reply>" + json.dumps(replies) + "</send_user_message_question_reply>"}])
        append(type="function_call", name="request_user_input_async", call_id="q1",
               arguments=json.dumps({"questions": [{"title": "first"}, {"title": "second"}]}))
        append(type="function_call_output", call_id="q1", output='{"accepted":true}')
        self.hook(self.codex_event("UserPromptSubmit", transcript_path=str(rollout)))
        [session] = self.view()
        self.assertEqual((session["state"], session["waiting_for"]), ("waiting", "question"))
        self.hook(self.codex_event("Stop", transcript_path=str(rollout)))
        answer("other-call", 0)
        answer("q1", 0)
        self.assertEqual([s["state"] for s in self.view()], ["waiting"])
        answer("q1", 1)
        self.assertEqual([s["state"] for s in self.view()], ["idle"])

    def test_rejected_async_question_does_not_leave_a_wait(self):
        rollout = self.codex / "async-error.jsonl"
        events = [
            {"type": "function_call", "name": "request_user_input_async", "call_id": "q1",
             "arguments": json.dumps({"questions": [{"title": "first"}]})},
            {"type": "function_call_output", "call_id": "q1", "output": '{"accepted":false}'},
        ]
        rollout.write_text("\n".join(json.dumps({"timestamp": "2026-10-18T19:00:00Z", "type": "response_item",
                                                 "payload": p}) for p in events) + "\n")
        self.hook(self.codex_event("UserPromptSubmit", transcript_path=str(rollout)))
        self.assertEqual([s["state"] for s in self.view()], ["working"])

    def test_codex_permission_ends_once_the_script_open_at_the_request_has_output(self):
        folder = self.codex / "sessions" / "2026" / "10" / "04"
        folder.mkdir(parents=True)
        rollout = folder / "rollout-2026-10-04T02-55-00-thread-1.jsonl"
        request = eta.parse_stamp("2026-10-04T00:55:34.000Z")
        def item(second, **payload):
            stamp = "2026-10-04T00:55:%02d.500Z" % second
            return json.dumps({"timestamp": stamp, "type": "response_item", "payload": payload}) + "\n"
        def write(*lines):
            with rollout.open("a") as handle:
                handle.write("".join(lines))
        def state():
            [session] = eta.sessions_view(self.dir, request + 60)
            return session["state"], session["waiting_for"], session["since"]
        write(item(20, type="custom_tool_call", name="exec", call_id="c0"),
              item(34, type="custom_tool_call", name="exec", call_id="c1"))
        eta.codex_state(self.dir, self.codex_event("PermissionRequest", transcript_path=str(rollout)),
                        "waiting", "permission", now=request)
        self.assertEqual(state(), ("waiting", "permission", int(request)))
        write(item(36, type="custom_tool_call_output", call_id="c0"))
        self.assertEqual(state()[:2], ("waiting", "permission"))
        write(item(41, type="custom_tool_call_output", call_id="c1"))
        self.assertEqual(state(), ("working", None, eta.parse_stamp("2026-10-04T00:55:41.500Z")))
        write(item(45, type="function_call", name="request_user_input", call_id="q1"))
        self.assertEqual(state()[:2], ("waiting", "question"))

    def test_codex_permission_without_its_call_in_the_transcript_stays_waiting(self):
        folder = self.codex / "sessions" / "2026" / "10" / "04"
        folder.mkdir(parents=True)
        rollout = folder / "rollout-2026-10-04T02-55-00-thread-1.jsonl"
        late = {"timestamp": "2099-01-01T00:00:00.000Z", "type": "response_item",
                "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "c9"}}
        answer = dict(late, payload={"type": "custom_tool_call_output", "call_id": "c9"})
        rollout.write_text(json.dumps(late) + "\n" + json.dumps(answer) + "\n")
        self.hook(self.codex_event("PermissionRequest", transcript_path=str(rollout)))
        self.assertEqual([(s["state"], s["waiting_for"]) for s in self.view()], [("waiting", "permission")])

    def test_a_derived_claude_name_gives_way_to_the_transcript_title(self):
        self.register(name="ai-0b", nameSource="derived")
        folder = self.claude / "projects" / "-work"
        folder.mkdir(parents=True)
        transcript = folder / ("s-%d.jsonl" % os.getpid())
        transcript.write_text(json.dumps({"type": "ai-title", "aiTitle": "ETA overview"}) + "\n")
        self.assertEqual([s["name"] for s in self.view()], ["ETA overview"])
        with transcript.open("a") as handle:
            handle.write(json.dumps({"type": "custom-title", "customTitle": "Agent ETA"}) + "\n")
            handle.write(json.dumps({"type": "ai-title", "aiTitle": "Later title"}) + "\n")
        self.assertEqual([s["name"] for s in self.view()], ["Agent ETA"])
        self.register(name="chosen", nameSource="user")
        self.assertEqual([s["name"] for s in self.view()], ["chosen"])

    def test_codex_name_comes_from_the_state_database(self):
        import sqlite3
        connection = sqlite3.connect(str(self.codex / "state_5.sqlite"))
        connection.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT, rollout_path TEXT)")
        connection.executemany("INSERT INTO threads VALUES (?, ?, ?, ?)", [
            ("thread-1", None, "in the dsp project add new ui features:\n\nmake every gain level", "/nope"),
            ("thread-2", "Run sleep 120", "run sleep 120", "/nope")])
        connection.commit()
        connection.close()
        self.hook(self.codex_event("UserPromptSubmit"))
        self.hook(self.codex_event("UserPromptSubmit", thread="thread-2"))
        self.assertEqual(sorted(s["name"] for s in self.view()),
                         ["Run sleep 120", "in the dsp project add new ui features"])

    def test_remaining_reads_zero_when_idle_and_unknown_with_its_due_when_working(self):
        now = time.time()
        idle, working, waiting = self.sleeper(), self.sleeper(), self.sleeper()
        self.register(idle.pid, "idle", now - 60)
        self.register(working.pid, "busy", now - 60)
        self.register(waiting.pid, "waiting", now - 60)
        lines = [line for line in eta.render_sessions(self.view(now), now).splitlines()[1:] if line != eta.SECTION_RULE and line not in eta.EMPTY_SECTIONS]
        cells = {line.split()[0]: tuple(line.split()[2:4]) for line in lines}
        self.assertEqual(cells, {"idle": ("0", "-"), "working": ("?", "?"), "waiting": ("-", "-")})

    def test_codex_plan_waits_for_approval_once_its_turn_ended(self):
        folder = self.codex / "sessions" / "2026" / "10" / "03"
        folder.mkdir(parents=True)
        rollout = folder / "rollout-2026-10-03T03-19-50-thread-1.jsonl"
        def event(stamp, **payload):
            return json.dumps({"timestamp": "2026-10-03T23:40:%s.000Z" % stamp, "type": "event_msg",
                               "payload": payload}) + "\n"
        rollout.write_text(event("00", type="task_started", turn_id="t-1") +
                           event("55", type="item_completed", turn_id="t-1", item={"type": "Plan", "id": "p"}))
        self.hook(self.codex_event("UserPromptSubmit"))
        self.assertEqual([s["state"] for s in self.view()], ["working"])
        with rollout.open("a") as handle:
            handle.write(event("56", type="task_complete", turn_id="t-1"))
        self.hook(self.codex_event("Stop"))
        [session] = self.view()
        self.assertEqual((session["state"], session["waiting_for"]), ("waiting", "plan approval"))
        self.assertEqual(session["since"], eta.parse_stamp("2026-10-03T23:40:56.000Z"))
        with rollout.open("a") as handle:
            handle.write(event("59", type="task_started", turn_id="t-2"))
        self.hook(self.codex_event("UserPromptSubmit"))
        self.assertEqual([s["state"] for s in self.view()], ["working"])
        with rollout.open("a") as handle:
            handle.write(event("59", type="task_complete", turn_id="t-2"))
        self.hook(self.codex_event("Stop"))
        self.assertEqual([s["state"] for s in self.view()], ["idle"])

    def test_codex_usage_limit_stops_the_turn_until_the_window_resets(self):
        folder = self.codex / "sessions" / "2026" / "10" / "04"
        folder.mkdir(parents=True)
        rollout = folder / "rollout-2026-10-04T00-17-51-thread-1.jsonl"
        now = time.time()
        resets = int(now) + 360
        # The turn ETA below is set before the turn fails, so the failure is stamped after it.
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now + 5))
        def event(**payload):
            return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": payload}) + "\n"
        limits = {"limit_id": "codex", "primary": {"used_percent": 100.0, "resets_at": resets},
                  "secondary": {"used_percent": 84.0, "resets_at": resets + 86400}}
        rollout.write_text(event(type="task_started", turn_id="t-1"))
        self.hook(self.codex_event("UserPromptSubmit"))
        env = dict(self.env, CODEX_THREAD_ID="thread-1", CODEX_SANDBOX="seccomp")
        self.cli("turn", "--eta", "ca. 30 minutes", env=env)
        self.hook(self.codex_event("PreToolUse", tool_name="Bash", tool_use_id="call_1",
                                   tool_input={"command": "sleep 300  # ETA ca. 5 minutes"}))
        [session] = self.view(now + 11)
        self.assertEqual(len(session["tasks"]), 1)
        with rollout.open("a") as handle:
            handle.write(event(type="token_count", rate_limits=limits) +
                         event(type="token_count", rate_limits={"limit_id": "premium", "primary": None}) +
                         event(type="task_complete", turn_id="t-1",
                               error={"message": "out of credits", "codex_error_info": "usage_limit_exceeded"}))
        [session] = self.view(now)
        self.assertEqual((session["state"], session["waiting_for"]), ("stopped", "usage limit"))
        self.assertEqual((session["due"], session["eta_source"]), (resets, "limit"))
        [line] = [line for line in eta.render_sessions([session], now).splitlines() if line.startswith("stopped")]
        self.assertIn("(usage limit)", line)
        # The command from the failed turn ends with it, so the thread rests once the window resets.
        [session] = self.view(now + 11)
        self.assertEqual((session["state"], session["tasks"]), ("stopped", []))
        self.assertFalse(pathlib.Path(self.dir, "codex-call_1.json").exists())
        # Once the window resets, the thread rests since its failed turn ended, not since the reset.
        ended = eta.parse_stamp(stamp)
        [session] = self.view(resets + 1)
        self.assertEqual((session["state"], session["since"], session["due"]), ("idle", ended, None))
        self.assertFalse(eta.dormant(session, resets + 1))
        self.assertTrue(eta.dormant(session, ended + eta.DORMANT_AFTER + 1))
        with rollout.open("a") as handle:
            handle.write(event(type="task_started", turn_id="t-2"))
        self.assertEqual([s["state"] for s in self.view(now)], ["working"])

    def test_an_account_at_its_usage_limit_stops_its_resting_sessions(self):
        now = time.time()
        private = self.second_account()
        idle, waiting, working = self.sleeper(), self.sleeper(), self.sleeper()
        self.register(idle.pid, "idle", now - 600)
        self.register(waiting.pid, "waiting", now - 60, waitingFor="permission")
        self.register(working.pid, "busy", now - 30)
        self.register(status="idle", since=now - 900)
        os.rename(self.claude / "sessions" / ("%d.json" % os.getpid()), private / "sessions" / ("%d.json" % os.getpid()))
        old = self.sleeper()
        self.register(old.pid, "idle", now - 2 * eta.DORMANT_AFTER)
        reset = int(now + 3 * 3600)
        (self.claude / "usage-state.json").write_text(json.dumps({"windows_seen_at": now, "windows": {
            "five_hour": {"used_percentage": 100.0, "resets_at": reset},
            "seven_day": {"used_percentage": 40.0, "resets_at": now + 86400}}}))
        sessions = {s["pid"]: s for s in self.view(now)}
        for pid in (idle.pid, waiting.pid):
            self.assertEqual((sessions[pid]["state"], sessions[pid]["waiting_for"], sessions[pid]["due"]),
                             ("stopped", "usage limit", reset))
        # A working session may run on extra usage, and the other account has room left.
        self.assertEqual(sessions[working.pid]["state"], "working")
        self.assertEqual(sessions[os.getpid()]["state"], "idle")
        self.assertTrue(eta.dormant(sessions[old.pid], now))
        text = eta.render_sessions(self.view(now), now).split(eta.SECTION_RULE + "\n")
        self.assertEqual(sorted(line.split()[1] for line in text[2].splitlines()), ["10m", "1m"])
        self.assertTrue(all(line.endswith("(usage limit)") for line in text[2].splitlines()))
        self.assertFalse(any(eta.dormant(s, now + 2 * eta.DORMANT_AFTER) for s in self.view(now)
                             if s["state"] == "stopped"))
        # Once the window has reset, the reading says nothing any more and the sessions rest again.
        self.assertEqual(sorted(s["state"] for s in self.view(reset + 1)),
                         ["idle", "idle", "idle", "waiting", "working"])

    def test_codex_usage_limit_below_a_full_window_waits_for_the_fullest_one(self):
        # Codex stopped two threads on 2026-10-14 with the 5-hour window at 99% and 97%.
        folder = self.codex / "sessions" / "2026" / "10" / "14"
        folder.mkdir(parents=True)
        rollout = folder / "rollout-2026-10-14T22-28-28-thread-1.jsonl"
        now = time.time()
        resets = int(now) + 360
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - 5))
        def event(**payload):
            return json.dumps({"timestamp": stamp, "type": "event_msg", "payload": payload}) + "\n"
        limits = {"limit_id": "codex", "primary": {"used_percent": 99.0, "resets_at": resets},
                  "secondary": {"used_percent": 16.0, "resets_at": resets + 86400}}
        rollout.write_text(event(type="task_started", turn_id="t-1"))
        self.hook(self.codex_event("UserPromptSubmit"))
        with rollout.open("a") as handle:
            handle.write(event(type="token_count", rate_limits=limits) +
                         event(type="token_count", rate_limits={"limit_id": "premium", "primary": None}) +
                         event(type="task_complete", turn_id="t-1",
                               error={"message": "out of credits", "codex_error_info": "usage_limit_exceeded"}))
        [session] = self.view(now)
        self.assertEqual((session["state"], session["waiting_for"], session["due"]), ("stopped", "usage limit", resets))
        self.assertEqual(eta.section(session), 2)
        [session] = self.view(resets + 1)
        self.assertEqual((session["state"], session["since"], session["due"]), ("idle", eta.parse_stamp(stamp), None))

    def test_an_archived_codex_thread_is_left_out_until_unarchived(self):
        import sqlite3
        connection = sqlite3.connect(str(self.codex / "state_5.sqlite"))
        connection.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT, rollout_path TEXT, archived INTEGER)")
        connection.executemany("INSERT INTO threads VALUES (?, ?, ?, ?, ?)", [
            ("thread-1", "Kept", "kept", "/nope", 0), ("thread-2", "Archived", "archived", "/nope", 1)])
        connection.commit()
        self.hook(self.codex_event("Stop"))
        self.hook(self.codex_event("Stop", thread="thread-2"))
        self.assertEqual([s["name"] for s in self.view()], ["Kept"])
        connection.execute("UPDATE threads SET archived = 0 WHERE id = 'thread-2'")
        connection.commit()
        connection.close()
        self.assertEqual(sorted(s["name"] for s in self.view()), ["Archived", "Kept"])

    def test_fullest_reset_takes_the_window_closest_to_its_limit(self):
        self.assertIsNone(eta.fullest_reset({"limit_id": "premium", "primary": None, "secondary": None}))
        self.assertIsNone(eta.fullest_reset(None))
        self.assertEqual(eta.fullest_reset({"primary": {"used_percent": 99, "resets_at": 5},
                                            "secondary": {"used_percent": 16, "resets_at": 9}}), 5)
        self.assertEqual(eta.fullest_reset({"primary": {"used_percent": 40, "resets_at": 5},
                                            "secondary": {"used_percent": 100, "resets_at": 9}}), 9)

    def test_exhausted_until_takes_the_latest_full_window(self):
        self.assertIsNone(eta.exhausted_until({"limit_id": "premium", "primary": None}))
        self.assertEqual(eta.exhausted_until({"primary": {"used_percent": 40, "resets_at": 5}}), 0)
        self.assertEqual(eta.exhausted_until({"primary": {"used_percent": 100, "resets_at": 5},
                                              "secondary": {"used_percent": 100, "resets_at": 9}}), 9)

    def test_dormant_sessions_are_counted_and_listed_apart_with_all(self):
        now = time.time()
        old, busy = self.sleeper(), self.sleeper()
        self.register(old.pid, "idle", now - eta.DORMANT_AFTER - 60)
        self.register(busy.pid, "busy", now - 60)
        self.register(status="idle", since=now - eta.DORMANT_AFTER - 60)
        self.put("ci", agent="claude", eta=600, session={"pid": os.getpid()}, now=now)
        sessions = self.view(now)
        self.assertEqual([eta.dormant(s, now) for s in sessions], [False, False, True])
        short = eta.render_sessions(sessions, now)
        self.assertNotIn("session-%d" % old.pid, short)
        self.assertIn("1 dormant session, idle for more than %dh. agent-eta --all lists it." % (eta.DORMANT_AFTER // 3600),
                      short)
        full = eta.render_sessions(sessions, now, show_dormant=True).splitlines()
        rule = len(full) - 1 - full[::-1].index(eta.SECTION_RULE)
        self.assertIn("session-%d" % old.pid, full[rule + 1])
        self.assertTrue(all("session-%d" % old.pid not in line for line in full[:rule]))
        data = json.loads(self.cli("--json").stdout)
        self.assertEqual(sorted(s["dormant"] for s in data["sessions"]), [False, False, True])

    def test_only_dormant_sessions_say_so(self):
        now = time.time()
        self.register(status="idle", since=now - eta.DORMANT_AFTER - 60)
        text = eta.render_sessions(self.view(now), now)
        self.assertIn("(no waiting or idle sessions)", text)
        self.assertIn("(no working sessions)", text)
        self.assertIn("1 dormant session", text)

    def test_a_session_that_never_ran_a_turn_is_dormant_at_once(self):
        # PhpStorm's pre-started agent-SDK processes write a record without a status and no transcript.
        now = time.time()
        unused = self.sleeper()
        self.register(unused.pid, status=None, since=now - 60, entrypoint="sdk-ts")
        [session] = self.view(now)
        self.assertEqual((session["state"], session["unused"]), ("idle", True))
        self.assertTrue(eta.dormant(session, now))
        self.assertIn("1 dormant session", eta.render_sessions([session], now))

    def test_a_status_less_session_with_a_transcript_stays_unknown(self):
        now = time.time()
        used = self.sleeper()
        self.register(used.pid, status=None, since=now - 60)
        transcripts = self.claude / "projects" / "-work"
        transcripts.mkdir(parents=True)
        (transcripts / ("s-%d.jsonl" % used.pid)).write_text("")
        [session] = self.view(now)
        self.assertEqual((session["state"], session["unused"]), ("unknown", False))
        self.assertFalse(eta.dormant(session, now))

    def test_the_codex_memory_agent_is_never_listed(self):
        self.hook(self.codex_event("UserPromptSubmit", cwd=str(self.codex / "memories")))
        record = os.path.join(self.dir, "sessions", "codex-thread-1.json")
        self.assertTrue(os.path.exists(record))
        self.assertEqual(self.view(), [])
        self.assertFalse(os.path.exists(record))

    def test_a_codex_thread_in_the_state_database_is_no_memory_agent(self):
        import sqlite3
        connection = sqlite3.connect(str(self.codex / "state_5.sqlite"))
        connection.execute("CREATE TABLE threads (id TEXT, name TEXT, title TEXT, rollout_path TEXT)")
        connection.execute("INSERT INTO threads VALUES ('thread-1', 'Notes', 'notes', '/nope')")
        connection.commit()
        connection.close()
        self.hook(self.codex_event("UserPromptSubmit", cwd=str(self.codex / "memories")))
        [session] = self.view()
        self.assertEqual(session["name"], "Notes")

    def test_codex_interrupt_without_turn_id_is_still_codex(self):
        self.hook(self.codex_event("UserPromptSubmit"))
        self.hook({"hook_event_name": "Interrupt", "session_id": "thread-1"})
        self.assertEqual([s["state"] for s in self.view()], ["idle"])

    def test_a_silent_codex_thread_turns_idle_then_drops(self):
        self.hook(self.codex_event("UserPromptSubmit"))
        now = time.time()
        self.assertEqual([s["state"] for s in self.view(now + eta.SESSION_STALE + 5)], ["idle"])
        self.assertEqual(self.view(now + eta.SESSION_IDLE_TTL + 5), [])

    def test_claude_turn_eta_ends_with_the_turn(self):
        self.register(status="busy", since=time.time() - 5)
        env = dict(self.env, CLAUDECODE="1", CLAUDE_PID=str(os.getpid()))
        done = self.cli("turn", "--eta", "20m", "--label", "session view", env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        [session] = self.view()
        self.assertEqual((session["eta_source"], session["turn_label"]), ("turn", "session view"))
        self.assertAlmostEqual(session["remaining"], 1200, delta=5)
        self.assertAlmostEqual(session["eta_started"], time.time(), delta=5)
        self.assertLess(session["progress"], 0.01)
        self.register(status="idle", since=time.time() + 1)
        [session] = self.view()
        self.assertEqual((session["due"], session["turn_label"]), (None, None))
        self.assertEqual(os.listdir(os.path.join(self.dir, "turns")), [])

    def test_codex_turn_eta_ends_with_stop(self):
        self.hook(self.codex_event("UserPromptSubmit"))
        env = dict(self.env, CODEX_THREAD_ID="thread-1", CODEX_SANDBOX="seccomp")
        self.assertEqual(self.cli("turn", "--eta", "ca. 10 minutes", env=env).returncode, 0)
        self.assertEqual([s["eta_source"] for s in self.view()], ["turn"])
        self.hook(self.codex_event("Stop"))
        self.assertEqual([s["due"] for s in self.view()], [None])

    def test_turn_outside_a_session_fails(self):
        self.assertEqual(self.cli("turn", "--eta", "5m").returncode, 1)
        env = dict(self.env, CODEX_THREAD_ID="thread-1")
        self.assertEqual(self.cli("turn", env=env).returncode, 2)
        self.assertEqual(self.cli("turn", "--done", env=env).returncode, 0)

    def test_json_names_the_tasks_of_each_session(self):
        self.put("ci", agent="local", eta=600)
        data = json.loads(self.cli("--json").stdout)
        self.assertEqual([s["tasks"] for s in data["sessions"]], [["ci"]])
        self.assertEqual([t["id"] for t in data["tasks"]], ["ci"])

    def test_json_carries_section_progress_lineage_and_project(self):
        child = self.sleeper()
        repo = self.root / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        (repo / "src").mkdir()
        self.register(pid=child.pid, status="waiting", cwd=str(repo / "src"))
        self.register(status="idle", since=time.time() - eta.DORMANT_AFTER - 60)
        holder = {"type": "pid", "pid": child.pid, "start": eta.proc_start(child.pid)}
        self.put("ci", agent="local", eta=600, now=time.time() - 300, holder=holder)
        data = json.loads(self.cli("--json").stdout)
        by_state = {s["state"]: s for s in data["sessions"]}
        waiting, local, idle = by_state["waiting"], by_state["working"], by_state["idle"]
        self.assertEqual([s["section"] for s in (waiting, local, idle)], [0, 1, eta.DORMANT_SECTION])
        self.assertEqual(waiting["pids"][:2], [child.pid, os.getpid()])
        self.assertNotIn(1, waiting["pids"])
        self.assertEqual((waiting["project_root"], waiting["project_name"]), (str(repo), "repo"))
        self.assertEqual((waiting["progress"], waiting["eta_started"]), (None, None))
        self.assertEqual(local["pids"][0], child.pid)
        self.assertEqual(local["eta_started"], data["tasks"][0]["started"])
        self.assertAlmostEqual(local["progress"], 0.5, delta=0.02)
        self.assertAlmostEqual(data["tasks"][0]["progress"], 0.5, delta=0.02)

    def test_project_root_is_the_first_level_below_the_projects_or_the_repository(self):
        projects = self.root / "projects"
        (projects / "shop" / "app" / "code").mkdir(parents=True)
        (self.root / "plain").mkdir()
        self.assertEqual(eta.project_root(str(projects / "shop" / "app" / "code"), str(projects)),
                         str(projects / "shop"))
        self.assertEqual(eta.project_root(str(projects), str(projects)), str(projects))
        self.assertEqual(eta.project_root(str(self.root / "plain"), str(projects)), str(self.root / "plain"))
        (self.root / "plain" / ".git").mkdir()
        (self.root / "plain" / "sub").mkdir()
        self.assertEqual(eta.project_root(str(self.root / "plain" / "sub"), str(projects)),
                         str(self.root / "plain" / "sub"))
        self.assertIsNone(eta.project_root(None))

    def test_project_name_follows_a_phpstorm_rename(self):
        root = self.root / "shop"
        (root / ".idea").mkdir(parents=True)
        self.assertEqual(eta.project_name(str(root)), "shop")
        (root / ".idea" / ".name").write_text("Shop Live\n")
        self.assertEqual(eta.project_name(str(root)), "Shop Live")


class Usage(StateTest):
    def rollout(self, name, *readings):
        folder = self.codex / "sessions" / "2026" / "10" / "04"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / ("rollout-2026-10-04T00-00-00-%s.jsonl" % name)
        path.write_text("".join(json.dumps({"timestamp": stamp, "type": "event_msg",
                                            "payload": {"type": "token_count", "rate_limits": limits}}) + "\n"
                                for stamp, limits in readings))
        return path

    def test_claude_windows_come_from_the_statusline_state(self):
        now = 1_000_000
        (self.claude / "usage-state.json").write_text(json.dumps({"windows_seen_at": now - 120, "windows": {
            "five_hour": {"used_percentage": 62.0, "resets_at": now + 3 * 3600},
            "seven_day": {"used_percentage": 10.0, "resets_at": now + 6 * 86400}}}))
        five, seven = eta.usage_view(now)
        self.assertEqual((five["agent"], five["minutes"], five["used"], round(five["elapsed"]), five["ahead"]),
                         ("claude", 300, 62.0, 40, True))
        self.assertEqual((seven["minutes"], round(seven["elapsed"]), seven["ahead"]), (10080, 14, False))
        self.assertEqual((round(five["pace"]), five["remaining"], five["reached"]), (22, 3 * 3600, False))
        lines = eta.render_usage([five, seven], now).splitlines()
        self.assertEqual(lines[0].split(), ["USAGE", "USED", "ELAPSED", "PACE", "REMAINING", "DUE", "READ"])
        self.assertEqual(lines[1].split()[:6] + lines[1].split()[-1:],
                         ["claude", "62%", "-", "ahead", "+22%", "3h00", "2m"])
        self.assertEqual(lines[2].split()[:6], ["└", "5h", "62%", "40%", "ahead", "+22%"])
        self.assertEqual(lines[3].split()[:6], ["└", "7d", "10%", "14%", "ok", "-4%"])
        self.assertEqual(lines[4:], ["---", eta.EMPTY_USAGE[1]])

    def test_account_notes_fill_a_note_column_and_list_accounts_without_a_reading(self):
        now = 1_000_000
        window = eta.usage_window("claude/work", 300, 50.0, now + 3600, now - 60)
        [window] = eta.usage_view(now, [window])
        lines = eta.render_usage([window], now, {"claude/work": "Different account logged in",
                                                 "codex": "Not logged in"}).splitlines()
        self.assertEqual(lines[0].split()[-1], "NOTE")
        self.assertTrue(lines[1].startswith("claude/work") and lines[1].endswith("Different account logged in"))
        self.assertEqual(lines[-2], "---")
        self.assertEqual(lines[-1].split()[0], "codex")
        self.assertTrue(lines[-1].endswith("Not logged in"))
        self.assertEqual(eta.account_note({"auth_state": "authenticated", "usage_status": "current"}), "")
        self.assertEqual(eta.account_note({"auth_state": "unknown", "usage_status": "stale"}),
                         "Authentication unknown · Stale reading")

    def test_the_agent_row_holds_the_worst_per_column(self):
        now = 1_000_000
        (self.claude / "usage-state.json").write_text(json.dumps({"windows_seen_at": now, "windows": {
            "five_hour": {"used_percentage": 43.0, "resets_at": now + 3 * 3600},
            "seven_day": {"used_percentage": 88.0, "resets_at": now + 5 * 86400}}}))
        agent = eta.render_usage(eta.usage_view(now), now).splitlines()[1].split()
        # The 7-day window has the highest share and the worst pace, the 5-hour window the soonest reset.
        self.assertEqual(agent[:6], ["claude", "88%", "-", "ahead", "+59%", "3h00"])

    def test_each_account_has_a_usage_row_of_its_own(self):
        now = 1_000_000
        private = self.second_account()
        for directory, used in ((self.claude, 30.0), (private, 70.0)):
            (directory / "usage-state.json").write_text(json.dumps({"windows_seen_at": now, "windows": {
                "five_hour": {"used_percentage": used, "resets_at": now + 3600}}}))
        rows = [line.split()[:2] for line in eta.render_usage(eta.usage_view(now), now).splitlines()
                if line.startswith("claude")]
        self.assertEqual(sorted(rows), [["claude/private", "70%"], ["claude/work", "30%"]])

    def test_codex_takes_the_latest_reading_with_windows(self):
        now = 1_000_000
        codex = {"limit_id": "codex", "primary": {"used_percent": 39.0, "window_minutes": 300, "resets_at": now + 600},
                 "secondary": {"used_percent": 90.0, "window_minutes": 10080, "resets_at": now + 86400}}
        older = dict(codex, primary=dict(codex["primary"], used_percent=20.0))
        premium = {"limit_id": "premium", "primary": None, "secondary": None}
        self.rollout("a", ("2026-10-04T01:00:00.000Z", older))
        self.rollout("b", ("2026-10-04T01:45:00.000Z", codex), ("2026-10-04T01:46:00.000Z", premium))
        five, seven = [w for w in eta.usage_view(now) if w["agent"] == "codex"]
        self.assertEqual((five["minutes"], five["used"], round(five["elapsed"])), (300, 39.0, 97))
        self.assertEqual(five["seen_at"], eta.parse_stamp("2026-10-04T01:45:00.000Z"))
        self.assertEqual((seven["minutes"], seven["used"], five["ahead"]), (10080, 90.0, False))

    def test_newer_rollouts_without_readings_do_not_hide_the_last_one(self):
        now = 1_000_000
        codex = {"limit_id": "codex", "primary": {"used_percent": 10.0, "window_minutes": 300, "resets_at": now + 600},
                 "secondary": {"used_percent": 100.0, "window_minutes": 10080, "resets_at": now + 86400}}
        old = self.rollout("real", ("2026-10-04T03:54:00.000Z", codex))
        os.utime(old, (now - 3600, now - 3600))
        for index in range(eta.USAGE_ROLLOUTS + 3):
            self.rollout("batch%d" % index, ("2026-10-04T13:19:00.000Z", None))
        windows = [w for w in eta.usage_view(now) if w["agent"] == "codex"]
        self.assertEqual([(w["minutes"], w["used"]) for w in windows], [(300, 10.0), (10080, 100.0)])

    def test_a_window_past_its_reset_is_unknown(self):
        now = 1_000_000
        (self.claude / "usage-state.json").write_text(json.dumps({"windows_seen_at": now - 7200, "windows": {
            "five_hour": {"used_percentage": 100.0, "resets_at": now - 60}}}))
        [window] = eta.usage_view(now)
        self.assertEqual((window["used"], window["elapsed"], window["ahead"]), (None, None, False))
        self.assertEqual(eta.render_usage([window], now).splitlines()[2].split(),
                         ["└", "5h", "?", "?", "?", "?", "?"])

    def test_sections_split_by_reached_limits_and_sort_by_reset(self):
        def window(agent, minutes, used, remaining):
            return {"agent": agent, "minutes": minutes, "used": used, "remaining": remaining,
                    "reached": used >= 100, "seen_at": None}
        windows = [window("later", 300, 10, 700), window("first", 10080, 80, 9000), window("first", 300, 20, 600),
                   window("late", 300, 100, 3000), window("soon", 300, 50, 900), window("soon", 10080, 100, 1200)]
        open_, blocked = eta.usage_sections(windows)
        self.assertEqual([(agent, summary["minutes"]) for agent, summary, _ in open_], [("first", 300), ("later", 300)])
        self.assertEqual([w["minutes"] for w in open_[0][2]], [300, 10080])
        self.assertEqual([(agent, summary["minutes"]) for agent, summary, _ in blocked], [("soon", 10080), ("late", 300)])
        self.assertEqual([w["minutes"] for w in blocked[0][2]], [300, 10080])

    def test_open_section_sorts_by_the_7_day_reset_before_the_5_hour_reset(self):
        def window(agent, minutes, used, remaining):
            return {"agent": agent, "minutes": minutes, "used": used, "remaining": remaining,
                    "reached": used >= 100, "seen_at": None}
        windows = [window("week-late", 300, 10, 100), window("week-late", 10080, 10, 9000),
                   window("tie-late", 300, 10, 800), window("tie-late", 10080, 10, 5000),
                   window("tie-soon", 300, 10, 700), window("tie-soon", 10080, 10, 5000),
                   window("no-week", 300, 10, 50),
                   window("unblocks-late", 300, 100, 3000), window("unblocks-late", 10080, 50, 4000),
                   window("unblocks-soon", 300, 100, 100), window("unblocks-soon", 10080, 50, 8000)]
        open_, blocked = eta.usage_sections(windows)
        self.assertEqual([agent for agent, _, _ in open_], ["tie-soon", "tie-late", "week-late", "no-week"])
        self.assertEqual([agent for agent, _, _ in blocked], ["unblocks-soon", "unblocks-late"])

    def test_blocked_section_sorts_by_the_end_of_the_block(self):
        def window(agent, minutes, used, remaining):
            return {"agent": agent, "minutes": minutes, "used": used, "remaining": remaining,
                    "reached": used >= 100, "seen_at": None}
        windows = [window("week-blocked", 300, 100, 100), window("week-blocked", 10080, 100, 9000),
                   window("hour-blocked", 300, 100, 2000), window("hour-blocked", 10080, 50, 3000),
                   window("tie-late", 300, 100, 500), window("tie-late", 10080, 50, 7000),
                   window("tie-soon", 300, 100, 500), window("tie-soon", 10080, 50, 6000)]
        _, blocked = eta.usage_sections(windows)
        self.assertEqual([agent for agent, _, _ in blocked], ["tie-soon", "tie-late", "hour-blocked", "week-blocked"])

    def test_json_carries_the_usage(self):
        (self.claude / "usage-state.json").write_text(json.dumps({"windows": {
            "five_hour": {"used_percentage": 5.0, "resets_at": time.time() + 3600}}}))
        [window] = json.loads(self.cli("--json").stdout)["usage"]
        self.assertEqual((window["agent"], window["minutes"], window["used"]), ("claude", 300, 5.0))



class CodexLimitTrigger(unittest.TestCase):
    """The Stop hook's handoff of a Codex thread at its usage threshold."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agent-eta-trigger-")
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.config = os.path.join(self.dir, "config.json")
        patcher = unittest.mock.patch.dict(os.environ, {"AGENT_ETA_CONFIG": self.config})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.proc = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (self.proc.kill(), self.proc.wait()))
        self.started = []
        self.record({"pid": self.proc.pid})

    def record(self, app):
        eta.write_atomic(eta.codex_session_path(self.dir, "t1"), {"id": "t1", "state": "idle", "app": app})

    def fire(self, used, minutes=300, resets_at=2000):
        usage = [eta.usage_window("codex", minutes, used, resets_at, 900)]
        return eta.codex_limit_trigger(self.dir, "t1", 1000, usage, lambda command, log: self.started.append(command))

    def test_a_window_at_its_threshold_starts_one_handoff(self):
        self.assertEqual(self.fire(89), "handoff-below")
        self.assertEqual(self.fire(90), "handoff-started")
        self.assertEqual(self.started[0][2:], ["handoff", "codex:t1", "--to", "claude", "--wait", "1800"])
        self.assertEqual(self.fire(95), "handoff-known")
        self.assertEqual(self.fire(94, minutes=10080), "handoff-below")
        self.assertEqual(self.fire(95, minutes=10080), "handoff-started")
        self.assertEqual(len(self.started), 2)

    def test_a_reset_window_triggers_nothing(self):
        self.assertEqual(self.fire(100, resets_at=500), "handoff-below")

    def test_the_config_sets_thresholds_and_can_switch_it_off(self):
        with open(self.config, "w") as handle:
            json.dump({"codex_handoff": {"five_hour_percent": 80, "weekly_percent": "x"}}, handle)
        self.assertEqual(self.fire(85), "handoff-started")
        self.assertEqual(eta.handoff_trigger_settings()["weekly_percent"], 95)
        with open(self.config, "w") as handle:
            json.dump({"codex_handoff": {"enabled": False}}, handle)
        self.assertEqual(self.fire(99, resets_at=3000), "handoff-off")

    def test_a_desktop_chat_is_skipped(self):
        self.record({})
        self.assertEqual(self.fire(99), "handoff-ungated")
        self.assertEqual(self.started, [])

if __name__ == "__main__":
    unittest.main()
