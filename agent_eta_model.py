"""The rules agent-eta decides for every surface, as one pure model.

`build_snapshot()` takes what the collectors in `agent-eta` read, which are the sessions with the
state their agent reports, the task entries whose holders were already verified, the usage windows,
the accounts and the turn ETAs, and returns one `Snapshot` for one point in time. It decides
effective activity, ETAs, ranking, sections, the tray summary, usage grouping and notification
signals. The terminal table, `list --json` and the tray widget all read that snapshot, so none of
them decides anything of its own.

Nothing here reads files, processes or the clock, and no input is mutated. The pair tasks a finished
Codex turn left without PostToolUse come back in `Snapshot.prune_tasks`, and the caller deletes them.
"""

import copy
from dataclasses import dataclass

# An entry without a live holder expires once it is overdue by its own length, but never
# sooner than this. One without any ETA expires after UNKNOWN_TTL.
OVERDUE_MIN = 3600
UNKNOWN_TTL = 2 * 3600
# How long a session that does not work may rest before it counts as dormant. Neither agent says
# whether anyone still looks at a session, and a process that lives on for days in a terminal
# tab, the Claude Code daemon or the Codex app's one app-server for all threads looks just like
# one in use, so time is the signal. Twelve hours kept a night's worth of finished threads under
# "Needs you" on 2026-10-15.
DORMANT_AFTER = 2 * 3600
# The section of a dormant session, after the three of section().
DORMANT_SECTION = 3
# The window lengths in minutes that order the agents of a usage section, the first deciding first.
USAGE_SORT_WINDOWS = (10080, 300)
# The holders whose liveness the collectors verified. A manual deadline alone proves no work.
RUNNING_HOLDERS = ("pid", "lock", "pair")

# The one table of words every surface shows for a state or a section.
STATE_LABELS = {"waiting": "waiting", "idle": "idle", "working": "working", "stopped": "stopped",
                "unknown": "unknown"}
# The label of a Codex thread whose turn runs on while an async question waits for its answer.
QUESTION_OPEN_LABEL = "working, question open"
SECTION_TITLES = ("Needs you", "Working", "Stopped until a limit resets", "Dormant")
# The semantic light of an activity state. The widget maps these to theme colours.
STATE_LIGHTS = {"waiting": "attention", "idle": "caution", "working": "active", "stopped": "off",
                "unknown": "off"}


@dataclass(frozen=True)
class Snapshot:
    """Everything the surfaces show for one point in time, in display order.

    `sessions` and `tasks` are fresh dicts that carry the collector fields plus the decided ones.
    `summary`, `sections`, `usage_groups` and `signals` name sessions, tasks, windows and accounts by
    their `key`. `prune_tasks` holds the ids of task entries the caller should delete.
    """
    now: float
    sessions: tuple
    tasks: tuple
    usage: tuple
    accounts: tuple
    summary: dict
    sections: tuple
    usage_groups: tuple
    signals: tuple
    prune_tasks: tuple


# --- identities ---------------------------------------------------------------------------

def agent_label(agent, account):
    return "%s/%s" % (agent, account) if account else agent


def session_key(agent, session):
    """Claude Code sessions are matched by pid, which survives a /clear, Codex threads by id."""
    if agent == "claude" and session.get("pid"):
        return ("claude", int(session["pid"]))
    if session.get("id"):
        return (agent, session["id"])
    return None


def key_text(key):
    return "%s:%s" % key


