"""Tests for agent_eta_handoff: plans, snapshots, commands and the gated move with real processes."""

import json
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from unittest import mock

import agent_eta_handoff as handoff

PLAN = """# Plan

## Steps

1. **First** (ca. 1 hour)
   - detail
2. Second
3. Third

## Verification

- run it
"""


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def jsonl(path, records):
    return write(path, "".join(json.dumps(record) + "\n" for record in records))


class StubEnv(handoff.Env):
    """An Env with a fake clock, a recorded terminal and freezer, and canned sessions and commands. The real
    freezer runs in test_handoff_e2e."""

    def __init__(self, sessions, commands=None, register_after=0):
        super().__init__(self.lookup, lambda: [("work", "/nonexistent")], out=self.collect)
        self.sessions = sessions
        self.commands = commands or {}
        self.register_after = register_after
        self.clock = 1_800_000_000.0
        self.opened, self.printed, self.notes, self.ran, self.events = [], [], [], [], []
        self.frozen = set()
        # What trust() answers, one per call, and None once they are used up. The real lookup runs in Trust.
        self.trust_answers = []

    def lookup(self, source):
        session = self.sessions.get("%s:%s" % source)
        return session(self) if callable(session) else session

    def collect(self, text):
        self.printed.append(json.loads(text))

    def run(self, argv, timeout=60, cwd=None):
        self.ran.append(argv)
        for prefix, result in self.commands.items():
            if tuple(argv[:len(prefix)]) == prefix:
                code, out = result
                return subprocess.CompletedProcess(argv, code, out, "stub failed" if code else "")
        return super().run(argv, timeout, cwd)

    def freeze(self, unit, pid):
        self.frozen.add(unit)
        self.events.append("freeze")

    def resume(self, unit):
        if unit in self.frozen:
            self.frozen.discard(unit)
            self.events.append("thaw")
        return True

    def signal(self, pid, start, signum):
        self.events.append(signal.Signals(signum).name)
        return super().signal(pid, start, signum)

    def open_terminal(self, tabs):
        with open(tabs, "r", encoding="utf-8") as handle:
            self.opened.append(handle.read())

    def registered(self, record):
        return len(self.opened) > 0 and self.clock >= record["launched"] + self.register_after

    def trust(self, target, account, cwd):
        return self.trust_answers.pop(0) if self.trust_answers else None

    def notify(self, text):
        self.notes.append(text)

    def sleep(self, seconds):
        self.clock += seconds

    def now(self):
        return self.clock


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-eta-handoff-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "handoff")
        os.makedirs(self.root)
        self.repo = os.path.join(self.tmp, "repo with 'quotes'")
        os.makedirs(self.repo)
        git = ["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.org"]
        subprocess.run(git + ["init", "-q", "-b", "feature/x"], check=True)
        write(os.path.join(self.repo, "a.txt"), "a\n")
        subprocess.run(git + ["add", "a.txt"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "init"], check=True)
        self.plan = write(os.path.join(self.tmp, "plan.md"), PLAN)
        self.codex = write(os.path.join(self.tmp, "bin", "codex"), "#!/bin/sh\nexit 1\n")
        os.chmod(self.codex, 0o755)
        # No test reads the real trust records of the clients.
        self.home, self.codex_home = os.path.join(self.tmp, "home"), os.path.join(self.tmp, "codex")
        os.makedirs(self.home)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_PLAN_PROGRESS_DIR": os.path.join(self.tmp, "progress"),
                                               "AGENT_ETA_CODEX_BIN": self.codex, "HOME": self.home,
                                               "CODEX_HOME": self.codex_home})
        patcher.start()
        self.addCleanup(patcher.stop)

    def process(self):
        """A real source process that dies on SIGHUP, like a terminal session."""
        proc = subprocess.Popen(["sleep", "120"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        return proc

    def session(self, proc=None, **extra):
        pid = proc.pid if proc else None
        return dict({"state": "idle", "waiting_for": None, "running": False, "gate": pid,
                     "proc_start": handoff.Env.proc_start(None, pid) if pid else None, "pid": pid,
                     "cwd": self.repo, "account": "work", "transcript": None, "rollout": None}, **extra)


class Plans(Base):
    def test_steps_of_reads_top_level_items_under_steps_only(self):
        self.assertEqual(["First (ca. 1 hour)", "Second", "Third"], handoff.steps_of(PLAN))
        self.assertEqual([], handoff.steps_of("# x\n\n1. not a step\n"))

    def approval(self, call):
        return {"type": "user", "toolUseResult": {"filePath": self.plan, "plan": PLAN, "isAgent": False},
                "message": {"content": [{"type": "tool_result", "tool_use_id": call,
                                         "content": "User has approved your plan."}]}}

    def test_claude_plan_is_approved_only_with_the_recorded_approval(self):
        transcript = jsonl(os.path.join(self.tmp, "t.jsonl"), [self.approval("toolu_1")])
        write(os.path.join(self.tmp, "progress", "s1.json"),
              json.dumps({"approval": "toolu_1", "done": 1, "total": 3, "plan": self.plan}))
        found = handoff.claude_plan("s1", transcript)
        self.assertEqual(("implementation", True, 1, 3), (found["phase"], found["approved"], found["done"], found["total"]))
        write(os.path.join(self.tmp, "progress", "s1.json"), json.dumps({"approval": "toolu_9", "plan": self.plan}))
        self.assertIsNone(handoff.claude_plan("s1", transcript))

    def test_claude_plan_in_planning_comes_from_the_plan_mode_attachment(self):
        transcript = jsonl(os.path.join(self.tmp, "t.jsonl"), [
            {"type": "attachment", "attachment": {"type": "plan_mode", "planFilePath": self.plan}}])
        found = handoff.claude_plan("s2", transcript)
        self.assertEqual(("planning", False, self.plan), (found["phase"], found["approved"], found["path"]))

    def test_codex_plan_takes_the_latest_plan_and_a_later_default_turn_approves_it(self):
        def plan(text):
            return {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "Plan", "id": "p", "text": text}}}

        def turn(kind):
            return {"type": "event_msg", "payload": {"type": "task_started", "collaboration_mode_kind": kind}}
        rollout = jsonl(os.path.join(self.tmp, "r.jsonl"), [plan("old"), turn("default"), plan("new"), turn("plan")])
        found = handoff.codex_plan(rollout)
        self.assertEqual(("new", "planning"), (found["text"], found["phase"]))
        jsonl(rollout, [plan("new"), turn("default")])
        self.assertEqual("implementation", handoff.codex_plan(rollout)["phase"])
        self.assertIsNone(handoff.codex_plan(os.path.join(self.tmp, "missing.jsonl")))

    def test_a_missing_plan_comes_from_a_forked_one_shot_or_needs_preparation(self):
        env = StubEnv({"codex:t1": self.session(self.process())}, {(self.codex, "exec", "fork"): (0, "# Forked\n\n## Steps\n\n1. Go\n")})
        record, _, _, text = handoff.prepare(("codex", "t1"), "claude", "work", None, env, self.root, dry_run=True)
        self.assertEqual(("fork", "planning"), (record["plan_origin"], record["phase"]))
        self.assertIn("--permission-mode", record["command"])
        self.assertIn("# Forked", text)
        env = StubEnv({"codex:t1": self.session(self.process())}, {(self.codex, "exec", "fork"): (1, "")})
        with self.assertRaisesRegex(handoff.HandoffError, "preparation needed"):
            handoff.prepare(("codex", "t1"), "claude", "work", None, env, self.root, dry_run=True)


