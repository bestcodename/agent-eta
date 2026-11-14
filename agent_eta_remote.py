"""Sessions of other machines, fetched over SSH and shown next to the local ones.

`agent-eta remote add HOST` adds an SSH host. `list --json` then starts a throttled background worker
that runs `agent-eta list --json --all --local` on every host with BatchMode, so an unreachable host
never blocks the widget's poll. Hosts fetched within the last minute merge into the listing as
display-only rows: keys gain a `remote:HOST/` prefix, local actions are cleared, and a session in a
managed tmux keeps its `tmux` navigation with a `host`. Their counts join the tray summary and their
waiting and overdue signals join the notifications. `attach SOURCE --host HOST` focuses the
terminal running agent-eta's own `ssh -t HOST agent-eta attach SOURCE`, or opens one.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

from agent_eta_accounts import AccountStore, check_worker_lock, file_lock, read_json, start_worker, write_json
from agent_eta_handoff import parse_source
from agent_eta_model import SCHEMA_VERSION, combined_summary
from agent_eta_providers import AccountError
from agent_eta_tmux import VIEWER_TIMEOUT, lineage, open_terminal

HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
THROTTLE_SECONDS = 10
FRESH_SECONDS = 60
CONNECT_TIMEOUT = 3
FETCH_TIMEOUT = 8
# Non-interactive SSH shells often lack ~/.local/bin on PATH, and the remote shell expands the tilde.
REMOTE_CLI = "~/.local/bin/agent-eta"
# Seconds a new remote viewer must stay up to count as attached. An ssh attach of a session the
# other machine does not run exited after 0.33 to 0.37 s on 2026-11-13; three times that.
REMOTE_SETTLE = 1.2
# The signals a remote host contributes. Usage stays local, and with it the reset signals.
REMOTE_SIGNAL_KINDS = ("waiting", "overdue")


class RemoteError(Exception):
    pass


def valid_host(host):
    """An SSH host name or alias. The leading character rules out options such as -oProxyCommand."""
    if not isinstance(host, str) or not HOST.fullmatch(host):
        raise RemoteError("%s: a host is an SSH host name or alias" % host)
    return host


def hosts(store):
    configured = store.settings().get("remote_hosts")
    return [h for h in configured if isinstance(h, str) and HOST.fullmatch(h)] if isinstance(configured, list) else []


def cache_path(store):
    return store.cache_dir / "remote.json"


def lock_path(store):
    return store.cache_dir / "remote-refresh.lock"


def read_cache(store):
    return read_json(cache_path(store))


def maybe_refresh(store, cli_path, now):
    """Start one background fetch every THROTTLE_SECONDS at most. Only the lock holder writes the cache."""
    if os.environ.get("AGENT_ETA_NO_REFRESH") == "1" or not hosts(store):
        return False

    def due():
        cache = read_cache(store)
        attempted = cache.get("refresh_attempted_at")
        if isinstance(attempted, (int, float)) and 0 <= now - attempted < THROTTLE_SECONDS:
            return False
        write_json(cache_path(store), dict(cache, refresh_attempted_at=now))
        return True

    try:
        return start_worker(lock_path(store), [sys.executable, str(cli_path), "remote", "refresh"], due)
    except AccountError:
        return False


def valid_listing(listing):
    return (isinstance(listing, dict) and listing.get("schema_version") == SCHEMA_VERSION
            and all(isinstance(listing.get(name), list) for name in ("sessions", "tasks", "sections")))


def fetch(host):
    """The host's listing and None, or None and an error. Remote output never becomes the error."""
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=%d" % CONNECT_TIMEOUT, host,
               REMOTE_CLI + " list --json --all --local"]
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                timeout=FETCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "unreachable"
    except OSError:
        return None, "ssh is unavailable"
    if result.returncode == 255:
        return None, "unreachable"
    if result.returncode != 0:
        if "--local" in result.stderr:
            return None, "agent-eta on %s is too old" % host
        return None, "exit %d" % result.returncode
    try:
        listing = json.loads(result.stdout)
    except ValueError:
        listing = None
    return (listing, None) if valid_listing(listing) else (None, "invalid listing")