def stamp(value):
    """A time as a key part that reads the same whichever side formatted it, `1760000000` rather
    than `1760000000.0`."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# --- tasks --------------------------------------------------------------------------------

def progress(started, due, now):
    """The share of the time from started to due that has passed, from 0 to 1, or None without a
    due time. An overdue ETA stays at 1, and `overdue` says that it ran over."""
    if not due:
        return None
    if not started or due <= started:
        return 1.0 if now >= due else 0.0
    return max(0.0, min(1.0, (now - started) / (due - started)))


def task_view(entry, now):
    """A task entry with the time left until its ETA, whether it ran over and its progress."""
    due = entry.get("due")
    remaining = int(due - now) if due else None
    row = dict(entry)
    row["key"] = "task:%s" % entry["id"]
    row["remaining"] = remaining
    row["overdue"] = remaining is not None and remaining < 0
    row["progress"] = progress(entry.get("started"), due, now)
    return row


def task_sort_key(row):
    """Overdue first, then by the time left, then those without an ETA by their start."""
    remaining = row["remaining"]
    if remaining is None:
        return (2, row.get("started") or 0)
    return (0 if remaining < 0 else 1, remaining)


# --- sessions -----------------------------------------------------------------------------

def has_running_task(session):
    """The collectors have already checked these holders; a manual deadline alone proves no work."""
    return any((task.get("holder") or {}).get("type") in RUNNING_HOLDERS for task in session["tasks"])


def stopped_before(session, task):
    """Whether an unpaired Codex command predates a completed or failed turn.

    A denied command can miss PostToolUse even though Stop arrives. The shared app-server
    staying alive does not prove that command still runs. PID and lock holders are unaffected.
    """
    return (session["state"] in ("idle", "stopped") and (task.get("holder") or {}).get("type") == "pair"
            and (task.get("started") or 0) <= (session.get("since") or 0))


def expired(entry, now):
    """Whether an entry without a live holder has run out, see OVERDUE_MIN."""
    started = entry.get("started") or now
    due = entry.get("due")
    if due:
        return now > due + max(OVERDUE_MIN, due - started)
    return now > started + UNKNOWN_TTL


def turn_ended(record, owner, now):
    """Whether a turn ETA is over, because its session is gone, its ETA expired or its session went
    idle or stopped after the turn began."""
    return (owner is None or expired(record, now)
            or (owner["state"] in ("idle", "stopped") and (owner.get("since") or 0) >= (record.get("started") or 0)))


def at_rest(session):
    """Idle, or stopped by an error with no reset left to wait for. Nothing runs either way."""
    return session["state"] == "idle" or (session["state"] == "stopped" and not session.get("due"))


def dormant(session, now):
    """Whether a session has rested so long that nobody looks at it any more. A dsh turn that
    failed waits for the next prompt, and after DORMANT_AFTER it rests like an idle session. A
    session that never ran a turn is dormant from the start."""
    if session.get("unused") and not session["tasks"]:
        return True
    return ((at_rest(session) or bool(session.get("failed"))) and not session["tasks"]
            and now - (session.get("since") or now) > DORMANT_AFTER)


def session_sort_key(session):
    """By how soon a session needs you. Waiting for an answer first, then at rest with the most
    recently active first, then working by its ETA like the tasks, then stopped until a usage
    limit resets."""
    if session["state"] == "waiting":
        rank = 0
    elif session["state"] == "unknown" or (at_rest(session) and not has_running_task(session)):
        rank = 1
    elif session["state"] == "stopped":
        rank = 3
    else:
        rank = 2
    remaining = session["remaining"]
    if remaining is None:
        return (rank, 2, -(session.get("since") or 0) if rank == 1 else session.get("since") or 0)
    return (rank, 0 if remaining < 0 else 1, remaining)


def section(session):
    """0 for a session that needs you, 1 for a working one, 2 for one stopped by a usage limit,
    its own or its account's."""
    return max(session_sort_key(session)[0] - 1, 0)


def activity_state(session):
    """What a session effectively does. An idle or unknown owner of verified background work works,
    while the state its agent reported stays in `reported_state`."""
    if session["state"] in ("idle", "unknown") and has_running_task(session):
        return "working"
    return session["state"]


def activity_label(session):
    if session["activity_state"] == "waiting" and session.get("turn_running"):
        return QUESTION_OPEN_LABEL
    return STATE_LABELS.get(session["activity_state"], session["activity_state"])


