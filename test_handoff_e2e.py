"""End-to-end tests of `agent-eta handoff`: a real interactive bash in a pty runs the source as its foreground
job, the CLI runs as a subprocess with the real collectors and the real cgroup freezer, and only the terminal
and the Codex binary are fakes that stand outside the move."""

import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

import agent_eta_handoff as handoff

HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = "# Plan\n\n## Steps\n\n1. First\n2. Second\n3. Third\n\n## Verification\n\n- run it\n"
# The fake terminal checks the launcher, then writes a Codex rollout whose first user message carries the
# handoff ID behind 70 KiB of preamble, as the Codex CLI does. FAKE_TERMINAL=silent writes no rollout.
TERMINAL = r'''
import json, os, shlex, sys
tabs = sys.argv[-1]
folder = os.path.dirname(tabs)
with open(tabs) as handle:
    launch = handle.read().split("command: /bin/sh ", 1)[1].strip()
with open(launch) as handle:
    script = handle.read()
codex = os.environ["AGENT_ETA_CODEX_BIN"]
usable = shlex.quote(codex) in script and os.access(codex, os.X_OK)
with open(os.environ["FAKE_TERMINAL_LOG"], "a") as handle:
    handle.write(json.dumps({"id": os.path.basename(folder), "codex": usable}) + "\n")
if os.environ.get("FAKE_TERMINAL") == "silent" or not usable:
    sys.exit(0)
def message(role, text):
    return json.dumps({"type": "response_item", "payload": {"type": "message", "role": role,
                       "content": [{"type": "input_text", "text": text}]}}) + "\n"
day = os.path.join(os.environ["CODEX_HOME"], "sessions", "2026", "10", "20")
os.makedirs(day, exist_ok=True)
with open(os.path.join(day, "rollout-2026-10-20T04-22-30-x.jsonl"), "w") as handle:
    handle.write("".join(message("developer", "x" * 1000) for _ in range(70)))
    handle.write(message("user", "agent-eta handoff %s: you take over" % os.path.basename(folder)))
'''


def user_manager():
    """Why the freezer cases cannot run here, or None when they can."""
    if not shutil.which("bash"):
        return "bash is missing"
    if not shutil.which("busctl") or not shutil.which("systemctl"):
        return "systemd is missing"
    probe = subprocess.run(["systemctl", "--user", "show", "-P", "Version"], capture_output=True, text=True)
    if probe.returncode != 0 or not probe.stdout.strip():
        return "no systemd user manager"
    return None


def stat(pid):
    """State, process group and the terminal's foreground process group of pid."""
    with open("/proc/%d/stat" % pid) as handle:
        rest = handle.read().rsplit(")", 1)[1].split()
    return rest[0], int(rest[2]), int(rest[5])


def frozen(pid):
    """The scope that holds pid and whether the cgroup freezer holds it."""
    group = handoff.Env.cgroup(None, pid)
    with open("/sys/fs/cgroup%s/cgroup.events" % group) as handle:
        return os.path.basename(group), "frozen 1" in handle.read().splitlines()


