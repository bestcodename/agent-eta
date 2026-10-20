#!/usr/bin/env python3
"""Tests for agent_eta_model, the pure rules behind every agent-eta surface.

Run with:  python3 -m unittest discover -s . -v

Every case builds its inputs as the collectors in agent-eta hand them over, so nothing here reads
files, processes or the clock.
"""

import copy
import json
import os
import pathlib
import unittest

import agent_eta_model as model

NOW = 1_760_000_000


def session(agent="claude", pid=100, state="idle", since=NOW - 60, **fields):
    found = {"agent": agent, "id": "s-%s" % pid, "pid": pid if agent == "claude" else None, "name": "session-%s" % pid,
             "state": state, "waiting_for": None, "since": since, "cwd": "/work"}
    found.update(fields)
    return found


def task(task_id, holder="pid", owner=None, started=NOW - 300, eta=600, **fields):
    found = {"version": 1, "id": task_id, "agent": (owner or {}).get("agent", "local"),
             "session": {"id": owner["id"], "pid": owner.get("pid")} if owner else {}, "cwd": "/work",
             "label": task_id, "started": started, "due": started + eta if eta is not None else None,
             "source": "add", "holder": {"type": holder} if holder else None, "session_name": task_id}
    found.update(fields)
    return found


def window(agent="claude", minutes=300, used=40.0, resets_in=3600, seen_at=NOW - 30):
    return {"agent": agent, "minutes": minutes, "used": used,
            "resets_at": NOW + resets_in if resets_in is not None else None, "seen_at": seen_at}


def build(**inputs):
    inputs.setdefault("sessions", [])
    inputs.setdefault("tasks", [])
    return model.build_snapshot(now=NOW, **inputs)


def by_key(snapshot):
    return {s["key"]: s for s in snapshot.sessions}


class Inputs(unittest.TestCase):
    def test_no_input_is_mutated(self):
        owner = session(state="idle")
        inputs = {"sessions": [owner, session(agent="codex", pid="t-1", state="working")],
                  "tasks": [task("ci", owner=owner), task("reminder", holder=None)],
                  "usage": [window(used=100.0), window(minutes=10080)],
                  "accounts": [{"id": "claude:default", "agent": "claude", "auth_state": "ok",
                                "usage_status": "current"}],
                  "turns": {("codex", "s-t-1"): {"due": NOW + 600, "started": NOW - 60, "label": "deploy"}}}
        before = copy.deepcopy(inputs)
        build(**inputs)
        self.assertEqual(inputs, before)

    def test_keys_name_sessions_tasks_windows_and_accounts(self):
        claude = session()
        snap = build(sessions=[claude, session(agent="codex", pid="t-1")], tasks=[task("lone")],
                     usage=[window()], accounts=[{"id": "claude:work", "agent": "claude/work"}])
        self.assertEqual(sorted(by_key(snap)), ["claude:100", "codex:s-t-1", "task:lone"])
        self.assertEqual(snap.tasks[0]["key"], "task:lone")
        self.assertEqual(snap.usage[0]["key"], "window:claude:300")
        self.assertEqual(snap.accounts[0]["key"], "account:claude:work")