class Commands(Base):
    def test_destination_commands_follow_the_phase(self):
        for account, start in (("work", ["claude-account", "run", "work"]), (None, ["claude"])):
            self.assertEqual(start + ["--session-id", "u", "--permission-mode", "manual", "go"],
                             handoff.destination_command("claude", account, "/d", "u", True, "go"))
            self.assertEqual(start + ["--session-id", "u", "--permission-mode", "plan", "go"],
                             handoff.destination_command("claude", account, "/d", "u", False, "go"))
        record = {"id": "h-1", "source": "codex:t1"}
        approved = handoff.handover_prompt(record, "/p/plan.md", True)
        self.assertIn("The plan is approved", approved)
        self.assertNotIn("not approved", approved)
        self.assertIn("not approved yet", handoff.handover_prompt(record, "/p/plan.md", False))
        self.assertEqual([self.codex, "-C", "/d", "go"], handoff.destination_command("codex", None, "/d", None, True, "go"))
        self.assertEqual([self.codex, "-C", "/d", "-s", "read-only", "-a", "on-request", "go"],
                         handoff.destination_command("codex", None, "/d", None, False, "go"))

    def test_the_launcher_quotes_paths_drops_session_markers_and_runs_once(self):
        script = write(os.path.join(self.repo, "launch.sh"),
                       handoff.launcher(["sh", "-c", 'printf "%s|" "$1" "${CLAUDECODE-unset}"', "x", self.repo]))
        env = dict(os.environ, CLAUDECODE="1")
        out = subprocess.run(["/bin/sh", script], capture_output=True, text=True, env=env, check=True).stdout
        self.assertEqual("%s|unset|" % self.repo, out)
        with open(script) as handle:
            self.assertNotIn("printf \"%s|\"", handle.read())

    def test_the_snapshot_records_progress_next_step_and_a_dirty_tree(self):
        write(os.path.join(self.repo, "dirty file.txt"), "x")
        transcript = jsonl(os.path.join(self.tmp, "t.jsonl"), [Plans.approval(self, "toolu_1")])
        write(os.path.join(self.tmp, "progress", "s1.json"),
              json.dumps({"approval": "toolu_1", "done": 1, "total": 3, "plan": self.plan}))
        env = StubEnv({"claude:s1": self.session(self.process(), transcript=transcript)})
        record, _, _, _ = handoff.prepare(("claude", "s1"), "codex", None, None, env, self.root)
        folder = os.path.join(self.root, record["id"])
        self.assertEqual(0o700, os.stat(folder).st_mode & 0o777)
        with open(os.path.join(folder, "plan.md")) as handle:
            text = handle.read()
        self.assertIn("- Progress: 1/3 steps done", text)
        self.assertIn("- Next step: 2. Second", text)
        self.assertIn("feature/x at", text)
        self.assertIn("dirty file.txt", text)
        self.assertIn("plan's `## Verification` section", text)
        self.assertEqual([self.codex, "-C", self.repo], record["command"][:3])

    def test_the_desktop_bundle_starts_without_its_shared_server(self):
        link = os.path.join(self.tmp, "bin", "bundled")
        with mock.patch.object(handoff.agent_eta_providers, "DESKTOP_CODEX", os.path.realpath(self.codex)):
            os.symlink(self.codex, link)
            with mock.patch.dict(os.environ, {"AGENT_ETA_CODEX_BIN": link}):
                self.assertEqual([link, "--no-daemon", "-C", "/d", "go"],
                                 handoff.destination_command("codex", None, "/d", None, True, "go"))
        self.assertNotIn("--no-daemon", handoff.destination_command("codex", None, "/d", None, True, "go"))

    def test_codex_resolves_off_path_and_a_missing_one_refuses_before_anything_changes(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertEqual(self.codex, handoff.destination_command("codex", None, "/d", None, True, "go")[0])
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)})
        with mock.patch.dict(os.environ, {"AGENT_ETA_CODEX_BIN": os.path.join(self.tmp, "missing")}):
            code = handoff.run(["claude:s1"], "codex", plan_path=self.plan, env=env, root=self.root)
        self.assertEqual((1, "refused"), (code, env.printed[-1]["state"]))
        self.assertIn("codex executable is unavailable", env.printed[-1]["error"])
        self.assertEqual([], env.events)

    def test_a_codex_destination_registers_by_its_first_user_message(self):
        def message(role, text):
            return {"type": "response_item", "payload": {"type": "message", "role": role,
                                                         "content": [{"type": "input_text", "text": text}]}}
        preamble = [message("developer", "x" * 1000) for _ in range(70)]
        rollout = jsonl(os.path.join(self.tmp, "codex", "sessions", "2026", "10", "20", "rollout-x.jsonl"),
                        preamble + [message("user", "agent-eta handoff h-1: you take over")])
        self.assertGreater(os.path.getsize(rollout), 70 * 1024)
        self.assertTrue(handoff.prompted(rollout, "h-1"))
        self.assertFalse(handoff.prompted(rollout, "h-1", limit=64 * 1024))
        quoted = jsonl(os.path.join(self.tmp, "quoted.jsonl"), [
            message("developer", "h-1"), {"type": "response_item", "payload": {"type": "function_call_output",
                                                                               "output": "h-1"}}, "h-1"])
        self.assertFalse(handoff.prompted(quoted, "h-1"))
        with mock.patch.dict(os.environ, {"CODEX_HOME": os.path.join(self.tmp, "codex")}):
            env = handoff.Env(lambda source: None, lambda: [])
            self.assertTrue(env.registered({"target": "codex", "id": "h-1", "launched": time.time() - 1}))
            self.assertFalse(env.registered({"target": "codex", "id": "h-1", "launched": time.time() + 60}))

    def test_dry_run_writes_nothing(self):
        env = StubEnv({"claude:s1": self.session(self.process())})
        code = handoff.run(["claude:s1"], "codex", plan_path=self.plan, dry_run=True, env=env, root=self.root)
        self.assertEqual(0, code)
        self.assertEqual(["locks"] if os.path.exists(os.path.join(self.root, "locks")) else [], os.listdir(self.root))
        self.assertEqual("prepared", env.printed[0]["state"])
        self.assertEqual([], env.opened)

    def test_refusals(self):
        env = StubEnv({"codex:t1": self.session(gate=None, gate_reason="desktop chats cannot be gated")})
        code = handoff.run(["codex:t1", "nonsense", "codex:gone"], "claude", account="work", plan_path=self.plan,
                           env=env, root=self.root)
        self.assertEqual(1, code)
        self.assertEqual(["desktop chats cannot be gated", "a source is", "no running session"],
                         [next(part for part in ("desktop chats cannot be gated", "a source is", "no running session")
                               if part in result["error"]) for result in env.printed])

    def test_claude_to_claude_delegates_to_claude_account(self):
        env = StubEnv({"claude:s1": self.session(self.process())}, {("claude-account", "handoff"): (0, "moved")})
        code = handoff.run(["claude:s1"], "claude", account="private", wait=60, env=env, root=self.root)
        self.assertEqual(0, code)
        self.assertEqual(["claude-account", "handoff", "work", "private", "--only", "s1", "--wait", "60"], env.ran[-1])

    def test_the_account_comes_from_claude_account_targets(self):
        env = StubEnv({}, {("claude-account", "targets"): (0, json.dumps(
            {"targets": [{"name": "full", "eligible": False}, {"name": "free", "eligible": True}]}))})
        self.assertEqual("free", handoff.choose_account("claude", None, env))
        env = StubEnv({}, {("claude-account", "targets"): (1, "")})
        self.assertEqual("work", handoff.choose_account("claude", None, env))


