"""dsh sessions, read from their zstd event logs and the processes that hold them loaded.

agent-eta lists them like Claude Code sessions and their bash calls as tasks.
"""

import json
import os
import subprocess

from agent_eta_model import clip
from agent_eta_store import read_json, safe_id, sub_dir, write_atomic

# dsh keeps each session as a zstd-compressed event log next to a lock file, which the process
# that has the session loaded holds open. Measured on @deepseek-ai/dsh 0.1.5-rc.2 on 2026-10-05.
DSH_LOG = "session.v3.jsonl.zstd"
DSH_LOCK = "session.lock"
# Where the web UI keeps its session list. Archiving a session only adds its id here, and dsh keeps it loaded.
DSH_WORKSPACE = os.path.join("storages", "workspace.json")
DSH_PORT = 3080
DSH_CACHE = "dsh-cache.json"
DSH_CACHE_VERSION = 1
DSH_DECODE_TIMEOUT = 10
# dsh tools that wait for the user while their call is open, and what the list calls the wait.
DSH_WAITING_TOOLS = {"ask_user_question": "question", "exit_plan_mode": "plan approval"}
# How a turn that ended without finishing reads in the list, by its reason. Nothing continues
# until the user prompts again, so such a session counts as waiting.
DSH_FAILED_TURNS = {"error": "turn failed", "max-tokens": "hit max tokens", "blocked": "blocked"}
# A dsh bash call younger than this is an ordinary short command and stays out of the list, for
# the same reason as CODEX_MIN_AGE.
DSH_MIN_AGE = 10


def dsh_home():
    return os.environ.get("DSH_HOME") or os.path.expanduser("~/.dsh")