class Activity(unittest.TestCase):
    def test_idle_owner_with_verified_work_is_working_and_keeps_its_report(self):
        for holder in ("pid", "lock", "pair"):
            with self.subTest(holder=holder):
                owner = session(state="idle")
                [found] = build(sessions=[owner], tasks=[task("job", holder=holder, owner=owner, started=NOW)]).sessions
                self.assertEqual((found["reported_state"], found["activity_state"], found["section"], found["light"]),
                                 ("idle", "working", 1, "active"))

    def test_a_reminder_without_owner_stays_unknown_and_adds_no_work(self):
        snap = build(tasks=[task("reminder", holder=None)])
        [found] = snap.sessions
        self.assertEqual((found["state"], found["activity_state"], found["section"]), ("unknown", "unknown", 0))
        self.assertEqual((snap.summary["working"], snap.summary["live"], snap.summary["light"]), (0, 0, "off"))

    def test_an_idle_owner_with_only_a_manual_wait_stays_idle(self):
        owner = session(state="idle")
        [found] = build(sessions=[owner], tasks=[task("wait", holder=None, owner=owner)]).sessions
        self.assertEqual((found["activity_state"], found["section"], found["light"]), ("idle", 0, "caution"))

    def test_a_pair_task_older_than_a_finished_turn_is_pruned(self):
        owner = session(agent="codex", pid="t-1", state="idle", since=NOW - 10)
        snap = build(sessions=[owner], tasks=[task("cmd", holder="pair", owner=owner, started=NOW - 100),
                                              task("live", holder="pid", owner=owner, started=NOW - 100)])
        self.assertEqual(snap.prune_tasks, ("cmd",))
        self.assertEqual([t["id"] for t in snap.tasks], ["live"])
        self.assertEqual(snap.sessions[0]["activity_state"], "working")

    def test_an_async_question_during_a_running_turn_needs_you_under_its_own_label(self):
        thread = session(agent="codex", pid="t-1", state="waiting", waiting_for="question",
                         reported_state="working", turn_running=True)
        snap = build(sessions=[thread])
        [found] = snap.sessions
        self.assertEqual((found["activity_state"], found["activity_label"], found["light"], found["section"]),
                         ("waiting", model.QUESTION_OPEN_LABEL, "attention", 0))
        self.assertEqual((snap.summary["waiting"], snap.summary["light"], snap.summary["badge_count"]),
                         (1, "attention", 1))

    def test_an_answered_question_without_a_running_turn_reads_waiting(self):
        [found] = build(sessions=[session(agent="codex", pid="t-1", state="waiting", waiting_for="question")]).sessions
        self.assertEqual(found["activity_label"], "waiting")

    def test_a_long_rest_is_dormant_and_left_out_of_summary_and_signals(self):
        snap = build(sessions=[session(state="idle", since=NOW - model.DORMANT_AFTER - 1)])
        self.assertEqual((snap.sessions[0]["section"], snap.summary["dormant"], snap.summary["live"]),
                         (model.DORMANT_SECTION, 1, 0))
        self.assertEqual([s for s in snap.signals if s["entity_key"] == "claude:100"], [])
        self.assertEqual(snap.sections[model.DORMANT_SECTION]["session_keys"], ["claude:100"])

    def test_an_account_at_its_limit_stops_its_resting_sessions_only(self):
        snap = build(sessions=[session(pid=1, state="idle"), session(pid=2, state="working")],
                     usage=[window(used=100.0, resets_in=1800)])
        found = by_key(snap)
        self.assertEqual((found["claude:1"]["state"], found["claude:1"]["resume_at"], found["claude:1"]["eta_source"]),
                         ("stopped", NOW + 1800, "limit"))
        self.assertEqual((found["claude:1"]["section"], found["claude:1"]["light"]), (2, "off"))
        self.assertEqual(found["claude:2"]["state"], "working")

    def test_a_running_turn_with_an_open_question_is_not_stopped_by_its_limit(self):
        thread = session(agent="codex", pid="t-1", state="waiting", waiting_for="question", turn_running=True)
        [found] = build(sessions=[thread], usage=[window("codex", used=100.0)]).sessions
        self.assertEqual((found["state"], found["activity_label"]), ("waiting", model.QUESTION_OPEN_LABEL))


class Eta(unittest.TestCase):
    def test_turn_eta_wins_over_tasks(self):
        owner = session(state="working")
        snap = build(sessions=[owner], tasks=[task("ci", owner=owner)],
                     turns={("claude", 100): {"due": NOW + 900, "started": NOW - 100, "label": "deploy"}})
        [found] = snap.sessions
        self.assertEqual((found["eta_source"], found["turn_label"], found["remaining"]), ("turn", "deploy", 900))

    def test_an_overdue_working_session_is_counted_and_turns_to_caution(self):
        owner = session(state="working")
        snap = build(sessions=[owner], turns={("claude", 100): {"due": NOW - 60, "started": NOW - 600}})
        self.assertEqual((snap.sessions[0]["light"], snap.summary["overdue"], snap.summary["light"]),
                         ("caution", 1, "caution"))
        [overdue] = [s for s in snap.signals if s["kind"] == "overdue"]
        self.assertEqual((overdue["active"], overdue["dedupe_key"]), (True, "overdue:claude:100:%d" % (NOW - 60)))

    def test_the_progress_session_is_the_working_one_due_first(self):
        first, second = session(pid=1, state="working"), session(pid=2, state="working")
        snap = build(sessions=[first, second],
                     turns={("claude", 1): {"due": NOW + 900, "started": NOW - 100},
                            ("claude", 2): {"due": NOW + 300, "started": NOW - 100}})
        self.assertEqual(snap.summary["progress_session_key"], "claude:2")

    def test_a_session_timed_by_its_tasks_leaves_overdue_to_the_task(self):
        owner = session(state="working")
        snap = build(sessions=[owner], tasks=[task("ci", owner=owner, started=NOW - 900, eta=600)])
        kinds = [(s["key"], s["active"]) for s in snap.signals if s["kind"] == "overdue"]
        self.assertEqual(kinds, [("overdue:task:ci", True)])

    def test_order_is_waiting_then_resting_then_working_then_stopped(self):
        snap = build(sessions=[session(pid=1, state="working"), session(pid=2, state="stopped", resume_at=NOW + 60),
                               session(pid=3, state="idle"), session(pid=4, state="waiting")])
        self.assertEqual([s["key"] for s in snap.sessions], ["claude:4", "claude:3", "claude:1", "claude:2"])
        self.assertEqual([len(s["session_keys"]) for s in snap.sections], [2, 1, 1, 0])


