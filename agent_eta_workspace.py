"""Optional KDE workspace capture and conservative restoration through kdotool.

Desktop IDs and window IDs are local to a compositor. Names identify desktops
across hosts; exact application identities or managed session identities identify
windows. Importing this module never touches the compositor or session registry.
"""

from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

VERSION = 1
# KWin 6's VirtualDesktopManager maximum. Creation is also verified after the call.
MAX_DESKTOPS = 20
KEY = re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")
SCRIPT = Path(__file__).with_name("workspace.js")


class WorkspaceError(Exception):
    """An actionable workspace failure which must not stop an agent."""


def jira_key(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise WorkspaceError("A Jira key must have the form PROJECT-123.")
    return value


def assignment(directory, explicit=None):
    """Infer once at launch. No ticket lookup, prompt parsing or ongoing branch watching."""
    if explicit is not None:
        return jira_key(explicit)
    try:
        result = subprocess.run(["git", "-C", directory, "branch", "--show-current"],
                                capture_output=True, text=True, timeout=3)
        keys = set(re.findall(r"(?<![A-Za-z0-9_])" + KEY.pattern + r"(?![A-Za-z0-9_])", result.stdout))
        return keys.pop() if result.returncode == 0 and len(keys) == 1 else None
    except (OSError, subprocess.SubprocessError):
        return None


def identity(raw):
    values = list(raw)
    values[-1] = hashlib.sha256(values[-1].encode()).hexdigest()
    return values


def validate(snapshot):
    """Validate an untrusted cross-host snapshot completely before any compositor writes."""
    if not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int or snapshot.get("version") != VERSION:
        raise WorkspaceError("Unsupported workspace snapshot version.")
    try:
        names = [desktop["name"] for desktop in snapshot["desktops"]]
        if not names or len(names) > MAX_DESKTOPS or any(not isinstance(name, str) or not name or "\0" in name for name in names):
            raise ValueError("invalid desktop names")
        outputs = snapshot["outputs"]
        output_names = [output["name"] for output in outputs]
        if not outputs or len(set(output_names)) != len(output_names):
            raise ValueError("invalid outputs")
        for output in outputs:
            numbers(output["area"], positive_size=True)
        for window in snapshot["windows"]:
            if not isinstance(window["id"], str) or not window["id"]:
                raise ValueError("invalid window ID")
            if len(window["identity"]) != 5 or any(not isinstance(value, str) for value in window["identity"]):
                raise ValueError("invalid window identity")
            if not set(window["desktops"]).issubset(names) or (not window["all_desktops"] and not window["desktops"]):
                raise ValueError("unknown window desktop")
            if type(window["all_desktops"]) is not bool or window["output"] not in output_names:
                raise ValueError("invalid window output or membership")
            numbers(window["rect"], positive_size=True)
            state = window["state"]
            if (type(state["minimized"]) is not bool or type(state["fullscreen"]) is not bool
                    or type(state["maximize"]) is not int or not 0 <= state["maximize"] <= 3):
                raise ValueError("invalid window state")
        if len({window["id"] for window in snapshot["windows"]}) != len(snapshot["windows"]):
            raise ValueError("duplicate window IDs")
    except (KeyError, TypeError, ValueError, IndexError) as error:
        raise WorkspaceError("Invalid workspace snapshot (%s)." % error) from None
    return snapshot


def numbers(values, positive_size=False):
    if (not isinstance(values, list) or len(values) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
            or (positive_size and (values[2] <= 0 or values[3] <= 0))):
        raise ValueError("invalid rectangle")


class Backend:
    """One-shot scripts use upstream reply handling and cleanup, never journal scraping."""

    def __init__(self):
        self.raw_windows = {}

    def run(self, request):
        binary = os.environ.get("AGENT_ETA_KDOTOOL_BIN") or shutil.which("kdotool")
        if not binary:
            raise WorkspaceError("Workspace placement needs kdotool 0.3.0 or later.")
        environment = dict(os.environ)
        bus = Path("/run/user/%d/bus" % os.getuid())
        if not environment.get("DBUS_SESSION_BUS_ADDRESS") and bus.exists():
            environment["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=" + str(bus)
        # kdotool refuses without it, and an SSH shell from host-sync or a handoff has no session environment.
        environment.setdefault("KDE_SESSION_VERSION", "6")
        with tempfile.TemporaryDirectory(prefix="agent-eta-workspace-") as folder:
            script = Path(folder) / "operation.js"
            script.write_text("const request = " + json.dumps(request, ensure_ascii=True) + ";\n" + SCRIPT.read_text())
            try:
                result = subprocess.run([binary, "kwinscript", "--file", str(script)], env=environment,
                                        capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                raise WorkspaceError("KWin workspace request failed or timed out.") from None
        if result.returncode:
            # Native stderr may include window titles or script contents.
            raise WorkspaceError("KWin workspace request failed. Check kdotool and the graphical session.")
        try:
            value = json.loads(result.stdout)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise WorkspaceError("KWin returned an invalid workspace reply.") from None

    def snapshot(self):
        raw = self.run({"operation": "snapshot"})
        self.raw_windows = {window["id"]: window for window in raw["windows"]}
        outputs = {output["name"]: output["area"] for output in raw["outputs"]}
        value = dict(raw, version=VERSION, host=socket.gethostname())
        value["windows"] = []
        for window in raw["windows"]:
            area, geometry = outputs[window["output"]], window["geometry"]
            rect = [(geometry[0] - area[0]) / area[2], (geometry[1] - area[1]) / area[3],
                    geometry[2] / area[2], geometry[3] / area[3]]
            value["windows"].append({key: deepcopy(item) for key, item in window.items() if key not in ("geometry", "identity")}
                                    | {"rect": rect, "identity": identity(window["identity"])})
        return validate(value)

    def apply(self, plan):
        commands = []
        for item in plan["windows"]:
            raw = self.raw_windows.get(item["id"])
            if raw is None or identity(raw["identity"]) != item["expected_identity"]:
                raise WorkspaceError("Window identity changed. Preview again.")
            commands.append({key: value for key, value in item.items() if key not in ("expected_identity", "source_id", "mapping")}
                            | {"identity": raw["identity"], "pid": raw["pid"]})
        request = {"operation": "apply", "expected_desktops": plan["expected_desktops"],
                   "creates": plan["creates"], "windows": commands}
        first = self.run(dict(request, phase="geometry"))
        if not commands:
            return first
        # Wayland resize acknowledgements must arrive before membership changes
        # hide a window. The isolated compositor test exercises this ordering.
        deadline = time.monotonic() + 2
        while True:
            after = self.snapshot()
            ready = all(command["id"] not in first["applied"] or
                        (command["id"] in self.raw_windows and all(abs(a - b) <= 2 for a, b in
                         zip(self.raw_windows[command["id"]]["geometry"], command["geometry"]))) for command in commands)
            if ready or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        request.update(expected_desktops=after["desktops"], creates=[],
                       windows=[command for command in commands if command["id"] in first["applied"]])
        result = self.run(request)
        result["created"] = first["created"]
        result["skipped"] = first["skipped"] + result["skipped"]
        return result


def ambiguous_names(*snapshots):
    """Desktop names that occur more than once in any snapshot, such as KDE's default „New Desktop“.
    Names identify desktops across hosts, so these stay unmatched."""
    found = set()
    for snapshot in snapshots:
        counts = Counter(desktop["name"] for desktop in snapshot["desktops"])
        found.update(name for name, count in counts.items() if count > 1)
    return found


def desktop_plan(source, target):
    """Insert missing names; never redefine an existing desktop's identity. Ambiguous names are neither
    created nor used for positions."""
    ambiguous = ambiguous_names(source, target)
    current = [desktop["name"] for desktop in target["desktops"]]
    wanted = [desktop["name"] for desktop in source["desktops"] if desktop["name"] not in ambiguous]
    creates = []
    for index, name in enumerate(wanted):
        if name in current:
            continue
        following = next((value for value in wanted[index + 1:] if value in current), None)
        preceding = [current.index(value) for value in wanted[:index] if value in current]
        position = current.index(following) if following is not None else len(current)
        if preceding and position <= max(preceding):
            position = len(current)
        current.insert(position, name)
        creates.append({"name": name, "position": position})
    if len(current) > MAX_DESKTOPS:
        raise WorkspaceError("The desktop union exceeds KWin's capacity of %d." % MAX_DESKTOPS)
    named = [name for name in current if name not in ambiguous]
    desired = wanted + [name for name in named if name not in wanted]
    warnings = [] if named == desired else ["Existing desktop IDs and order were preserved; source ordering differs."]
    if ambiguous:
        warnings.append("Desktops with duplicate names stay unmatched: %s." % ", ".join(sorted(ambiguous)))
    return creates, warnings


def output_mapping(source, target):
    destination = sorted(target["outputs"], key=lambda output: (output["area"][0], output["area"][1], output["name"]))
    origin = sorted(source["outputs"], key=lambda output: (output["area"][0], output["area"][1], output["name"]))
    named = {output["name"]: output for output in destination}
    fallback = named.get(target.get("active_output"), destination[0])
    mapping = {}
    for index, output in enumerate(origin):
        name = output["name"]
        if name in named:
            mapping[name] = (named[name], "name")
        elif index < len(destination):
            mapping[name] = (destination[index], "spatial order")
        else:
            mapping[name] = (fallback, "active output")
    return mapping


def geometry(rect, area):
    x, y, width, height = area
    wanted_width = min(width, max(1, round(rect[2] * width)))
    wanted_height = min(height, max(1, round(rect[3] * height)))
    return [max(x, min(x + width - wanted_width, round(x + rect[0] * width))),
            max(y, min(y + height - wanted_height, round(y + rect[1] * height))), wanted_width, wanted_height]


def reconcile(source, target, bindings=None):
    validate(source)
    validate(target)
    creates, warnings = desktop_plan(source, target)
    plan = {"version": VERSION, "expected_desktops": target["desktops"], "creates": creates,
            "windows": [], "skipped": [], "warnings": warnings}
    mappings = output_mapping(source, target)
    ambiguous = ambiguous_names(source, target)
    counts = Counter(tuple(window["identity"]) for window in source["windows"])
    used = set()
    for window in source["windows"]:
        bound = (bindings or {}).get(window["id"])
        if bound:
            candidates = [item for item in target["windows"] if item["id"] == bound]
        elif window.get("session"):
            candidates = [item for item in target["windows"] if item.get("session") == window["session"]]
        else:
            candidates = [item for item in target["windows"] if item["identity"] == window["identity"]]
            if counts[tuple(window["identity"])] != 1:
                candidates = []
        reason = None
        if not window["all_desktops"] and ambiguous.intersection(window["desktops"]):
            reason = "Desktop name is not unique."
        elif len(candidates) != 1 or candidates[0]["id"] in used:
            reason = "No unique destination window."
        elif window.get("tiled") or candidates[0].get("tiled"):
            reason = "Tiling is not restored."
        elif not candidates[0].get("movable", True) or not candidates[0].get("resizable", True):
            reason = "Destination window has geometry constraints."
        elif window.get("shared") or candidates[0].get("shared"):
            reason = "Terminal contains unrelated sessions."
        elif len(window["desktops"]) > 1 and target.get("x11"):
            # X11 supports only one desktop or all; avoid silently losing memberships.
            reason = "X11 cannot restore multiple-desktop membership."
        if reason:
            plan["skipped"].append({"id": window["id"], "reason": reason})
            continue
        destination = candidates[0]
        used.add(destination["id"])
        output, method = mappings[window["output"]]
        plan["windows"].append({"id": destination["id"], "source_id": window["id"],
                                "expected_identity": destination["identity"], "desktops": window["desktops"],
                                "all_desktops": window["all_desktops"], "state": window["state"],
                                "geometry": geometry(window["rect"], output["area"]),
                                "mapping": {"from": window["output"], "to": output["name"], "method": method}})
    return plan


@contextmanager
def locked():
    from agent_eta_tmux import protected
    state = Path(os.environ.get("AGENT_ETA_DIR") or "/tmp/agent-eta-%d" % os.getuid())
    root = protected(protected(state) / "workspace")
    with (root / "lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield root


def apply_snapshot(source, apply=False, backend=None, bindings=None):
    validate(source)
    backend = backend or Backend()
    with locked() as root:
        target = backend.snapshot()
        plan = reconcile(source, target, bindings)
        if not apply:
            return dict(plan, applied=False)
        backup = root / ("before-%d.json" % time.time_ns())
        backup.write_text(json.dumps(target, indent=2) + "\n")
        backup.chmod(0o600)
        try:
            result = backend.apply(plan)
            after = readback(backend, plan)
        except WorkspaceError as error:
            raise WorkspaceError("%s Partial application is possible; backup %s." % (error, backup)) from None
        return dict(plan, applied=True, result=result, verification=verify(plan, after), backup=str(backup))


def verify(plan, after):
    """Report compositor constraints; do not claim a transactional or pixel-perfect restore."""
    found = {window["id"]: window for window in after["windows"]}
    differences = []
    names = {desktop["name"] for desktop in after["desktops"]}
    for item in plan["creates"]:
        if item["name"] not in names:
            differences.append({"desktop": item["name"], "reason": "Desktop creation was not confirmed."})
    for item in plan["windows"]:
        window = found.get(item["id"])
        if not window or window["identity"] != item["expected_identity"]:
            differences.append({"id": item["id"], "reason": "Window disappeared or changed identity."})
            continue
        if (window["all_desktops"] != item["all_desktops"] or
                (not item["all_desktops"] and window["desktops"] != item["desktops"]) or window["state"] != item["state"]):
            differences.append({"id": item["id"], "reason": "KWin constrained membership or state."})
        if not item["state"]["maximize"] and not item["state"]["fullscreen"]:
            area = next(output["area"] for output in after["outputs"] if output["name"] == window["output"])
            actual = geometry(window["rect"], area)
            if any(abs(a - b) > 2 for a, b in zip(actual, item["geometry"])):
                differences.append({"id": item["id"], "reason": "KWin constrained geometry.",
                                    "expected": item["geometry"], "actual": actual})
    return differences


def readback(backend, plan):
    """Wayland clients acknowledge configure events asynchronously."""
    deadline = time.monotonic() + 2
    while True:
        after = backend.snapshot()
        if not verify(plan, after) or time.monotonic() >= deadline:
            return after
        time.sleep(0.1)


def record_for(source, inspect):
    """Resolve a managed ID or a native session through the existing ownership check."""
    from agent_eta_handoff import parse_source
    from agent_eta_tmux import Runtime
    runtime = Runtime()
    if source.startswith("terminal:"):
        record = runtime.read(source.split(":", 1)[1])
        if not runtime.pane(record):
            raise WorkspaceError("The managed session has ended.")
        return runtime, record
    session = inspect(parse_source(source)) if inspect else None
    record = runtime.find(session.get("pid"), session.get("proc_start")) if session else None
    if not record:
        raise WorkspaceError("The session has no live managed terminal.")
    return runtime, record


def viewer_window(runtime, record, snapshot, pids=None):
    """Identify a dedicated Konsole without selecting tabs or opening a viewer."""
    from agent_eta_konsole import Unavailable, call, find_tab, lines, qdbus
    from agent_eta_tmux import lineage
    if pids is None:
        pane = runtime.pane(record)
        client = runtime.local_client(pane["window"]) if pane else None
        pids = lineage(client["pid"]) if client else []
    try:
        binary = qdbus()
        found = find_tab(binary, pids) if binary and pids else None
        if not found or len(lines(call(binary, found[0], found[1], "sessionList"))) != 1:
            return None
        pid = int(found[0].rsplit("-", 1)[1])
        windows = [window for window in snapshot["windows"] if window["pid"] == pid]
        # A dedicated --separate process must own exactly one normal window.
        return windows[0] if len(windows) == 1 else None
    except (Unavailable, ValueError):
        return None


def capture_session(source, inspect, backend=None):
    runtime, record = record_for(source, inspect)
    value = (backend or Backend()).snapshot()
    window = viewer_window(runtime, record, value)
    value["windows"] = [dict(window, session=source)] if window else []
    value["assignment"] = record.get("workspace", {}).get("jira_key")
    value["warnings"] = [] if window else ["No dedicated session viewer was found; only desktops were captured."]
    return value


def annotate(snapshot, sessions, inspect):
    """Attach native identities to known managed viewers without changing their records."""
    for source in sessions:
        try:
            runtime, record = record_for(source, inspect)
            window = viewer_window(runtime, record, snapshot)
            if window:
                window["session"] = source
        except (WorkspaceError, OSError):
            continue
    # General caption matching must never move an unmanaged Konsole process which
    # could contain tabs belonging to other work. Dedicated managed windows above
    # have a process- and tab-checked identity.
    for window in snapshot["windows"]:
        if "konsole" in " ".join(window["identity"][:3]).lower() and not window.get("session"):
            window["shared"] = True
    return snapshot


def place_viewer(runtime, record, pids=None, backend=None):
    """Best effort after attachment. A workspace failure never cancels a launched agent."""
    settings = record.get("workspace")
    if not settings or not (settings.get("jira_key") or settings.get("placement")):
        return True
    backend = backend or Backend()
    try:
        with locked():
            target = backend.snapshot()
            window = viewer_window(runtime, record, target, pids)
            if not window:
                raise WorkspaceError("No dedicated viewer was found; its placement was left unchanged.")
            source = deepcopy(settings.get("placement") or target)
            if settings.get("placement"):
                if len(source["windows"]) != 1:
                    raise WorkspaceError("Session placement must contain exactly one window.")
            else:
                source["windows"] = [deepcopy(window)]
            key = settings.get("jira_key")
            if key:
                if key not in [desktop["name"] for desktop in source["desktops"]]:
                    source["desktops"].append({"id": "", "name": key})
                source["windows"][0].update(desktops=[key], all_desktops=False)
            plan = reconcile(source, target, {source["windows"][0]["id"]: window["id"]})
            result = backend.apply(plan)
            after = readback(backend, plan)
            if plan["skipped"] or result.get("skipped") or verify(plan, after):
                raise WorkspaceError("KWin did not confirm complete viewer placement.")
            if settings.pop("placement", None) is not None:
                # Later Jump actions keep the user's subsequent geometry changes.
                runtime.write(record)
            return True
    except (WorkspaceError, OSError, KeyError, TypeError, ValueError) as error:
        print("agent-eta workspace: %s The agent keeps running." % error, file=sys.stderr)
        return False


def configure(runtime, record, key=None, placement=None):
    """Persist explicit null assignments too, so a later branch change cannot reassign a session."""
    if key is not None:
        jira_key(key)
    if placement is not None:
        validate(placement)
    record["workspace"] = {"jira_key": key}
    if placement is not None and placement.get("windows"):
        record["workspace"]["placement"] = placement
    runtime.write(record)


def action(args, inspect=None, sessions=None):
    operation = args.workspace_action
    if operation == "snapshot":
        value = capture_session(args.session, inspect) if args.session else annotate(Backend().snapshot(), sessions or [], inspect)
        print(json.dumps(value, indent=2))
        return 0
    if operation == "assign":
        if args.clear == (args.key is not None):
            raise WorkspaceError("Choose a Jira key or --clear.")
        runtime, record = record_for(args.source, inspect)
        configure(runtime, record, None if args.clear else jira_key(args.key))
        return 0 if place_viewer(runtime, record) else 1
    try:
        source = json.load(sys.stdin)
    except ValueError:
        raise WorkspaceError("Expected a JSON workspace snapshot on stdin.") from None
    backend = Backend()
    # Annotate the destination once per snapshot, using the same read-only resolver.
    original = backend.snapshot
    backend.snapshot = lambda: annotate(original(), sessions or [], inspect)
    result = apply_snapshot(source, args.apply, backend)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("%s %d desktops and %d windows; %d windows skipped." % (
            "Applied" if args.apply else "Would create/move", len(result["creates"]), len(result["windows"]), len(result["skipped"])))
        for warning in result["warnings"]:
            print(warning)
        for window in result["windows"]:
            mapping = window["mapping"]
            print("Output %s -> %s (%s)." % (mapping["from"], mapping["to"], mapping["method"]))
        for item in result["skipped"]:
            print("%s: %s" % (item["id"], item["reason"]))
    return 1 if args.apply and (result.get("verification") or result.get("result", {}).get("skipped")) else 0


def add_parser(sub):
    workspace = sub.add_parser("workspace", help="capture, preview or restore KDE workspace placement")
    actions = workspace.add_subparsers(dest="workspace_action", required=True)
    capture = actions.add_parser("snapshot", help="emit a version 1 snapshot without moving windows")
    capture.add_argument("--session", metavar="SOURCE", help="only the dedicated viewer of this managed session")
    restore = actions.add_parser("apply", help="read snapshot JSON from stdin; preview by default")
    restore.add_argument("--apply", action="store_true", help="create missing desktops and move uniquely matched windows")
    restore.add_argument("--json", action="store_true")
    assign = actions.add_parser("assign", help="assign a managed session to a ticket desktop")
    assign.add_argument("source", metavar="SOURCE")
    assign.add_argument("key", nargs="?", metavar="KEY")
    assign.add_argument("--clear", action="store_true", help="clear the assignment without deleting the desktop")
