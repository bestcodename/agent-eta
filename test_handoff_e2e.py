"""Real tmux, user scopes, freezer, CLI collectors and controller shutdown; fake providers only."""
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
import uuid
from unittest import mock

import agent_eta_handoff as handoff
import agent_eta_tmux as tmux

HERE = Path(__file__).resolve().parent
PROVIDER = '''#!/usr/bin/python3
import json,os,signal,sys,time,uuid
from pathlib import Path
pid=os.getpid()
root=Path(os.environ['FAKE_RECORDS'])
fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
record={'pid':pid,'start':fields[19],'tty':fields[4],'pgrp':fields[2],'tpgid':fields[5],
        'cgroup':Path(f'/proc/{pid}/cgroup').read_text(),'source_marker':os.getenv('CLAUDECODE'),
        'literal':os.getenv('AGENT_ETA_LITERAL_TEST')}
if sys.argv[1:] == ['source']:
    account=Path(os.environ['CLAUDE_CONFIG_DIR'])/'sessions'
    account.mkdir(parents=True,exist_ok=True)
    (account/f'{pid}.json').write_text(json.dumps({'pid':pid,'sessionId':os.environ['FAKE_SOURCE_ID'],
        'cwd':os.getcwd(),'status':'idle','startedAt':int(time.time()*1000)}))
    (root/'source.json').write_text(json.dumps(record))
else:
    (root/'destination.json').write_text(json.dumps(record))
    if os.environ.get('FAKE_REGISTER','yes') == 'yes':
        folder=Path(os.environ['CODEX_HOME'])/'sessions'/'test'
        folder.mkdir(parents=True,exist_ok=True)
        session_id=str(uuid.uuid4())
        state=Path(os.environ['AGENT_ETA_DIR'])/'sessions'
        state.mkdir(parents=True,exist_ok=True)
        (state/('codex-'+session_id+'.json')).write_text(json.dumps({'app':{'pid':pid,'start':fields[19]}}))
        (folder/'rollout.jsonl').write_text(json.dumps({'type':'session_meta','payload':{'id':session_id}})+'\\n'+json.dumps({'type':'response_item','payload':{
            'type':'message','role':'user','content':[{'type':'input_text','text':sys.argv[-1]}]}})+'\\n')
while True: signal.pause()
'''


def unavailable():
    if not shutil.which("tmux"):
        return "tmux is not installed"
    result = subprocess.run(["systemctl", "--user", "show", "-P", "Version"], capture_output=True, text=True)
    return None if result.returncode == 0 and result.stdout.strip() else "no systemd user manager"