def refresh(store, lock_fd=None):
    """Fetch every host in turn. A failed host keeps its last listing until it is no longer fresh."""
    if lock_fd is None:
        try:
            with file_lock(lock_path(store), nonblocking=True):
                return _refresh(store)
        except BlockingIOError:
            return False
    try:
        check_worker_lock(lock_path(store), lock_fd)
        return _refresh(store)
    finally:
        os.close(lock_fd)


def _refresh(store):
    fetched = {host: fetch(host) + (time.time(),) for host in hosts(store)}
    cache = read_cache(store)
    known = cache.get("hosts") if isinstance(cache.get("hosts"), dict) else {}
    entries = {}
    for host, (listing, error, at) in fetched.items():
        entry = dict(known[host]) if isinstance(known.get(host), dict) else {}
        if listing is not None:
            entry.update(listing=listing, fetched_at=at, error=None, failed_at=None)
        else:
            entry.update(error=error, failed_at=at)
        entries[host] = entry
    write_json(cache_path(store), dict(cache, hosts=entries))
    return True


def remote_rows(host, listing):
    """A host's sessions, tasks and section keys, prefixed and stripped of everything that acts locally."""
    prefix = "remote:%s/" % host
    sessions, tasks, sections = [], [], {}
    for session in listing["sessions"]:
        navigation = session.get("navigation") or {}
        sessions.append(dict(
            session, key=prefix + session["key"], host=host, cwd=None, project_root=None, pids=[],
            tasks=[prefix + task for task in session.get("tasks") or []],
            handoff={"available": False, "reason": "runs on " + host, "status": None, "targets": []},
            navigation=dict(navigation, host=host) if navigation.get("kind") == "tmux"
            else {"kind": "unavailable", "reason": "Runs on " + host}))
    for task in listing["tasks"]:
        tasks.append(dict(task, id=prefix + task["id"], key=prefix + task["key"], source="remote"))
    for section in listing["sections"]:
        sections[section["index"]] = dict(section, session_keys=[prefix + key for key in section["session_keys"]])
    return sessions, tasks, sections


def remote_summary(host, listing):
    """A host's summary with its progress session under the prefixed key, or {} if it has none."""
    found = listing.get("summary")
    if not isinstance(found, dict):
        return {}
    key = found.get("progress_session_key")
    return dict(found, progress_session_key="remote:%s/%s" % (host, key) if isinstance(key, str) else None)


def remote_signals(host, listing):
    """A host's waiting and overdue signals under prefixed keys, with the host for the message.
    Its reset signals stay local like the usage they belong to, and a malformed signal is left out.
    The prefixed dedupe key stays the same while the host is away, so a host that turns fresh again
    does not notify a second time for a wait the widget already claimed."""
    found = listing.get("notification_signals")
    if not isinstance(found, list):
        return []
    prefix = "remote:%s/" % host
    signals = []
    for signal in found:
        if not (isinstance(signal, dict) and signal.get("kind") in REMOTE_SIGNAL_KINDS
                and all(isinstance(signal.get(name), str) for name in ("key", "entity_key", "dedupe_key"))):
            continue
        params = signal.get("message_params")
        signals.append(dict(signal, key=prefix + signal["key"], entity_key=prefix + signal["entity_key"],
                            dedupe_key=prefix + signal["dedupe_key"],
                            message_params=dict(params if isinstance(params, dict) else {}, host=host)))
    return signals


def merge(listing, cache, now):
    """The local listing plus every host fetched within FRESH_SECONDS. The summary and the waiting
    and overdue signals cover the merged hosts too, so the tray counts and notifies for them. Usage,
    accounts and actions stay local, and without a fresh host the listing stays as it was."""
    merged = dict(listing, sessions=list(listing["sessions"]), tasks=list(listing["tasks"]),
                  sections=[dict(s, session_keys=list(s["session_keys"])) for s in listing["sections"]])
    by_index = {section["index"]: section for section in merged["sections"]}
    summaries = [listing.get("summary") if isinstance(listing.get("summary"), dict) else {}]
    signals = list(listing.get("notification_signals") or [])
    entries = cache.get("hosts") if isinstance(cache.get("hosts"), dict) else {}
    for host in sorted(entries):
        entry = entries[host]
        if not isinstance(entry, dict) or not HOST.fullmatch(host):
            continue
        fetched = entry.get("fetched_at")
        if not isinstance(fetched, (int, float)) or not 0 <= now - fetched <= FRESH_SECONDS:
            continue
        if not valid_listing(entry.get("listing")):
            continue
        try:
            sessions, tasks, sections = remote_rows(host, entry["listing"])
        except (KeyError, TypeError, AttributeError):
            continue
        merged["sessions"] += sessions
        merged["tasks"] += tasks
        for index, section in sections.items():
            if index in by_index:
                by_index[index]["session_keys"] += section["session_keys"]
            else:
                by_index[index] = section
                merged["sections"].append(section)
        summaries.append(remote_summary(host, entry["listing"]))
        signals += remote_signals(host, entry["listing"])
    merged["sections"].sort(key=lambda section: section["index"])
    if len(summaries) > 1:
        merged["summary"] = dict(summaries[0], **combined_summary(summaries, merged["sessions"]))
        merged["notification_signals"] = signals
    return merged