def session_light(session):
    """A working session past its ETA turns to caution, like the tray summary counts it."""
    if session["activity_state"] == "working" and session["overdue"]:
        return "caution"
    return STATE_LIGHTS.get(session["activity_state"], "off")


def limit_stops(sessions, usage, now):
    """Mark every session that does not work while its account has a reached usage limit as
    stopped until that limit resets, as Codex marks a thread whose turn hit one. A working
    session stays as it is, since it may run on extra usage or the reading may lag behind a
    reset, and so does one whose turn runs on while an async question waits. A dormant one stays
    dormant, and one already stopped with a reset of its own keeps that one."""
    blocked = {agent: summary["resets_at"] for agent, summary, _ in usage_sections(usage)[1]}
    for session in sessions:
        resets_at = blocked.get(agent_label(session["agent"], session.get("account")))
        if (resets_at and session["state"] not in ("working", "unknown") and not session.get("turn_running")
                and not session.get("resume_at") and not dormant(session, now)):
            session.update(state="stopped", waiting_for="usage limit", resume_at=resets_at)


def set_eta(session, turn, now):
    """The ETA of a session: the reset a usage limit waits for, else the turn ETA its agent set
    with `agent-eta turn`, else the latest due time among its tasks."""
    timed = [task for task in session["tasks"] if task.get("due")]
    if session.get("resume_at"):
        session.update(due=session["resume_at"], eta_source="limit", turn_label=None,
                       eta_started=session.get("since"))
    elif turn and turn.get("due"):
        session.update(due=turn["due"], eta_source="turn", turn_label=turn.get("label") or None,
                       eta_started=turn.get("started"))
    elif timed:
        last = max(timed, key=lambda task: task["due"])
        session.update(due=last["due"], eta_source="tasks", turn_label=None, eta_started=last.get("started"))
    else:
        session.update(due=None, eta_source=None, turn_label=turn.get("label") if turn else None,
                       eta_started=None)
    session["remaining"] = int(session["due"] - now) if session["due"] else None
    session["overdue"] = session["remaining"] is not None and session["remaining"] < 0
    session["progress"] = progress(session["eta_started"], session["due"], now)


# --- usage --------------------------------------------------------------------------------

def window_key(window):
    return "window:%s:%s" % (window["agent"], window["minutes"])


def usage_view(now, windows):
    """Every usage window, copied, with the share of it that has passed, both in percent, how far
    the usage runs ahead of the time in percentage points, the time left until its reset and
    whether its limit is reached. A window whose reset lies in the past has started over since
    its reading, so none of that is known then."""
    found = []
    for window in windows:
        window = dict(window)
        resets_at, length = window["resets_at"], window["minutes"] * 60
        if resets_at and resets_at > now:
            window["elapsed"] = max(0.0, min(100.0, 100.0 * (1 - (resets_at - now) / length)))
            window["pace"] = window["used"] - window["elapsed"]
            window["remaining"] = int(resets_at - now)
        else:
            window["used"] = window["elapsed"] = window["pace"] = window["remaining"] = None
        window["ahead"] = window["pace"] is not None and window["pace"] > 0
        window["reached"] = window["used"] is not None and window["used"] >= 100
        window["key"] = window_key(window)
        found.append(window)
    return found


def until_reset(window):
    return (window is None or window["remaining"] is None, (window or {}).get("remaining") or 0)


def agent_order(windows):
    by_minutes = {window["minutes"]: window for window in windows}
    return tuple(until_reset(by_minutes.get(minutes)) for minutes in USAGE_SORT_WINDOWS)