@unittest.skipIf(unavailable(), unavailable())
class ManagedHandoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="eta-e2e-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.account = self.root / "account"
        self.account.mkdir()
        self.codex = self.root / "codex"
        self.codex.mkdir()
        (self.codex / "config.toml").write_text('[projects.' + json.dumps(str(self.repo)) + ']\ntrust_level="trusted"\n')
        self.provider = self.root / "provider"
        self.provider.write_text(PROVIDER)
        self.provider.chmod(0o700)
        self.source_id = str(uuid.uuid4())
        self.plan = self.root / "plan.md"
        self.plan.write_text("# Wait\n\nRemain interactive and wait for the user. No reply is required.\n")
        registry = self.root / "accounts.json"
        registry.write_text(json.dumps({"accounts": [{"name": "work", "dir": str(self.account)}]}))
        self.env = dict(os.environ, AGENT_ETA_DIR=str(self.root / "state"), CODEX_HOME=str(self.codex),
                        CLAUDE_ACCOUNTS_FILE=str(registry), AGENT_ETA_CODEX_BIN=str(self.provider),
                        AGENT_ETA_HANDOFF_DIR=str(self.root / "handoff"), AGENT_ETA_HANDOFF_NOTIFY="",
                        AGENT_ETA_HANDOFF_POLL="0.05", AGENT_ETA_HANDOFF_REGISTER_TIMEOUT="1",
                        FAKE_RECORDS=str(self.root), FAKE_SOURCE_ID=self.source_id, FAKE_REGISTER="yes",
                        AGENT_ETA_LITERAL_TEST='spaces "quotes" $HOME %s\nsecond line', AGENT_ETA_NO_REFRESH="1")
        self.patch = mock.patch.dict(os.environ, self.env)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.runtime = tmux.Runtime()
        self.owned = []
        self.addCleanup(self.cleanup)
        source = self.runtime.start([str(self.provider), "source"], self.repo,
                                    environment={"CLAUDE_CONFIG_DIR": str(self.account)})
        self.owned.append(source["id"])
        self.source_terminal = source
        self.source = self.wait(lambda: self.read("source.json"))
        self.assertEqual(self.source["pgrp"], self.source["tpgid"])

    def read(self, filename):
        try:
            return json.loads((self.root / filename).read_text())
        except (OSError, ValueError):
            return None

    def wait(self, function, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = function()
            if value:
                return value
            time.sleep(.05)
        self.fail("timed out waiting for fixture")

    def cleanup(self):
        for record in handoff.records(str(self.root / "handoff")) if (self.root / "handoff").exists() else []:
            if record.get("destination_id"):
                self.owned.append(record["destination_id"])
        for identifier in self.owned:
            try:
                self.runtime.stop(identifier)
            except tmux.TmuxError:
                pass

    def command(self):
        return [sys.executable, str(HERE / "agent-eta"), "handoff", "claude:" + self.source_id,
                "--to", "codex", "--plan", str(self.plan), "--wait", "2"]

    def finish(self, process):
        out, err = process.communicate(timeout=20)
        self.assertTrue(out.strip(), err)
        record = json.loads(out)
        return record

    def assert_source_live_and_thawed(self):
        self.assertEqual(tmux.proc_start(self.source["pid"]), self.source["start"])
        state = subprocess.run(["systemctl", "--user", "show", "-P", "FreezerState", self.source_terminal["scope"]], text=True, capture_output=True)
        self.assertNotEqual(state.stdout.strip(), "frozen")

    def test_completed_handoff_survives_controller_exit_and_viewer_detachment(self):
        other = self.runtime.start(["sleep", "120"], self.repo)
        self.owned.append(other["id"])
        controller = "agent-eta-test-controller-" + uuid.uuid4().hex + ".service"
        env_args = ["--setenv=" + name for name in self.env if name not in tmux.SERVICE_CONTEXT + tmux.INHERITED]
        process = subprocess.Popen(["systemd-run", "--user", "--collect", "--wait", "--pipe", "--quiet", "--unit=" + controller,
                                    *env_args, "--", *self.command()], env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        record = self.finish(process)
        self.assertEqual((process.returncode, record["state"]), (0, "completed"), record)
        self.assertIsNone(tmux.proc_start(self.source["pid"]))
        self.assertIsNone(self.runtime.pane(self.source_terminal))
        self.assertIsNotNone(self.runtime.pane(other))
        destination = self.wait(lambda: self.read("destination.json"))
        self.assertEqual(destination["literal"], self.env["AGENT_ETA_LITERAL_TEST"])
        self.assertIsNone(destination["source_marker"])
        self.assertNotEqual(destination["tty"], "0")
        self.assertEqual(destination["pgrp"], destination["tpgid"])
        self.assertNotIn(controller, destination["cgroup"])
        self.assertNotIn(self.source_terminal["scope"], destination["cgroup"])
        child, fd = pty.fork()
        if child == 0:
            os.environ["TERM"] = "xterm-256color"
            os.execvp("tmux", ["tmux", "-S", self.runtime.socket, "attach-session", "-t", record["destination_terminal"]["session"]])
        try:
            self.wait(self.runtime.clients)
            before = len(self.runtime.clients())
            result = self.runtime.attach(record["destination_terminal"])
            self.assertFalse(result["opened"])
            self.assertEqual(len(self.runtime.clients()), before)
        finally:
            os.kill(child, signal.SIGTERM)
            os.waitpid(child, 0)
            os.close(fd)
        self.assertEqual(tmux.proc_start(destination["pid"]), destination["start"])
        self.assertIsNotNone(self.runtime.find(destination["pid"], destination["start"]))

    def test_registration_timeout_cancels_destination_before_thawing_source(self):
        self.env["FAKE_REGISTER"] = "no"
        # The server retains the launch environment, so use an explicit fake that never registers.
        silent = self.root / "silent"
        silent.write_text(PROVIDER.replace("if os.environ.get('FAKE_REGISTER','yes') == 'yes':", "if False:"))
        silent.chmod(0o700)
        self.env["AGENT_ETA_CODEX_BIN"] = str(silent)
        process = subprocess.Popen(self.command(), env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        record = self.finish(process)
        self.assertEqual((process.returncode, record["state"], record["destination_cancelled"]), (1, "failed", True))
        destination = self.wait(lambda: self.read("destination.json"))
        self.assertIsNone(tmux.proc_start(destination["pid"]))
        self.assert_source_live_and_thawed()

    def test_cancel_confirms_destination_exit_and_thaws_source(self):
        self.env["AGENT_ETA_HANDOFF_REGISTER_TIMEOUT"] = "30"
        silent = self.root / "silent"
        silent.write_text(PROVIDER.replace("if os.environ.get('FAKE_REGISTER','yes') == 'yes':", "if False:"))
        silent.chmod(0o700)
        self.env["AGENT_ETA_CODEX_BIN"] = str(silent)
        process = subprocess.Popen(self.command(), env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.wait(lambda: self.read("destination.json"))
        process.terminate()
        record = self.finish(process)
        self.assertEqual((process.returncode, record["state"], record["destination_cancelled"]), (1, "cancelled", True))
        self.assertIsNone(tmux.proc_start(self.read("destination.json")["pid"]))
        self.assert_source_live_and_thawed()

    def test_last_pane_exit_collects_the_server_service(self):
        self.assertTrue(self.runtime.stop(self.source_terminal["id"]))
        self.wait(lambda: subprocess.run(["systemctl", "--user", "is-active", "--quiet", self.runtime.unit], capture_output=True).returncode != 0)

    def test_frozen_source_is_retired_without_resuming_it(self):
        subprocess.run(["systemctl", "--user", "freeze", self.source_terminal["scope"]], check=True, capture_output=True)
        self.assertTrue(self.runtime.stop(self.source_terminal["id"]))
        self.assertIsNone(tmux.proc_start(self.source["pid"]))
        self.assertIsNone(self.runtime.pane(self.source_terminal))


if __name__ == "__main__":
    unittest.main()