class Transfer(Base):
    def run_one(self, env, wait=60):
        code = handoff.run(["claude:s1"], "codex", plan_path=self.plan, wait=wait, env=env, root=self.root)
        return code, env.printed[-1]

    def test_a_confirmed_destination_ends_the_source(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)}, register_after=3)
        code, result = self.run_one(env)
        self.assertEqual((0, "completed"), (code, result["state"]))
        self.assertEqual(-signal.SIGHUP, proc.wait(timeout=5))
        self.assertEqual(["freeze", "SIGHUP", "thaw"], env.events)
        self.assertIn("command: /bin/sh ", env.opened[0])
        with open(os.path.join(self.root, result["id"], "status.json")) as handle:
            self.assertEqual("completed", json.load(handle)["state"])

    def test_a_destination_that_never_registers_resumes_the_source(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)}, register_after=10 ** 6)
        code, result = self.run_one(env)
        self.assertEqual((1, "failed"), (code, result["state"]))
        self.assertIn("did not register", result["error"])
        self.assertEqual(["freeze", "thaw"], env.events)
        self.assertIsNone(proc.poll())

    def test_a_busy_source_is_left_alone_until_the_wait_ends(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc, state="working")})
        code, result = self.run_one(env, wait=30)
        self.assertEqual((1, "waiting"), (code, result["state"]))
        self.assertEqual([], env.opened)
        self.assertEqual([], env.events)

    def test_a_source_that_turns_busy_after_the_stop_is_resumed_and_waited_for(self):
        proc, calls = self.process(), []

        def flapping(env):
            calls.append(1)
            return self.session(proc, state="working" if len(calls) == 3 else "idle")
        env = StubEnv({"claude:s1": flapping})
        code, result = self.run_one(env)
        self.assertEqual((0, "completed"), (code, result["state"]))
        self.assertGreaterEqual(len(calls), 5)
        self.assertEqual(["freeze", "thaw", "freeze", "SIGHUP", "thaw"], env.events)

    def test_a_cancel_after_the_stop_resumes_the_source(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)})

        def cancel(tabs):
            self.assertEqual({handoff.scope(json.load(open(os.path.join(os.path.dirname(tabs), "status.json"))))},
                             env.frozen)
            raise KeyboardInterrupt
        env.open_terminal = cancel
        code, result = self.run_one(env)
        self.assertEqual((1, "cancelled"), (code, result["state"]))
        self.assertEqual(["freeze", "thaw"], env.events)
        self.assertIsNone(proc.poll())

    def test_any_error_after_the_pause_thaws_the_source_and_is_recorded(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)})

        def broken(tabs):
            raise ValueError("collector broke")
        env.open_terminal = broken
        with self.assertRaisesRegex(ValueError, "collector broke"):
            self.run_one(env)
        self.assertEqual(["freeze", "thaw"], env.events)
        self.assertIsNone(proc.poll())
        (folder,) = [name for name in os.listdir(self.root) if name != "locks"]
        with open(os.path.join(self.root, folder, "status.json")) as handle:
            record = json.load(handle)
        self.assertEqual(("failed", "ValueError: collector broke"), (record["state"], record["error"]))
        self.assertEqual("systemctl --user thaw %s" % handoff.scope(record), record["resume_source"])

    def test_a_source_that_stays_frozen_is_reported_with_its_recovery(self):
        env = StubEnv({"claude:s1": self.session(self.process())}, register_after=10 ** 6)
        env.resume = lambda unit: False
        code, result = self.run_one(env)
        self.assertEqual((1, "failed"), (code, result["state"]))
        self.assertIn("still frozen, run resume_source", result["error"])

    def test_sighup_to_the_handoff_cancels_like_sigterm(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)})
        env.open_terminal = lambda tabs: os.kill(os.getpid(), signal.SIGHUP)
        previous = signal.getsignal(signal.SIGHUP)
        code, result = self.run_one(env)
        self.assertEqual((1, "cancelled"), (code, result["state"]))
        self.assertEqual(previous, signal.getsignal(signal.SIGHUP))
        self.assertIsNone(proc.poll())

    def test_a_reused_pid_is_never_signalled(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc, proc_start="1")})
        code, result = self.run_one(env)
        self.assertEqual((1, "failed"), (code, result["state"]))
        self.assertIn("replaced", result["error"])
        self.assertEqual([], env.events)
        self.assertIsNone(proc.poll())

    def test_the_snapshot_is_refreshed_once_the_source_is_paused(self):
        transcript = jsonl(os.path.join(self.tmp, "t.jsonl"), [Plans.approval(self, "toolu_1")])
        progress = os.path.join(self.tmp, "progress", "s1.json")
        write(progress, json.dumps({"approval": "toolu_1", "done": 1, "total": 3, "plan": self.plan}))
        proc, calls = self.process(), []

        def working(env):
            calls.append(1)
            if len(calls) == 2:
                write(progress, json.dumps({"approval": "toolu_1", "done": 2, "total": 3, "plan": self.plan}))
                write(os.path.join(self.repo, "late.txt"), "x")
            return self.session(proc, transcript=transcript, state="working" if len(calls) == 2 else "idle")
        env = StubEnv({"claude:s1": working})
        code = handoff.run(["claude:s1"], "codex", env=env, root=self.root)
        result = env.printed[-1]
        self.assertEqual((0, "completed"), (code, result["state"]))
        with open(os.path.join(self.root, result["id"], "plan.md")) as handle:
            text = handle.read()
        self.assertIn("- Progress: 2/3 steps done", text)
        self.assertIn("- Next step: 3. Third", text)
        self.assertIn("late.txt", text)
        self.assertNotIn(".plan.md.tmp", os.listdir(os.path.join(self.root, result["id"])))

    def test_a_freezer_that_refuses_fails_the_move_before_anything_changes(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)}, {("busctl",): (1, "")})
        env.freeze = lambda unit, pid: handoff.Env.freeze(env, unit, pid)
        code, result = self.run_one(env)
        self.assertEqual((1, "failed"), (code, result["state"]))
        self.assertIn("cannot move into a scope", result["error"])
        self.assertEqual([], env.opened)
        self.assertIsNone(proc.poll())

    def test_a_repeated_request_reports_the_earlier_move(self):
        env = StubEnv({"claude:s1": self.session(self.process())})
        self.run_one(env)
        code, result = self.run_one(env)
        self.assertEqual("already handed off", result["note"])
        self.assertEqual(1, len(env.opened))

    def test_a_running_handoff_of_the_same_source_blocks_another(self):
        env = StubEnv({"claude:s1": self.session(self.process())})
        with handoff.SourceLock(self.root, ("claude", "s1")):
            code, result = self.run_one(env)
        self.assertEqual((1, "refused"), (code, result["state"]))
        self.assertIn("already running", result["error"])

    def test_a_batch_reports_each_source_separately(self):
        env = StubEnv({"claude:s1": self.session(self.process()), "claude:s2": self.session(self.process())})
        code = handoff.run(["claude:s1", "claude:s2", "claude:s3"], "codex", plan_path=self.plan, wait=10,
                           env=env, root=self.root)
        self.assertEqual(1, code)
        self.assertEqual(["completed", "completed", "refused"], [r["state"] for r in env.printed])
        self.assertEqual(3, len(env.notes))

    def test_an_untrusted_destination_is_refused_before_anything_runs(self):
        forked = {(self.codex, "exec", "fork"): (0, "# Forked\n\n## Steps\n\n1. Go\n")}
        for dry_run, notes in ((False, 1), (True, 0)):
            env = StubEnv({"codex:t1": self.session(self.process())}, forked)
            env.trust_answers = ["Claude Code does not trust it yet"]
            code = handoff.run(["codex:t1"], "claude", account="work", dry_run=dry_run, env=env, root=self.root)
            self.assertEqual((1, "refused", "Claude Code does not trust it yet"),
                             (code, env.printed[-1]["state"], env.printed[-1]["error"]))
            self.assertFalse([argv for argv in env.ran if argv[1:3] == ["exec", "fork"]])
            self.assertEqual(([], [], notes), (env.events, env.opened, len(env.notes)))
        self.assertEqual(["locks"], os.listdir(self.root))

    def test_trust_lost_while_waiting_fails_the_move_and_thaws_the_source(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)})
        env.trust_answers = [None, "Codex marks it as untrusted"]
        code, result = self.run_one(env)
        self.assertEqual((1, "failed", "Codex marks it as untrusted"), (code, result["state"], result["error"]))
        self.assertEqual((["freeze", "thaw"], []), (env.events, env.opened))
        self.assertIsNone(proc.poll())

    def moved(self, records, during=None, plan_path=None):
        """Hand claude:s1 to Codex while its fork would write a summary, running `during` while the move waits."""
        transcript = jsonl(os.path.join(self.tmp, "t.jsonl"), records)
        proc, calls = self.process(), []

        def waiting(env):
            calls.append(1)
            if len(calls) == 2 and during:
                during()
            return self.session(proc, transcript=transcript)
        env = StubEnv({"claude:s1": waiting},
                      {("claude-account", "run", "work", "--resume"): (0, "# Forked\n\n## Steps\n\n1. Go\n")})
        code = handoff.run(["claude:s1"], "codex", plan_path=plan_path, env=env, root=self.root)
        result = env.printed[-1]
        self.assertEqual((0, "completed"), (code, result["state"]))
        with open(os.path.join(self.root, result["id"], "plan.md")) as handle:
            return result, handle.read()

    def test_a_plan_the_source_writes_while_waiting_replaces_the_forked_summary(self):
        native = os.path.join(self.tmp, "plans", "native.md")
        attachment = {"type": "attachment", "attachment": {"type": "plan_mode", "planFilePath": native}}
        result, text = self.moved([attachment], lambda: write(native, "# Native\n\n## Steps\n\n1. Plan on\n"))
        self.assertEqual(("transcript", "planning"), (result["plan_origin"], result["phase"]))
        self.assertIn("# Native", text)
        self.assertNotIn("# Forked", text)
        self.assertIn("read-only", result["command"])

    def test_an_approval_recorded_while_waiting_replaces_the_forked_summary(self):
        progress = os.path.join(self.tmp, "progress", "s1.json")
        result, text = self.moved([Plans.approval(self, "toolu_1")], lambda: write(progress, json.dumps(
            {"approval": "toolu_1", "done": 1, "total": 3, "plan": self.plan})))
        self.assertEqual(("plan-progress", "implementation"), (result["plan_origin"], result["phase"]))
        self.assertIn("- Next step: 2. Second", text)
        self.assertNotIn("read-only", result["command"])

    def test_a_forked_summary_stays_without_a_plan_and_a_given_plan_stays_anyway(self):
        result, text = self.moved([])
        self.assertEqual(("fork", "planning"), (result["plan_origin"], result["phase"]))
        self.assertIn("# Forked", text)
        native = write(os.path.join(self.tmp, "plans", "native.md"), "# Native\n")
        attachment = {"type": "attachment", "attachment": {"type": "plan_mode", "planFilePath": native}}
        shutil.rmtree(self.root)
        os.makedirs(self.root)
        result, text = self.moved([attachment], plan_path=self.plan)
        self.assertEqual("option", result["plan_origin"])
        self.assertIn("# Plan", text)
        self.assertNotIn("# Native", text)