def usage_sections(windows):
    """The agents whose usage limits all have room left and the agents with a reached limit, with
    their windows ordered by reset. Each entry is (agent, summary, windows). The summary of an open
    agent is its window that resets first, and that of a blocked one the reached window that resets
    last, since that reset ends the block. Open agents are ordered by the reset of the 7-day window
    and then by that of the 5-hour window, blocked ones by the end of their block, the soonest
    first in both."""
    by_agent = {}
    for window in windows:
        by_agent.setdefault(window["agent"], []).append(window)
    open_, blocked = [], []
    for agent, group in by_agent.items():
        group.sort(key=until_reset)
        reached = [window for window in group if window["reached"]]
        if reached:
            blocked.append((agent, max(reached, key=lambda window: window["remaining"]), group))
        else:
            open_.append((agent, group[0], group))
    open_.sort(key=lambda entry: agent_order(entry[2]))
    blocked.sort(key=lambda entry: (until_reset(entry[1]), agent_order(entry[2])))
    return open_, blocked


def usage_groups(windows, accounts=()):
    """The usage block of the widget, one group per agent in the order of the usage table, which
    includes accounts without a reading. `reset_window_key` names the window that resets first for
    an open agent and the one that ends the block for a blocked one."""
    by_agent = {}
    for account in accounts:
        by_agent.setdefault(account["agent"], [])
    for window in windows:
        by_agent.setdefault(window["agent"], []).append(window)
    account_of = {account["agent"]: account for account in accounts}
    groups = []
    for agent, group in by_agent.items():
        group = sorted(group, key=until_reset)
        reached = [window for window in group if window["reached"]]
        known = [window["used"] for window in group if window["used"] is not None]
        reset_by = max(reached, key=lambda window: window["remaining"]) if reached else (group[0] if group else None)
        account = account_of.get(agent)
        groups.append({
            "key": "usage:%s" % agent, "agent": agent,
            "account_key": account["key"] if account else None,
            "window_keys": [window["key"] for window in group],
            "reached": bool(reached), "ahead": any(window["ahead"] for window in group),
            "used": max(known) if known else None,
            "reset_window_key": reset_by["key"] if reset_by else None,
            "_order": (bool(reached), until_reset(reset_by) if reached else (False, 0), agent_order(group)),
        })
    groups.sort(key=lambda group: group["_order"])
    for group in groups:
        del group["_order"]
    return groups


def account_note(account):
    """What the usage table says about an account whose login or reading is not in order, the
    same wording as the tray, or "" for an authenticated account with a current reading."""
    if account["auth_state"] == "logged_out":
        return "Not logged in"
    if account["auth_state"] == "mismatch":
        return "Different account logged in"
    parts = []
    if account["auth_state"] == "unknown":
        parts.append("Authentication unknown")
    if account["usage_status"] != "current":
        parts.append("Stale reading" if account["usage_status"] == "stale" else "Usage unavailable")
    return " · ".join(parts)


# --- summary and signals ------------------------------------------------------------------

def late(session):
    return session["overdue"] or any(task["overdue"] for task in session["tasks"])


def summary(sessions):
    """Counts, the tray state and the session whose progress the tray icon shows. `attention`
    counts the sessions that need you now, which are the waiting ones and the working ones that
    ran over.

    `light` is the tray orb over the sessions that are not dormant: attention with the number of
    waiting sessions as soon as one waits, caution with the number of idle and overdue ones, active
    without a number while everything else works or waits for a limit, and off without any such
    session. Only attention makes the tray pulse.
    """
    live = [s for s in sessions if not s["dormant"] and s["activity_state"] != "unknown"]
    counts = {state: sum(1 for s in live if s["activity_state"] == state)
              for state in ("waiting", "working", "idle", "stopped")}
    overdue = sum(1 for s in live if s["activity_state"] == "working" and late(s))
    timed = [s for s in live if s["activity_state"] == "working" and s["progress"] is not None]
    timed.sort(key=lambda s: s["remaining"])
    result = dict(counts, overdue=overdue, dormant=sum(1 for s in sessions if s["dormant"]),
                  attention=counts["waiting"] + overdue, live=len(live),
                  progress_session_key=timed[0]["key"] if timed else None)
    if counts["waiting"]:
        result.update(light="attention", badge_count=counts["waiting"])
    elif counts["idle"] or overdue:
        result.update(light="caution", badge_count=counts["idle"] + overdue)
    else:
        result.update(light="active" if live else "off", badge_count=0)
    result["status"] = "attention" if result["light"] == "attention" else "active" if live else "passive"
    return result