def dsh_archived():
    """The ids of the sessions archived in the dsh web UI."""
    shared = (read_json(os.path.join(dsh_home(), DSH_WORKSPACE)) or {}).get("global")
    ids = shared.get("archivedSessionIds") if isinstance(shared, dict) else None
    return {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()


def is_dsh(argv):
    """Whether a command line runs the dsh CLI, as `node /usr/local/bin/dsh …` or straight."""
    return any(arg == "dsh" or arg.endswith("/dsh") or arg.endswith("/@deepseek-ai/dsh/lib/bin.js")
               for arg in argv[:2])


def dsh_web_url(argv):
    """The address of the browser UI a `dsh web` process serves, or None for another profile."""
    args = argv[next(i for i, arg in enumerate(argv) if is_dsh([arg])) + 1:] if is_dsh(argv) else []
    options = {}
    for i, arg in enumerate(args):
        if arg.startswith("--") and "=" in arg:
            options.setdefault(arg.split("=", 1)[0], arg.split("=", 1)[1])
        elif arg.startswith("--") and i + 1 < len(args):
            options.setdefault(arg, args[i + 1])
    if (args[:1] != ["web"]) and options.get("--profile") != "web":
        return None
    try:
        port = int(options.get("--port") or DSH_PORT)
    except ValueError:
        port = DSH_PORT
    return "http://%s:%d/" % (options.get("--host") or "127.0.0.1", port)


def dsh_processes(proc="/proc"):
    """Every dsh session a running process has loaded, as {session folder: (pid, web url)}. The
    process holds the lock file of each session it has loaded open, and only then."""
    root = os.path.join(os.path.realpath(dsh_home()), "sessions") + os.sep
    uid = os.getuid()
    found = {}
    for name in os.listdir(proc):
        if not name.isdigit():
            continue
        base = os.path.join(proc, name)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as handle:
                argv = [arg.decode("utf-8", "replace") for arg in handle.read().split(b"\0") if arg]
            if not is_dsh(argv):
                continue
            fds = os.listdir(os.path.join(base, "fd"))
        except OSError:
            continue
        url = dsh_web_url(argv)
        for fd in fds:
            try:
                target = os.readlink(os.path.join(base, "fd", fd))
            except OSError:
                continue
            if target.startswith(root) and os.path.basename(target) == DSH_LOCK:
                found[os.path.dirname(target)] = (int(name), url)
    return found


def dsh_log(path):
    """The records of a dsh session log, or None when it cannot be decoded. The log is a run of
    zstd frames, one per write batch, so a batch still being written only loses its own lines."""
    try:
        result = subprocess.run(["zstdcat", "--", path], capture_output=True, timeout=DSH_DECODE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    records = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records or None


def first_line(text):
    return clip((text or "").strip().splitlines()[0]) if (text or "").strip() else None


def dsh_arguments(data):
    arguments = data.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            arguments = {}
    return arguments if isinstance(arguments, dict) else {}


def dsh_summary(records):
    """What the list needs from a dsh session log: its id, cwd, title and model, its state with
    the reason for a wait and the time that state began, and the bash calls still running.

    An open approval or an open question call waits for the user, an open turn works, a turn
    that ended with an error, at its token limit or blocked waits for the next prompt, and
    anything else is idle. A retry of the model call inside an open turn becomes its reason, so
    a slow turn says why.
    """
    header = records[0] if records[0].get("type") == "session" else {}
    since = (header.get("createdAt") or 0) / 1000 or None
    title = goal = prompt = model = None
    turn = retry = ended = None
    calls, approvals = {}, {}
    for record in records:
        kind, data = record.get("type"), record.get("data") or {}
        if not isinstance(data, dict):
            continue
        at = (record.get("time") or 0) / 1000 or since
        if kind == "turn/start":
            turn, retry, ended = at, None, None
        elif kind == "turn/end":
            turn, retry, ended = None, None, (data.get("reason") or {}, at)
            calls.clear()
            approvals.clear()
        elif kind == "tool/call" and data.get("callId"):
            calls[data["callId"]] = (data.get("name"), dsh_arguments(data), at)
            retry = None
        elif kind == "tool/result":
            calls.pop(((data.get("message") or {}).get("source") or {}).get("callId"), None)
        elif kind == "approval/asked":
            approvals[data.get("id")] = at
        elif kind == "approval/decided":
            approvals.pop(data.get("id"), None)
        elif kind == "llm/retry":
            retry = data
        elif kind in ("assistant/message", "step/start"):
            retry = None
        elif kind == "session/title" and data.get("title"):
            title = data["title"]
        elif kind == "goal/change" and isinstance(data.get("goal"), dict) and not goal:
            goal = data["goal"].get("objective")
        elif kind == "user/message" and not prompt and (data.get("source") or {}).get("kind") == "user":
            prompt = next((part.get("text") for part in data.get("content") or []
                           if isinstance(part, dict) and part.get("type") == "text"), None)
        elif kind == "request/context" and data.get("model"):
            model = data["model"]
    waiting = sorted((at, DSH_WAITING_TOOLS[name]) for name, _, at in calls.values() if name in DSH_WAITING_TOOLS)
    failed = False
    if approvals:
        state, waiting_for, since = "waiting", "permission", min(approvals.values())
    elif waiting:
        state, waiting_for, since = "waiting", waiting[0][1], waiting[0][0]
    elif turn:
        state, waiting_for, since = "working", None, turn
        if retry:
            failure = retry.get("failure") or {}
            waiting_for = "retry %s/%s (%s)" % (retry.get("retry"), retry.get("maxRetries"),
                                                failure.get("code") or "error")
    elif ended and ended[0].get("kind") in DSH_FAILED_TURNS:
        reason = ended[0]
        code = (reason.get("error") or {}).get("code")
        state, since, failed = "waiting", ended[1], True
        waiting_for = DSH_FAILED_TURNS[reason["kind"]] + (" (%s)" % code if code else "")
    else:
        state, waiting_for, since = "idle", None, ended[1] if ended else since
    bash = [{"call": call_id, "label": clip(arguments.get("description") or first_line(arguments.get("command"))
                                             or "bash"), "started": at}
            for call_id, (name, arguments, at) in calls.items() if name == "bash"]
    return {"id": header.get("id"), "cwd": header.get("cwd"),
            "title": first_line(title) or first_line(goal) or first_line(prompt), "model": model,
            "state": state, "waiting_for": waiting_for, "since": since, "failed": failed, "bash": bash}


def dsh_sessions(directory, now):
    """Every dsh session a running dsh process has loaded and nobody archived, and the bash calls
    running in them as tasks without an ETA. A log is decoded again only once its size or mtime has changed, and
    what it said is kept in the state directory meanwhile, so a poll every two seconds costs no
    decoding while a session sits still."""
    loaded = dsh_processes()
    archived = dsh_archived()
    # Its own subdirectory, since every JSON file at the top of the state directory is a task.
    path = os.path.join(directory, "cache", DSH_CACHE)
    cache = read_json(path) or {}
    known = cache.get("logs") if cache.get("version") == DSH_CACHE_VERSION else None
    known = known if isinstance(known, dict) else {}
    logs, sessions, tasks = {}, [], []
    for folder, (pid, url) in sorted(loaded.items()):
        if os.path.basename(folder) in archived:
            continue
        log = os.path.join(folder, DSH_LOG)
        try:
            info = os.stat(log)
        except OSError:
            continue
        signature = [info.st_size, info.st_mtime_ns]
        entry = known.get(log) or {}
        summary = entry.get("summary") if entry.get("signature") == signature else None
        if summary is None:
            records = dsh_log(log)
            if records is None:
                continue
            summary = dsh_summary(records)
        logs[log] = {"signature": signature, "summary": summary}
        session_id = summary.get("id") or os.path.basename(folder)
        name = summary.get("title") or os.path.basename(summary.get("cwd") or "") or "-"
        sessions.append({
            "agent": "dsh", "id": session_id, "pid": pid, "name": name, "state": summary["state"],
            "waiting_for": summary.get("waiting_for"), "since": summary.get("since"),
            "cwd": summary.get("cwd"), "model": summary.get("model"), "web_url": url,
            "failed": summary.get("failed", False)})
        for call in summary.get("bash") or []:
            if now - (call.get("started") or now) < DSH_MIN_AGE:
                continue
            started = int(call.get("started") or now)
            tasks.append({
                "version": 1, "id": "dsh-%s" % safe_id(call["call"]), "agent": "dsh",
                "session": {"id": session_id}, "cwd": summary.get("cwd"), "label": call.get("label"),
                "started": started, "due": None, "source": "dsh", "holder": {"type": "dsh", "pid": pid},
                "remaining": None, "overdue": False, "progress": None, "session_name": name})
    if logs != known:
        try:
            sub_dir(directory, "cache")
            write_atomic(path, {"version": DSH_CACHE_VERSION, "logs": logs})
        except OSError:
            pass
    return sessions, tasks