def viewer(argv, proc="/proc"):
    """The pid of this user's SSH viewer. Match ssh and the remote CLI by basename so viewers
    opened by hand through PATH or an absolute CLI path count too. Other arguments stay exact."""
    wanted = [arg.encode() for arg in argv]
    uid = os.getuid()
    for name in os.listdir(proc):
        if not name.isdigit():
            continue
        base = os.path.join(proc, name)
        try:
            if os.stat(base).st_uid != uid:
                continue
            with open(os.path.join(base, "cmdline"), "rb") as handle:
                found = handle.read().split(b"\0")[:-1]
            if (len(found) == len(wanted) == 6
                    and os.path.basename(found[0]) == os.path.basename(wanted[0])
                    and os.path.basename(found[3]) == os.path.basename(wanted[3])
                    and found[1:3] == wanted[1:3] and found[4:] == wanted[4:]):
                return int(name)
        except OSError:
            continue
    return None


def attach(host, source, interactive, proc="/proc"):
    """Show a session of a managed tmux on host. ssh hands its arguments to the remote shell as one
    string, so both are validated first."""
    agent, identifier = parse_source(source)
    argv = ["ssh", "-t", valid_host(host), REMOTE_CLI, "attach", agent + ":" + identifier]
    if interactive:
        os.execvp(argv[0], argv)
    pid = viewer(argv, proc)
    if pid:
        return {"opened": False, "pids": lineage(pid)}
    open_terminal(argv)
    # The terminal command returns once its unit starts, and a remote attach that fails exits
    # within a second, so only an ssh that is still up after REMOTE_SETTLE counts as opened.
    deadline = time.monotonic() + VIEWER_TIMEOUT
    while not pid and time.monotonic() < deadline:
        time.sleep(0.1)
        pid = viewer(argv, proc)
    if pid:
        time.sleep(REMOTE_SETTLE)
    if not pid or not os.path.isdir(os.path.join(proc, str(pid))):
        raise RemoteError("the remote attach ended at once; run agent-eta attach %s on %s" % (source, host))
    return {"opened": True, "pids": lineage(pid)}


def add_parser(sub):
    remote = sub.add_parser("remote", help="other machines whose sessions the JSON list and the widget show")
    actions = remote.add_subparsers(dest="remote_action", required=True)
    for action in ("add", "remove"):
        actions.add_parser(action, help="%s an SSH host" % action).add_argument("host")
    actions.add_parser("list", help="each host with its last fetch and error")
    worker = actions.add_parser("refresh", help="fetch every host now; list --json starts this itself")
    worker.add_argument("--lock-fd", type=int, help=argparse.SUPPRESS)


def remote_action(args):
    store = AccountStore()
    action = args.remote_action
    if action in ("add", "remove"):
        host = valid_host(args.host)

        def change(data):
            configured = data.get("remote_hosts")
            current = [h for h in configured if h != host] if isinstance(configured, list) else []
            data["remote_hosts"] = current + [host] if action == "add" else current

        store.configure(change)
    elif action == "refresh":
        refresh(store, args.lock_fd)
    else:
        entries = read_cache(store).get("hosts")
        entries = entries if isinstance(entries, dict) else {}
        for host in hosts(store):
            entry = entries.get(host) if isinstance(entries.get(host), dict) else {}
            fetched = entry.get("fetched_at")
            when = time.strftime("%H:%M:%S", time.localtime(fetched)) if isinstance(fetched, (int, float)) else "never"
            print("%s\tfetched %s\t%s" % (host, when, entry.get("error") or "ok"))
    return 0