def signal(key, kind, entity_key, active, edge, notify_on_new, dedupe_key, **message_params):
    return {"key": key, "kind": kind, "entity_key": entity_key, "active": bool(active), "edge": edge,
            "notify_on_new": notify_on_new, "dedupe_key": dedupe_key, "message_params": message_params}


def signals(sessions, tasks, windows):
    """What may notify, one signal per condition. The widget compares each with the signal of the
    same key in the poll before. A rising signal notifies when it turns active, and one with
    `notify_on_new` also when it shows up active, while a falling one notifies when it turns
    inactive and then takes the dedupe key of the poll before. Every tray uses the same dedupe key,
    so two trays notify once.

    A session whose ETA comes from its tasks runs over with them, and the task says which, so it
    has no overdue signal of its own.
    """
    found = []
    for session in sessions:
        if session["dormant"]:
            continue
        key = session["key"]
        found.append(signal("waiting:" + key, "waiting", key, session["activity_state"] == "waiting", "rising",
                            True, "waiting:%s:%s" % (key, stamp(session.get("since"))),
                            name=session["name"], agent=agent_label(session["agent"], session.get("account")),
                            waiting_for=session.get("waiting_for") or "input"))
        if session["eta_source"] != "tasks":
            found.append(signal("overdue:" + key, "overdue", key,
                                session["overdue"] and session["activity_state"] == "working", "rising", False,
                                "overdue:%s:%s" % (key, stamp(session["due"])), name=session["name"],
                                turn_label=session.get("turn_label"), due=session["due"]))
    for task in tasks:
        if task.get("due"):
            found.append(signal("overdue:" + task["key"], "overdue", task["key"], task["overdue"], "rising", False,
                                "overdue:%s:%s" % (task["key"], stamp(task["due"])), label=task.get("label"),
                                session_name=task.get("session_name") or task.get("agent"), due=task["due"]))
    for window in windows:
        found.append(signal("reset:" + window["key"], "reset", window["key"], window["reached"], "falling", False,
                            "reset:%s:%s" % (window["key"], stamp(window.get("resets_at"))),
                            agent=window["agent"], minutes=window["minutes"],
                            reading_pending=window["used"] is None))
    return found


# --- snapshot -----------------------------------------------------------------------------

def handoff_view(session, handoffs):
    """Whether `agent-eta handoff` can move a session, where to, and its latest move. A collector
    that found no process to pause sets `gate_reason`."""
    if session.get("agent") not in HANDOFF_TARGETS or not session.get("id"):
        return {"available": False, "reason": "only Claude Code and Codex sessions move", "targets": [],
                "status": None}
    record = handoffs.get("%s:%s" % (session["agent"], session["id"]))
    status = {key: record.get(key) for key in ("id", "state", "target", "error")} if record else None
    reason = session.get("gate_reason")
    return {"available": not reason, "reason": reason, "targets": list(HANDOFF_TARGETS[session["agent"]]),
            "status": status}