class Usage(unittest.TestCase):
    def test_groups_put_open_agents_before_blocked_ones_and_keep_unread_accounts(self):
        snap = build(usage=[window("claude", used=100.0, resets_in=600), window("codex", minutes=10080, resets_in=9000),
                            window("codex", minutes=300, resets_in=100)],
                     accounts=[{"id": "claude:other", "agent": "claude/other"}, {"id": "codex", "agent": "codex"}])
        groups = [(g["agent"], g["reached"], g["reset_window_key"]) for g in snap.usage_groups]
        self.assertEqual(groups, [("codex", False, "window:codex:300"), ("claude/other", False, None),
                                  ("claude", True, "window:claude:300")])
        self.assertEqual(snap.usage_groups[0]["window_keys"], ["window:codex:300", "window:codex:10080"])

    def test_a_window_past_its_reset_is_unknown_and_its_reset_signal_falls(self):
        snap = build(usage=[window(used=100.0, resets_in=-10)])
        [found] = snap.usage
        self.assertEqual((found["used"], found["reached"], found["remaining"]), (None, False, None))
        [reset] = [s for s in snap.signals if s["kind"] == "reset"]
        self.assertEqual((reset["active"], reset["edge"], reset["message_params"]["reading_pending"]),
                         (False, "falling", True))

    def test_signals_carry_their_contract_fields(self):
        snap = build(sessions=[session(state="waiting", waiting_for="permission")], usage=[window()])
        for signal in snap.signals:
            self.assertEqual(sorted(signal), ["active", "dedupe_key", "edge", "entity_key", "key", "kind",
                                              "message_params", "notify_on_new"])
        [waiting] = [s for s in snap.signals if s["kind"] == "waiting"]
        self.assertEqual((waiting["notify_on_new"], waiting["dedupe_key"], waiting["message_params"]["waiting_for"]),
                         (True, "waiting:claude:100:%d" % (NOW - 60), "permission"))

    def test_stamps_read_alike_for_ints_and_whole_floats(self):
        self.assertEqual((model.stamp(5.0), model.stamp(5), model.stamp(5.5), model.stamp(None)),
                         ("5", "5", "5.5", "None"))


FIXTURES = pathlib.Path(__file__).with_name("test_fixtures") / "contract-v1"


def mixed():
    """One of everything the widget shows."""
    idle_owner = session(pid=1, state="idle", name="idle owner of a build")
    working = session(pid=2, state="working", name="overdue turn", account="work")
    thread = session(agent="codex", pid="t-1", state="waiting", waiting_for="question", reported_state="working",
                     turn_running=True, name="question during a turn")
    return build(sessions=[idle_owner, working, thread,
                           session(pid=3, state="waiting", waiting_for="permission", name="permission"),
                           session(pid=4, state="idle", name="resting"),
                           session(pid=5, state="idle", since=NOW - model.DORMANT_AFTER - 60, name="dormant"),
                           session(agent="codex", pid="t-2", state="idle", name="stopped by codex limit")],
                 tasks=[task("build", owner=idle_owner, started=NOW - 120), task("reminder", holder=None)],
                 usage=[window("claude", 300, 55.0, 3000), window("claude", 10080, 20.0, 400000),
                        window("claude/work", 300, 30.0, 9000), window("codex", 300, 100.0, 1200),
                        window("codex", 10080, 70.0, 300000)],
                 accounts=[{"id": "claude:default", "provider": "claude", "agent": "claude", "name": None,
                            "auth_state": "ok", "usage_status": "current", "seen_at": NOW - 30},
                           {"id": "claude:work", "provider": "claude", "agent": "claude/work", "name": "work",
                            "auth_state": "unknown", "usage_status": "stale", "seen_at": NOW - 7200},
                           {"id": "codex", "provider": "codex", "agent": "codex", "name": None,
                            "auth_state": "ok", "usage_status": "current", "seen_at": NOW - 30}],
                 turns={("claude", 2): {"due": NOW - 120, "started": NOW - 1200, "label": "deploy"}})


def before():
    """The poll before after(): nothing waits, nothing ran over, and the Codex limit is reached."""
    owner = session(pid=2, state="working", name="turn")
    return build(sessions=[owner, session(pid=3, state="working", name="asks soon")],
                 tasks=[task("ci", owner=owner, started=NOW - 500, eta=600)],
                 usage=[window("codex", 300, 100.0, 60)],
                 turns={("claude", 2): {"due": NOW + 30, "started": NOW - 600}})