@unittest.skipIf(user_manager(), user_manager())
class Handoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="agent-eta-e2e-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        for args in (["init", "-q", "-b", "feature/x"], ["commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.org"] + args,
                           check=True)
        self.account = os.path.join(self.tmp, "account")
        self.session_id = str(uuid.uuid4())
        self.progress = os.path.join(self.tmp, "progress", self.session_id + ".json")
        self.log = os.path.join(self.tmp, "terminal.log")
        self.root = os.path.join(self.tmp, "handoff")
        codex = self.write("bin/codex", "#!/bin/sh\nexit 0\n")
        os.chmod(codex, 0o755)
        terminal = self.write("bin/terminal.py", TERMINAL)
        self.env = dict(os.environ, AGENT_ETA_DIR=self.path("state"), AGENT_ETA_HANDOFF_DIR=self.root,
                        CODEX_HOME=self.path("codex"), DSH_HOME=self.path("dsh"), CLAUDE_CONFIG_DIR=self.account,
                        CLAUDE_ACCOUNTS_FILE=self.write("accounts.json", json.dumps(
                            {"accounts": [{"name": "work", "dir": self.account}]})),
                        CLAUDE_PLAN_PROGRESS_DIR=os.path.dirname(self.progress), AGENT_ETA_HANDOFF_NOTIFY="",
                        AGENT_ETA_HANDOFF_POLL="0.2", AGENT_ETA_CODEX_BIN=codex, FAKE_TERMINAL_LOG=self.log,
                        AGENT_ETA_HANDOFF_TERMINAL="%s %s" % (sys.executable, terminal))
        for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID"):
            self.env.pop(name, None)
        self.bash, self.fd = pty.fork()
        if self.bash == 0:
            os.chdir(self.repo)
            os.execvp("bash", ["bash", "--norc", "--noprofile", "-i"])
        self.addCleanup(self.kill)
        self.drain(1.0)
        os.write(self.fd, b"python3 -c 'import sys; sys.stdin.readline(); print(\"got\")'\n")
        self.job = self.wait_for(self.child)
        self.output = self.drain(0.3)

    def path(self, rel):
        return os.path.join(self.tmp, rel)

    def write(self, rel, text):
        path = rel if os.path.isabs(rel) else self.path(rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def kill(self):
        for pid in (getattr(self, "job", None), self.bash):
            try:
                os.kill(pid, signal.SIGKILL)
            except (OSError, TypeError):
                pass
        os.waitpid(self.bash, 0)
        os.close(self.fd)

    def drain(self, wait):
        out, end = b"", time.time() + wait
        while time.time() < end:
            if select.select([self.fd], [], [], 0.05)[0]:
                try:
                    data = os.read(self.fd, 4096)
                except OSError:
                    break
                out += data
        return out.decode(errors="replace")

    def wait_for(self, probe, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            found = probe()
            if found:
                return found
            time.sleep(0.05)
        self.fail("timed out waiting for %s" % probe.__name__)

    def child(self):
        with open("/proc/%d/task/%d/children" % (self.bash, self.bash)) as handle:
            pids = handle.read().split()
        return int(pids[0]) if pids else None

    def source(self, status, done):
        """Register the job as a Claude Code session with an approved plan, `done` of 3 steps finished."""
        plan = self.write("plan.md", PLAN)
        self.write(os.path.join(self.account, "sessions", "%d.json" % self.job), json.dumps({
            "pid": self.job, "sessionId": self.session_id, "status": status, "cwd": self.repo,
            "statusUpdatedAt": int(time.time() * 1000), "procStart": handoff.Env.proc_start(None, self.job)}))
        self.write(os.path.join(self.account, "projects", "x", self.session_id + ".jsonl"), json.dumps({
            "type": "user", "toolUseResult": {"filePath": plan, "plan": PLAN, "isAgent": False},
            "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                     "content": "User has approved your plan."}]}}) + "\n")
        self.write(self.progress, json.dumps({"approval": "toolu_1", "plan": plan, "done": done, "total": 3}))

    def handoff(self, **extra):
        return subprocess.Popen([sys.executable, os.path.join(HERE, "agent-eta"), "handoff",
                                 "claude:" + self.session_id, "--to", "codex", "--wait", "60"],
                                env=dict(self.env, **extra), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)

    def record(self):
        (folder,) = [name for name in os.listdir(self.root) if name not in ("locks",)]
        with open(os.path.join(self.root, folder, "status.json")) as handle:
            return json.load(handle)

    def finish(self, proc):
        out, err = proc.communicate(timeout=60)
        self.assertNotIn("Traceback", err)
        return self.record()

    def assert_usable(self):
        """The job runs in the terminal's foreground, was not stopped and reads the next line."""
        state, group, foreground = stat(self.job)
        self.assertEqual((group, False), (foreground, state == "T"))
        self.assertNotIn("Stopped", self.output + self.drain(0.3))
        os.write(self.fd, b"line\n")
        self.assertIn("got", self.drain(1.0))

    def test_a_completed_move_ends_the_source_and_hands_the_terminal_back(self):
        self.source("busy", 1)
        proc = self.handoff()
        time.sleep(1.0)
        self.source("idle", 2)
        record = self.finish(proc)
        self.assertEqual("completed", record["state"], record.get("error"))
        with open(os.path.join(self.root, record["id"], "plan.md")) as handle:
            text = handle.read()
        self.assertIn("- Progress: 2/3 steps done", text)
        self.assertIn("- Next step: 3. Third", text)
        with open(self.log) as handle:
            self.assertTrue(json.loads(handle.readline())["codex"])
        self.wait_for(lambda: not os.path.exists("/proc/%d" % self.job) or stat(self.job)[0] == "Z")
        self.assertIn("Hangup", self.drain(1.0))
        self.assertEqual(self.bash, stat(self.bash)[2])

    def test_a_registration_timeout_thaws_a_usable_source(self):
        self.source("idle", 1)
        record = self.finish(self.handoff(FAKE_TERMINAL="silent", AGENT_ETA_HANDOFF_REGISTER_TIMEOUT="2"))
        self.assertEqual("failed", record["state"])
        self.assertIn("did not register", record["error"])
        self.assert_usable()

    def test_a_cancel_thaws_a_usable_source(self):
        self.source("idle", 1)
        proc = self.handoff(FAKE_TERMINAL="silent")
        self.wait_for(lambda: os.path.exists(self.log))
        paused = frozen(self.job)
        proc.send_signal(signal.SIGTERM)
        record = self.finish(proc)
        self.assertEqual((handoff.scope(record), True), paused)
        self.assertEqual("cancelled", record["state"])
        self.assert_usable()


if __name__ == "__main__":
    unittest.main()
