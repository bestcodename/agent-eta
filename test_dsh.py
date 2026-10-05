#!/usr/bin/env python3
"""Tests for the dsh sessions of agent-eta.

Run with: python3 -m unittest discover -s scripts/agent-eta -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

from test_agent_eta import StateTest, eta

# A stand-in for `node /usr/local/bin/dsh web`. It holds every lock file it is given open, as dsh
# holds the lock of each session it has loaded, and sleeps.
FAKE_DSH = """import sys, time
handles = [open(path, "a") for path in sys.argv[1:] if path.endswith("session.lock")]
print("ready", flush=True)
time.sleep(60)
"""


def at(seconds):
    return int(seconds * 1000)


def record(kind, when, **data):
    return {"type": kind, "seq": 0, "time": at(when), "data": data}


def header(session_id, when, cwd="/work/shop"):
    return {"type": "session", "version": 3, "id": session_id, "createdAt": at(when), "cwd": cwd}


def bash(call_id, when, description="run the tests", command="composer test"):
    return record("tool/call", when, turn=1, step=1, callId=call_id, name="bash",
                  arguments=json.dumps({"command": command, "description": description}))


def result(call_id, when):
    return record("tool/result", when, turn=1, step=1,
                  message={"source": {"kind": "tool", "callId": call_id}, "content": [], "role": "user"})


class Summary(unittest.TestCase):
    """What dsh_summary reads from a log, without zstd."""

    def setUp(self):
        self.now = time.time()
        self.start = [header("session-1", self.now - 600), record("turn/start", self.now - 300, turn=1)]

    def summary(self, *records):
        return eta.dsh_summary(self.start + list(records))

    def test_an_open_turn_works_and_a_retry_says_why_it_is_slow(self):
        summary = self.summary(record("request/context", self.now - 290, provider="ollama", model="qwen3-coder"))
        self.assertEqual((summary["state"], summary["waiting_for"], summary["model"]), ("working", None, "qwen3-coder"))
        self.assertAlmostEqual(summary["since"], self.now - 300, places=2)
        retry = record("llm/retry", self.now - 10, turn=1, retry=2, maxRetries=5,
                       failure={"message": "stream idle timeout", "code": "TIMEOUT"})
        self.assertEqual(self.summary(retry)["waiting_for"], "retry 2/5 (TIMEOUT)")
        answered = record("assistant/message", self.now - 5, message={})
        self.assertIsNone(self.summary(retry, answered)["waiting_for"])

    def test_an_open_approval_question_or_plan_waits_for_the_user(self):
        asked = record("approval/asked", self.now - 60, id="a-1", toolName="bash")
        self.assertEqual(self.summary(asked)["waiting_for"], "permission")
        self.assertEqual(self.summary(asked, record("approval/decided", self.now - 50, id="a-1",
                                                    outcome="approved"))["state"], "working")
        question = record("tool/call", self.now - 40, callId="q-1", name="ask_user_question", arguments="{}")
        summary = self.summary(question)
        self.assertEqual((summary["state"], summary["waiting_for"]), ("waiting", "question"))
        self.assertAlmostEqual(summary["since"], self.now - 40, places=2)
        self.assertEqual(self.summary(question, result("q-1", self.now - 30))["state"], "working")
        plan = record("tool/call", self.now - 20, callId="p-1", name="exit_plan_mode", arguments="{}")
        self.assertEqual(self.summary(plan)["waiting_for"], "plan approval")

    def test_a_failed_turn_waits_and_a_finished_or_aborted_one_is_idle(self):
        def ended(**reason):
            return self.summary(record("turn/end", self.now - 100, turn=1, reason=reason))

        failed = ended(kind="error", error={"message": "pi-ai stream idle timeout", "code": "TIMEOUT"})
        self.assertEqual((failed["state"], failed["waiting_for"], failed["failed"]),
                         ("waiting", "turn failed (TIMEOUT)", True))
        self.assertEqual(ended(kind="max-tokens")["waiting_for"], "hit max tokens")
        for kind in ("completed", "aborted", "interrupted"):
            summary = ended(kind=kind)
            self.assertEqual((summary["state"], summary["waiting_for"], summary["failed"]), ("idle", None, False))
            self.assertAlmostEqual(summary["since"], self.now - 100, places=2)

    def test_a_running_bash_call_is_listed_until_its_result_or_the_turn_end(self):
        self.assertEqual([(c["call"], c["label"]) for c in self.summary(bash("c-1", self.now - 30))["bash"]],
                         [("c-1", "run the tests")])
        self.assertEqual(self.summary(bash("c-1", self.now - 30), result("c-1", self.now - 1))["bash"], [])
        self.assertEqual(self.summary(bash("c-1", self.now - 30),
                                      record("turn/end", self.now, turn=1, reason={"kind": "aborted"}))["bash"], [])
        unnamed = self.summary(bash("c-2", self.now - 30, description="", command="sleep 60\necho done"))
        self.assertEqual(unnamed["bash"][0]["label"], "sleep 60")

    def test_the_title_comes_from_dsh_then_the_goal_then_the_first_prompt(self):
        prompt = record("user/message", self.now - 299, source={"kind": "user"},
                        content=[{"type": "text", "text": "fix the build\nand more"}])
        goal = record("goal/change", self.now - 298, goal={"objective": "find the receipts"})
        title = record("session/title", self.now - 297, title="Fix the build", source={"kind": "provider"})
        self.assertEqual(self.summary(prompt)["title"], "fix the build")
        self.assertEqual(self.summary(prompt, goal)["title"], "find the receipts")
        self.assertEqual(self.summary(prompt, goal, title)["title"], "Fix the build")


class CommandLine(unittest.TestCase):
    def test_a_dsh_process_is_recognised_with_its_web_address(self):
        web = ["node", "/usr/local/bin/dsh", "web", "--patch", "/x/ollama.cordis.yml", "--no-open"]
        self.assertTrue(eta.is_dsh(web))
        self.assertEqual(eta.dsh_web_url(web), "http://127.0.0.1:3080/")
        self.assertEqual(eta.dsh_web_url(["dsh", "--profile", "web", "--port=4000", "--host", "localhost"]),
                         "http://localhost:4000/")
        self.assertIsNone(eta.dsh_web_url(["node", "/usr/local/bin/dsh", "--profile", "headless", "task"]))
        self.assertFalse(eta.is_dsh(["node", "/srv/app.js", "dsh"]))


@unittest.skipUnless(shutil.which("zstd") and shutil.which("zstdcat"), "zstd is not installed")
class Sessions(StateTest):
    def write_log(self, session_id, records, cwd="/work/shop"):
        """A session folder as dsh writes it, with the log as one zstd frame per record."""
        folder = self.dsh / "sessions" / ("-" + cwd.replace("/", "-") + "--") / session_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / eta.DSH_LOCK).touch()
        with open(folder / eta.DSH_LOG, "wb") as handle:
            for line in [header(session_id, time.time() - 900, cwd)] + records:
                handle.write(subprocess.run(["zstd", "-q", "-c"], input=(json.dumps(line) + "\n").encode(),
                                            capture_output=True, check=True).stdout)
        return folder

    def load(self, *folders, port="3999"):
        """A fake dsh web process that has these sessions loaded."""
        script = self.root / "bin" / "dsh"
        script.parent.mkdir(exist_ok=True)
        script.write_text(FAKE_DSH)
        child = subprocess.Popen([sys.executable, str(script), "web", "--port", port]
                                 + [str(folder / eta.DSH_LOCK) for folder in folders],
                                 stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    def view(self, now=None):
        return eta.sessions_view(self.dir, time.time() if now is None else now)

    def test_only_a_session_a_live_dsh_has_loaded_is_listed_with_its_running_calls(self):
        now = time.time()
        loaded = self.write_log("session-1", [record("turn/start", now - 120, turn=1),
                                              record("request/context", now - 119, model="qwen3-coder"),
                                              bash("c-old", now - 60), bash("c-new", now - 2, description="ls")])
        self.write_log("session-2", [], cwd="/work/other")
        child = self.load(loaded)
        sessions = self.view(now)
        self.assertEqual([(s["agent"], s["id"], s["state"]) for s in sessions], [("dsh", "session-1", "working")])
        session = sessions[0]
        self.assertEqual((session["pid"], session["web_url"], session["model"], session["cwd"]),
                         (child.pid, "http://127.0.0.1:3999/", "qwen3-coder", "/work/shop"))
        self.assertEqual([(t["id"], t["label"], t["due"]) for t in session["tasks"]],
                         [("dsh-c-old", "run the tests", None)])
        listed = eta.session_json(session, now)
        self.assertEqual(listed["pids"][0], child.pid)
        self.assertEqual(listed["section"], 1)

    def test_a_session_archived_in_the_web_ui_is_left_out_though_dsh_keeps_it_loaded(self):
        now = time.time()
        archived = self.write_log("session-1", [record("turn/start", now - 120, turn=1), bash("c-1", now - 60)])
        kept = self.write_log("session-2", [], cwd="/work/other")
        self.load(archived, kept)
        workspace = self.dsh / "storages" / "workspace.json"
        workspace.parent.mkdir()
        workspace.write_text(json.dumps({"global": {"archivedSessionIds": ["session-1"]}}))
        sessions = self.view(now)
        self.assertEqual([s["id"] for s in sessions], ["session-2"])
        self.assertEqual([t["id"] for s in sessions for t in s["tasks"]], [])
        workspace.write_text(json.dumps({"global": {"archivedSessionIds": []}}))
        self.assertEqual(sorted(s["id"] for s in self.view(now)), ["session-1", "session-2"])
        workspace.write_text("not json")
        self.assertEqual(len(self.view(now)), 2)

    def test_add_from_a_dsh_shell_attaches_to_its_session(self):
        folder = self.write_log("session-1", [record("turn/start", time.time() - 60, turn=1)])
        self.load(folder)
        env = dict(self.env, DSH_SESSION_ID="session-1")
        self.assertEqual(self.cli("add", "--eta", "10m", "--label", "CI", env=env).returncode, 0)
        os.environ["DSH_SESSION_ID"] = "session-1"
        self.assertEqual(eta.current_session(), ("dsh", {"id": "session-1"}))
        (session,) = self.view()
        self.assertEqual([t["label"] for t in session["tasks"]], ["CI"])
        self.assertEqual(session["eta_source"], "tasks")

    def test_a_log_is_decoded_again_only_once_it_changed(self):
        folder = self.write_log("session-1", [record("turn/start", time.time() - 60, turn=1)])
        self.load(folder)
        self.assertEqual(self.view()[0]["state"], "working")
        log = folder / eta.DSH_LOG
        info = log.stat()
        # Same size and mtime: the cached summary stands, even though the bytes say otherwise.
        log.write_bytes(b"x" * info.st_size)
        os.utime(log, ns=(info.st_atime_ns, info.st_mtime_ns))
        self.assertEqual(self.view()[0]["state"], "working")
        self.write_log("session-1", [record("turn/start", time.time() - 60, turn=1),
                                     record("turn/end", time.time() - 30, turn=1, reason={"kind": "completed"})])
        self.assertEqual(self.view()[0]["state"], "idle")

    def test_a_failed_turn_needs_you_until_it_has_rested_for_half_a_day(self):
        ended = time.time() - 60
        folder = self.write_log("session-1", [record("turn/start", ended - 60, turn=1), record(
            "turn/end", ended, turn=1, reason={"kind": "error", "error": {"code": "TIMEOUT"}})])
        self.load(folder)
        (session,) = self.view()
        self.assertEqual((session["state"], session["waiting_for"]), ("waiting", "turn failed (TIMEOUT)"))
        self.assertEqual(eta.section(session), 0)
        self.assertFalse(eta.dormant(session, time.time()))
        self.assertTrue(eta.dormant(session, ended + eta.DORMANT_AFTER + 1))

    def test_without_zstdcat_dsh_is_left_out(self):
        self.load(self.write_log("session-1", []))
        empty = tempfile.mkdtemp(dir=self.root)
        saved = os.environ["PATH"]
        os.environ["PATH"] = empty
        try:
            self.assertEqual(self.view(), [])
        finally:
            os.environ["PATH"] = saved


if __name__ == "__main__":
    unittest.main()
