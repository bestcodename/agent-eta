"""Tests for agent_eta_handoff: plans, snapshots, commands and the gated move with real processes."""

import json
import os
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
    """An Env with a fake clock, a recorded terminal and canned sessions and commands."""

    def __init__(self, sessions, commands=None, register_after=0):
        super().__init__(self.lookup, lambda: [("work", "/nonexistent")], out=self.collect)
        self.sessions = sessions
        self.commands = commands or {}
        self.register_after = register_after
        self.clock = 1_800_000_000.0
        self.opened, self.printed, self.notes, self.ran = [], [], [], []

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

    def open_terminal(self, tabs):
        with open(tabs, "r", encoding="utf-8") as handle:
            self.opened.append(handle.read())

    def registered(self, record):
        return len(self.opened) > 0 and self.clock >= record["launched"] + self.register_after

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
        patcher = mock.patch.dict(os.environ, {"CLAUDE_PLAN_PROGRESS_DIR": os.path.join(self.tmp, "progress")})
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

    def state(self, proc, expect=None):
        """The process state letter; with `expect`, waits up to a second for it, since signals land
        asynchronously."""
        for _ in range(100):
            with open("/proc/%d/stat" % proc.pid) as handle:
                found = handle.read().rsplit(")", 1)[1].split()[0]
            if expect is None or found == expect:
                return found
            time.sleep(0.01)
        return found


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
        env = StubEnv({"codex:t1": self.session(self.process())}, {("codex", "exec", "fork"): (0, "# Forked\n\n## Steps\n\n1. Go\n")})
        record, _, text = handoff.prepare(("codex", "t1"), "claude", "work", None, env, self.root, dry_run=True)
        self.assertEqual(("fork", "planning"), (record["plan_origin"], record["phase"]))
        self.assertIn("--permission-mode", record["command"])
        self.assertIn("# Forked", text)
        env = StubEnv({"codex:t1": self.session(self.process())}, {("codex", "exec", "fork"): (1, "")})
        with self.assertRaisesRegex(handoff.HandoffError, "preparation needed"):
            handoff.prepare(("codex", "t1"), "claude", "work", None, env, self.root, dry_run=True)


class Commands(Base):
    def test_destination_commands_follow_the_phase(self):
        self.assertEqual(["claude-account", "run", "work", "--session-id", "u", "go"],
                         handoff.destination_command("claude", "work", "/d", "u", True, "go"))
        self.assertEqual(["claude", "--session-id", "u", "--permission-mode", "plan", "go"],
                         handoff.destination_command("claude", None, "/d", "u", False, "go"))
        self.assertEqual(["codex", "-C", "/d", "go"], handoff.destination_command("codex", None, "/d", None, True, "go"))
        self.assertEqual(["codex", "-C", "/d", "-s", "read-only", "-a", "on-request", "go"],
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
        record, _, _ = handoff.prepare(("claude", "s1"), "codex", None, None, env, self.root)
        folder = os.path.join(self.root, record["id"])
        self.assertEqual(0o700, os.stat(folder).st_mode & 0o777)
        with open(os.path.join(folder, "plan.md")) as handle:
            text = handle.read()
        self.assertIn("- Progress: 1/3 steps done", text)
        self.assertIn("- Next step: 2. Second", text)
        self.assertIn("feature/x at", text)
        self.assertIn("dirty file.txt", text)
        self.assertIn("plan's `## Verification` section", text)
        self.assertEqual(["codex", "-C", self.repo], record["command"][:3])

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
        self.assertIn("command: /bin/sh ", env.opened[0])
        with open(os.path.join(self.root, result["id"], "status.json")) as handle:
            self.assertEqual("completed", json.load(handle)["state"])

    def test_a_destination_that_never_registers_resumes_the_source(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)}, register_after=10 ** 6)
        code, result = self.run_one(env)
        self.assertEqual((1, "failed"), (code, result["state"]))
        self.assertIn("did not register", result["error"])
        self.assertNotEqual("T", self.state(proc))
        self.assertIsNone(proc.poll())

    def test_a_busy_source_is_left_alone_until_the_wait_ends(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc, state="working")})
        code, result = self.run_one(env, wait=30)
        self.assertEqual((1, "waiting"), (code, result["state"]))
        self.assertEqual([], env.opened)
        self.assertNotEqual("T", self.state(proc))

    def test_a_source_that_turns_busy_after_the_stop_is_resumed_and_waited_for(self):
        proc, calls = self.process(), []

        def flapping(env):
            calls.append(1)
            return self.session(proc, state="working" if len(calls) == 2 else "idle")
        env = StubEnv({"claude:s1": flapping})
        code, result = self.run_one(env)
        self.assertEqual((0, "completed"), (code, result["state"]))
        self.assertGreaterEqual(len(calls), 4)

    def test_a_cancel_after_the_stop_resumes_the_source(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc)})

        def cancel(tabs):
            self.assertEqual("T", self.state(proc, "T"))
            raise KeyboardInterrupt
        env.open_terminal = cancel
        code, result = self.run_one(env)
        self.assertEqual((1, "cancelled"), (code, result["state"]))
        self.assertNotEqual("T", self.state(proc))
        self.assertIsNone(proc.poll())

    def test_a_reused_pid_is_never_signalled(self):
        proc = self.process()
        env = StubEnv({"claude:s1": self.session(proc, proc_start="1")})
        code, result = self.run_one(env)
        self.assertEqual((1, "failed"), (code, result["state"]))
        self.assertIn("replaced", result["error"])
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
        self.assertEqual(2, len(env.notes))


if __name__ == "__main__":
    unittest.main()