class Trust(Base):
    """The preflight against fixture records of both clients, which it reads without changing them."""

    def setUp(self):
        super().setUp()
        self.second = os.path.join(self.tmp, "second")
        self.env = handoff.Env(lambda source: None, lambda: [("main", os.path.join(self.home, ".claude")),
                                                             ("second", self.second)])

    def claude(self, path, accepted):
        return write(path, json.dumps({"oauthAccount": {"secret": "s3cr3t"}, "projects": {
            key: {"hasTrustDialogAccepted": value} for key, value in accepted.items()}}))

    def codex_config(self, levels):
        return write(os.path.join(self.codex_home, "config.toml"), "model = \"x\"\n" + "".join(
            "[projects.%s]\ntrust_level = %s\n" % (json.dumps(key), json.dumps(level)) for key, level in levels.items()))

    def files(self):
        found = {}
        for top in (self.home, self.codex_home, self.second):
            for folder, _, names in os.walk(top):
                for name in names:
                    with open(os.path.join(folder, name), "rb") as handle:
                        found[os.path.join(folder, name)] = handle.read()
        return found

    def trust(self, target, account, cwd):
        before = self.files()
        refusal = self.env.trust(target, account, cwd)
        self.assertEqual(before, self.files())
        return refusal

    def test_claude_reads_the_record_of_the_account_it_starts_in(self):
        self.claude(os.path.join(self.home, ".claude.json"), {self.repo: True})
        self.assertIsNone(self.trust("claude", "main", self.repo))
        self.assertIsNone(self.trust("claude", None, self.repo))
        refusal = self.trust("claude", "second", self.repo)
        self.assertIn("account second", refusal)
        self.assertIn("cd %s && claude-account run second" % shlex.quote(self.repo), refusal)
        self.claude(os.path.join(self.second, ".claude.json"), {self.repo: True})
        self.assertIsNone(self.trust("claude", "second", self.repo))
        self.assertIn("not registered", self.trust("claude", "other", self.repo))
        single = handoff.Env(lambda source: None, lambda: [(None, self.second)])
        self.assertIsNone(single.trust("claude", "second", self.repo))

    def test_claude_walks_up_to_the_repository_and_its_main_checkout(self):
        state = os.path.join(self.home, ".claude.json")
        deeper = os.path.join(self.repo, "sub", "deeper")
        os.makedirs(deeper)
        worktree = os.path.join(self.tmp, "worktree")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", "--detach", worktree], check=True)
        self.claude(state, {self.repo: True})
        for cwd in (deeper, worktree):
            self.assertIsNone(self.trust("claude", None, cwd))
        self.claude(state, {os.path.join(self.repo, "sub"): True})
        self.assertIsNone(self.trust("claude", None, deeper))
        self.assertIn("does not trust", self.trust("claude", None, self.repo))
        plain = os.path.join(self.tmp, "plain", "a", "b")
        os.makedirs(plain)
        self.claude(state, {os.path.join(self.tmp, "plain"): True, self.repo: False})
        self.assertIsNone(self.trust("claude", None, plain))
        self.assertIn("does not trust", self.trust("claude", None, self.repo))

    def test_claude_refuses_the_home_directory_and_unreadable_records(self):
        state = self.claude(os.path.join(self.home, ".claude.json"), {self.home: True})
        self.assertIn("for one session only", self.trust("claude", None, self.home))
        os.remove(state)
        self.assertIn("does not trust", self.trust("claude", None, self.repo))
        write(state, "{broken s3cr3t")
        refusal = self.trust("claude", None, self.repo)
        self.assertEqual("%s cannot be read" % state, refusal)

    def test_codex_needs_a_trusted_entry(self):
        refusal = self.trust("codex", None, self.repo)
        self.assertIn("run `%s -C %s` once" % (self.codex, shlex.quote(self.repo)), refusal)
        config = self.codex_config({self.repo: "trusted"})
        self.assertIsNone(self.trust("codex", None, self.repo))
        write(config, "[projects\ns3cr3t")
        self.assertEqual("%s cannot be read" % config, self.trust("codex", None, self.repo))

    def test_codex_takes_the_entry_of_the_directory_before_the_main_checkout(self):
        sub = os.path.join(self.repo, "sub")
        os.makedirs(sub)
        worktree = os.path.join(self.tmp, "worktree")
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", "--detach", worktree], check=True)
        self.codex_config({self.repo: "trusted"})
        for cwd in (sub, worktree):
            self.assertIsNone(self.trust("codex", None, cwd))
        self.codex_config({self.repo: "trusted", sub: "untrusted"})
        self.assertIn("marks %s as untrusted" % sub, self.trust("codex", None, sub))
        self.codex_config({self.repo: "untrusted", sub: "trusted"})
        self.assertIsNone(self.trust("codex", None, sub))
        self.assertIn("as untrusted", self.trust("codex", None, worktree))


if __name__ == "__main__":
    unittest.main()