def after():
    """The poll after before(), 120 seconds on: one session waits, the turn and the task ran over,
    the Codex window reset without a fresh reading and a new session waits from the start."""
    later = NOW + 120
    owner = session(pid=2, state="working", name="turn")
    return model.build_snapshot(
        now=later, sessions=[owner, session(pid=3, state="waiting", since=later - 5, waiting_for="question",
                                            name="asks soon"),
                             session(pid=6, state="waiting", since=later - 3, name="new and waiting")],
        tasks=[task("ci", owner=owner, started=NOW - 500, eta=600)],
        usage=[window("codex", 300, 100.0, 60)],
        turns={("claude", 2): {"due": NOW + 30, "started": NOW - 600}})


SCENARIOS = {"empty": lambda: build(), "mixed": mixed, "signals-before": before, "signals-after": after}


class Contract(unittest.TestCase):
    def test_handoff_availability_comes_from_the_gate_and_the_latest_record(self):
        sessions = [{"agent": "claude", "id": "s1", "pid": 1, "name": "a", "state": "idle", "since": NOW, "cwd": "/w"},
                    {"agent": "codex", "id": "t1", "name": "b", "state": "idle", "since": NOW, "cwd": "/w",
                     "gate_reason": "desktop chats cannot be gated"}]
        result = model.build_snapshot(now=NOW, sessions=sessions, tasks=[{"id": "x", "agent": "other",
                                      "label": "run", "eta": NOW + 60, "started": NOW, "holder": {}}],
                                      handoffs={"claude:s1": {"id": "h1", "state": "failed", "target": "codex",
                                                              "error": "did not register"}})
        views = {s["key"]: s["handoff"] for s in result.sessions}
        self.assertEqual((True, ["codex", "claude"], "failed"),
                         (views["claude:1"]["available"], views["claude:1"]["targets"], views["claude:1"]["status"]["state"]))
        self.assertEqual((False, "desktop chats cannot be gated", ["claude"]),
                         (views["codex:t1"]["available"], views["codex:t1"]["reason"], views["codex:t1"]["targets"]))
        self.assertFalse(views["task:x"]["available"])

    def test_the_owner_of_tasks_without_a_live_session_offers_no_handoff(self):
        result = model.build_snapshot(now=NOW, sessions=[], tasks=[
            {"id": "x", "agent": "claude", "label": "run", "eta": NOW + 60, "started": NOW, "holder": {},
             "session": {"id": "s9"}}])
        (view,) = [s["handoff"] for s in result.sessions]
        self.assertEqual((False, "it has no running session"), (view["available"], view["reason"]))

    def test_the_listing_carries_schema_1(self):
        data = model.listing(mixed(), lambda s: {"pids": []})
        self.assertEqual(data["schema_version"], 1)
        for key in ("labels", "summary", "sections", "usage_groups", "notification_signals", "accounts"):
            self.assertIn(key, data)
        self.assertEqual(data["labels"]["dormant_after"], model.DORMANT_AFTER)
        self.assertTrue(all(isinstance(s["tasks"], list) and "pids" in s for s in data["sessions"]))
        known = {s["key"] for s in data["sessions"]}
        self.assertTrue(all(key in known for section in data["sections"] for key in section["session_keys"]))
        windows = {w["key"] for w in data["usage"]}
        self.assertTrue(all(key in windows for group in data["usage_groups"] for key in group["window_keys"]))
        json.dumps(data)

    def test_mixed_scenario_decides_what_the_widget_shows(self):
        snap = mixed()
        found = by_key(snap)
        self.assertEqual(found["claude:1"]["activity_state"], "working")
        self.assertEqual(found["codex:s-t-1"]["activity_label"], model.QUESTION_OPEN_LABEL)
        self.assertEqual((found["codex:s-t-2"]["state"], found["codex:s-t-2"]["waiting_for"]),
                         ("stopped", "usage limit"))
        self.assertEqual(found["task:reminder"]["activity_state"], "unknown")
        self.assertEqual((snap.summary["waiting"], snap.summary["overdue"], snap.summary["light"]),
                         (2, 1, "attention"))

    def test_fixtures_match_the_model(self):
        """AGENT_ETA_WRITE_FIXTURES=1 rewrites them after a deliberate change."""
        write = os.environ.get("AGENT_ETA_WRITE_FIXTURES") == "1"
        for name, scenario in SCENARIOS.items():
            with self.subTest(name=name):
                text = json.dumps(model.listing(scenario()), indent=2, sort_keys=True) + "\n"
                path = FIXTURES / ("%s.json" % name)
                if write:
                    FIXTURES.mkdir(parents=True, exist_ok=True)
                    path.write_text(text, encoding="utf-8")
                self.assertEqual(path.read_text(encoding="utf-8"), text,
                                 "stale fixture, rerun with AGENT_ETA_WRITE_FIXTURES=1")


if __name__ == "__main__":
    unittest.main()
