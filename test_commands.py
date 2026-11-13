"""Native completion reconciliation without reading live sessions or running agents."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from agent_eta_commands import completed_commands, finished_tasks
from test_agent_eta import eta
from test_model import NOW, session, task


def completion(identifier, status="completed", kind="CommandExecution"):
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": kind, "id": identifier, "status": status, "exit_code": 0}}}


class Commands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "rollout.jsonl"

    def write(self, *records):
        self.path.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    def test_terminal_statuses_are_positive_evidence_even_outside_the_tail(self):
        self.write(completion("done"), completion("error", "failed"), completion("running", "inProgress"),
                   completion("other-tool", kind="McpToolCall"))
        with self.path.open("a") as handle:
            handle.write(json.dumps({"output": "x" * (eta.ROLLOUT_TAIL + 1)}) + "\n")
        self.assertEqual(completed_commands(self.path, {"done", "error", "running", "other-tool", "missing"}),
                         {"done", "error"})

    def test_unreadable_malformed_and_unrelated_records_never_prove_completion(self):
        self.write(None, [], {}, {"type": "event_msg", "payload": []},
                   {"type": "response_item", "payload": completion("done")["payload"]},
                   completion("unrequested"), completion(["invalid-id"]))
        with self.path.open("a") as handle:
            handle.write('{"CommandExecution": broken\n')
        self.assertEqual(completed_commands(self.path, {"done"}), set())
        self.assertEqual(completed_commands(None, {"done"}), set())
        self.assertEqual(completed_commands(self.root / "missing", {"done"}), set())

    def test_latest_native_status_wins(self):
        self.write(completion("same"), completion("same", "inProgress"))
        self.assertEqual(completed_commands(self.path, {"same"}), set())

    def test_only_pair_tasks_from_the_matching_thread_are_reconciled(self):
        self.write(completion("done"))
        owner = session(agent="codex")
        tasks = [task("codex-done", owner=owner, holder=holder) for holder in ("pair", "pid", "lock", "manual")]
        tasks += [task("codex-missing", owner=owner, holder="pair")]
        resolver = mock.Mock(return_value=str(self.path))
        self.assertEqual(finished_tasks(self.root, tasks, resolver), {"codex-done"})
        resolver.assert_called_once_with(owner["id"], None)
        other = task("codex-done", owner=session(agent="codex", id="other"), holder="pair")
        self.assertEqual(finished_tasks(self.root, [other], lambda thread, hint: None), set())

    def test_snapshot_deletes_completed_pair_task_while_owner_keeps_working(self):
        self.write(completion("done"))
        owner = session(agent="codex", state="working")
        done = task("codex-done", owner=owner, holder="pair")
        running = task("codex-running", owner=owner, holder="pair")
        reminder = task("reminder", owner=owner, holder="manual")
        for item in (done, running, reminder):
            (self.root / (item["id"] + ".json")).write_text(json.dumps(item))
        with mock.patch.object(eta, "require_process_view"), \
                mock.patch.object(eta, "codex_rollout", return_value=str(self.path)), \
                mock.patch.object(eta, "collect_sessions", return_value=([owner], [], {})), \
                mock.patch.object(eta, "handoff_gate", return_value=(None, None, None)), \
                mock.patch.object(eta, "handoff_records", return_value={}):
            snap = eta.snapshot(str(self.root), NOW, tasks=[done, running, reminder], usage=[])
        self.assertEqual({item["id"] for item in snap.tasks}, {"codex-running", "reminder"})
        self.assertFalse((self.root / "codex-done.json").exists())
        self.assertTrue((self.root / "codex-running.json").exists())
        self.assertTrue((self.root / "reminder.json").exists())
