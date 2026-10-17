"""The Konsole tab a session runs in, for the tray's jump.

Konsole runs all its windows in one process, so the pid the tray matches windows by cannot tell
them apart. Its D-Bus interface can. Every Konsole process registers `org.kde.konsole-<pid>`,
every `/Windows/N` lists its tabs, and every `/Sessions/N` names the process it runs.
`agent-eta tab PID...` takes a session's lineage, makes the tab running one of those processes the
current one in its window and prints the titles that window's caption carries before and after
the switch. The tray raises the window with one of those captions and no other.
"""

import json
import os
import re
import shutil
import subprocess
import sys

# Seconds one qdbus call may take. Konsole answers in milliseconds, and the tray waits for the
# whole lookup before it raises a window.
TIMEOUT = 2
SERVICE = re.compile(r"org\.kde\.konsole-(\d+)")
WINDOW = re.compile(r"/Windows/\d+")


class Unavailable(Exception):
    pass


def qdbus():
    """The qdbus binary, or None. AGENT_ETA_QDBUS_BIN replaces the lookup, for tests."""
    override = os.environ.get("AGENT_ETA_QDBUS_BIN")
    for path in [override] if override else [shutil.which("qdbus6"), shutil.which("qdbus")]:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def call(binary, *args):
    try:
        result = subprocess.run([binary, *args], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        raise Unavailable() from None
    if result.returncode:
        raise Unavailable()
    return result.stdout


def lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def title(binary, service, session):
    return call(binary, service, "/Sessions/%s" % session, "title", "1").rstrip("\n")


def find_tab(binary, pids):
    """(service, window, session) of the tab whose process is one of pids, or None.

    The nearest pid that is a Konsole process decides which Konsole to ask.
    """
    services = {}
    for name in lines(call(binary)):
        match = SERVICE.fullmatch(name)
        if match:
            services[int(match.group(1))] = name
    for pid in pids:
        service = services.get(pid)
        if not service:
            continue
        for window in [path for path in lines(call(binary, service)) if WINDOW.fullmatch(path)]:
            for session in lines(call(binary, service, window, "sessionList")):
                try:
                    process = int(call(binary, service, "/Sessions/%s" % session, "processId"))
                except (Unavailable, ValueError):
                    continue
                if process in pids:
                    return service, window, session
        return None
    return None


def select(binary, service, window, session):
    """Make the tab current and return the window's caption titles before and after."""
    before = title(binary, service, call(binary, service, window, "currentSession").strip())
    after = title(binary, service, session)
    call(binary, service, window, "setCurrentSession", session)
    return [before, after]


def tab_action(args):
    binary = qdbus()
    try:
        found = find_tab(binary, args.pids) if binary else None
        titles = select(binary, *found) if found else None
    except Unavailable:
        found = None
    if not found:
        print("agent-eta: no Konsole tab runs any of these processes", file=sys.stderr)
        return 1
    print(json.dumps({"window": found[1], "titles": titles}))
    return 0


def add_parser(sub):
    tab = sub.add_parser("tab", help="make the Konsole tab running one of these processes current, for the tray")
    tab.add_argument("pids", nargs="+", type=int, help="a session's pids, nearest first, as list --json gives them")