def build_snapshot(*, now, sessions, tasks, usage=(), accounts=(), turns=None, handoffs=None):
    """One snapshot from the collected inputs, none of which it changes.

    A task whose session is not known, such as a local run, stands as a session of its own. A
    Codex command left without PostToolUse when its turn ended goes to `prune_tasks`. A session
    that does not work while its account has a reached usage limit counts as stopped until that
    limit resets. `turns` maps a session_key() to the turn ETA record of that session, and
    `handoffs` a handoff source such as `codex:<thread>` to its latest handoff record.
    """
    sessions = copy.deepcopy(list(sessions))
    accounts = [dict(account, key="account:%s" % account["id"]) for account in copy.deepcopy(list(accounts))]
    windows = usage_view(now, copy.deepcopy(list(usage)))
    turns = turns or {}
    by_key = {}
    for session in sessions:
        session.setdefault("reported_state", session["state"])
        session["tasks"] = []
        session["key"] = key_text(session_key(session["agent"], session) or ("task", "-"))
        by_key[session_key(session["agent"], session)] = session
    kept, prune = [], []
    for task in sorted((task_view(task, now) for task in copy.deepcopy(list(tasks))), key=task_sort_key):
        key = session_key(task.get("agent"), task.get("session") or {}) or ("task", task["id"])
        owner = by_key.get(key)
        if owner and stopped_before(owner, task):
            prune.append(task["id"])
            continue
        kept.append(task)
        if owner is None:
            session = task.get("session") or {}
            owner = by_key[key] = {
                "agent": task.get("agent"), "id": session.get("id"), "pid": session.get("pid"),
                "name": task.get("session_name") or "-", "state": "unknown", "reported_state": "unknown",
                "waiting_for": None, "since": task.get("started"), "cwd": task.get("cwd"), "tasks": [],
                "key": key_text(key)}
            sessions.append(owner)
        owner["tasks"].append(task)
    for session in sessions:
        if session["state"] == "unknown" and has_running_task(session):
            session["state"] = "working"
    limit_stops(sessions, windows, now)
    for session in sessions:
        set_eta(session, turns.get(session_key(session["agent"], session)), now)
    sessions.sort(key=lambda session: (dormant(session, now), session_sort_key(session)))
    for session in sessions:
        session["dormant"] = dormant(session, now)
        session["section"] = DORMANT_SECTION if session["dormant"] else section(session)
        session["activity_state"] = activity_state(session)
        session["handoff"] = handoff_view(session, handoffs or {})
        session["activity_label"] = activity_label(session)
        session["light"] = session_light(session)
    sections = tuple({"index": index, "title": title,
                      "session_keys": [s["key"] for s in sessions if s["section"] == index]}
                     for index, title in enumerate(SECTION_TITLES))
    return Snapshot(now=now, sessions=tuple(sessions), tasks=tuple(kept), usage=tuple(windows),
                    accounts=tuple(accounts), summary=summary(sessions), sections=sections,
                    usage_groups=tuple(usage_groups(windows, accounts)),
                    signals=tuple(signals(sessions, kept, windows)), prune_tasks=tuple(prune))


# --- contract -----------------------------------------------------------------------------

# The version of the `list --json` contract. It grows only by additions, and anything else is a
# new version the widget refuses until it is updated.
SCHEMA_VERSION = 1
# Where `agent-eta handoff` moves a session of each agent. Claude to Claude stays a resume.
HANDOFF_TARGETS = {"claude": ("codex", "claude"), "codex": ("claude",)}


def labels():
    """The one label table every surface reads its words from."""
    return {"states": dict(STATE_LABELS), "question_open": QUESTION_OPEN_LABEL, "sections": list(SECTION_TITLES),
            "dormant_after": DORMANT_AFTER}


def listing(snapshot, enrich=None):
    """A snapshot as `list --json` prints it, contract schema 1. Sessions name their tasks by id,
    and `enrich` may add fields to each session, such as the process lineage only a collector can
    read."""
    sessions = []
    for session in snapshot.sessions:
        found = dict(session, tasks=[task["id"] for task in session["tasks"]])
        if enrich:
            found.update(enrich(session))
        sessions.append(found)
    return {"schema_version": SCHEMA_VERSION, "now": int(snapshot.now), "labels": labels(),
            "sessions": sessions, "tasks": list(snapshot.tasks), "usage": list(snapshot.usage),
            "accounts": list(snapshot.accounts), "summary": dict(snapshot.summary),
            "sections": list(snapshot.sections), "usage_groups": list(snapshot.usage_groups),
            "notification_signals": list(snapshot.signals)}
