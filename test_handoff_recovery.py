"""Handoff recovery reports use lock ownership without changing live sessions."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

import agent_eta_handoff as handoff
from agent_eta_recovery import recovery_view
from test_agent_eta import eta


class Recovery(unittest.TestCase):
    def test_retry_of_abandoned_prepared_record_refuses_before_touching_processes(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "h1"
            folder.mkdir()
            handoff.write_record(str(folder), {"id": "h1", "source": "claude:s1", "state": "prepared"})
            inspect = mock.Mock(side_effect=AssertionError("must not inspect or move the source"))
            env = handoff.Env(inspect, lambda: [])
            with self.assertRaisesRegex(handoff.HandoffError, "unresolved ownership"):
                handoff.handoff_one("claude:s1", "codex", None, None, 1, False, env, root)
            inspect.assert_not_called()

    def test_batch_command_preserves_an_unnamed_account_directory(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(eta, "state_dir", return_value=root), \
                mock.patch.object(eta, "snapshot", return_value=SimpleNamespace(sessions=[{
                    "agent": "codex", "id": "thread", "dormant": False, "handoff": {"available": True}}])), \
                mock.patch.object(handoff, "handoff_root", return_value=root), \
                mock.patch.object(eta, "spawn_logged") as spawn:
            eta.handoff_batch("codex", "claude", None, account_directory="/selected account")
        command = spawn.call_args.args[0]
        self.assertEqual(command[-2:], ["--account-directory", "/selected account"])
        self.assertNotIn("--account", command)

    def test_completed_and_cleanly_failed_handoffs_do_not_need_recovery(self):
        for state in ("completed", "failed", "cancelled", "waiting"):
            record = {"source": "claude:s1", "state": state}
            with self.subTest(state=state):
                self.assertEqual(recovery_view(record, "/missing"), record)

    def test_unknown_controller_ownership_never_claims_interruption(self):
        record = {"source": "claude:s1", "state": "prepared", "source_paused": True}
        with mock.patch("agent_eta_recovery.controller_active", return_value=None):
            self.assertEqual(recovery_view(record, "/missing"), record)

    def test_missing_lock_reports_conservative_recovery_without_creating_files(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(subprocess, "run") as run:
            record = {"id": "h1", "source": "codex:s1", "state": "prepared"}
            result = recovery_view(record, root)
            self.assertTrue(result["recovery_required"])
            self.assertIn("may still be paused", result["error"])
            self.assertEqual(list(Path(root).iterdir()), [])
            run.assert_not_called()

    def test_sigkill_controller_is_reported_without_mutating_its_record(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / "h1"
            folder.mkdir()
            record = {"id": "h1", "source": "claude:s1", "target": "codex", "state": "launched",
                      "source_scope": "agent-eta-source.scope", "destination_id": "a" * 32,
                      "resume_source": "systemctl --user thaw agent-eta-source.scope"}
            handoff.write_record(str(folder), record)
            before = (folder / "status.json").read_bytes()
            code = ("import sys,time; import agent_eta_handoff as h; "
                    "lock=h.SourceLock(sys.argv[1],('claude','s1')); lock.__enter__(); "
                    "print('locked',flush=True); time.sleep(60)")
            child = subprocess.Popen([sys.executable, "-c", code, root], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "locked")
                self.assertNotEqual(handoff.latest_by_source(root)["claude:s1"]["state"], "interrupted")
                child.send_signal(signal.SIGKILL)
                child.wait(timeout=5)
                reported = handoff.latest_by_source(root)["claude:s1"]
                self.assertEqual(reported["state"], "interrupted")
                self.assertIn("Confirm", reported["error"])
                self.assertIn("destination", reported["error"])
                self.assertEqual((folder / "status.json").read_bytes(), before)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()
