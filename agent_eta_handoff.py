"""Hand a Claude Code session or a Codex thread over to the other provider, with its active plan.

`agent-eta handoff SOURCE... --to claude|codex [--account NAME] [--plan PATH] [--wait SECONDS] [--dry-run]`
takes sources as `claude:<session>` and `codex:<thread>`. A move from Claude to Claude stays a resume and goes
through `claude-account handoff --only`, which keeps the conversation. A move between providers starts a fresh
session that continues the source's plan:

1. The plan comes from --plan, else from the source's records (see claude_plan() and codex_plan()), else from a
   forked one-shot of the source that prints a brief plan. Without any, the handoff stops as "preparation needed".
2. A snapshot under ~/.local/state/agent-eta/handoff/<id>/ (mode 0700) keeps plan.md, the plan with a
   "Handover" section of progress, next step, branch, HEAD and dirty paths, and status.json.
3. The source must reach a safe boundary: no turn running, nothing waiting for an answer and no verified
   background writer. The command waits up to --wait seconds and reports without forcing.
4. The source process moves into a transient systemd user scope, is frozen there and checked again, the
   destination opens in a new Konsole window, and once it registered the source gets SIGHUP and is thawed.
   The cgroup freezer leaves job control alone, while SIGSTOP would hand the terminal back to the shell. A
   failure, a timeout, a cancel or any error thaws the source and keeps status.json with the commands for
   recovery. Every pause and signal checks the process start time first, so a reused pid is never hit.

A Codex thread of the desktop app shares one app-server with every other thread, so it cannot be paused on
its own and is refused as a source. Every collaborator that touches the system comes in through `Env`, which
the tests replace.
"""

import fcntl
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import time
import uuid
from datetime import datetime

import agent_eta_providers

# Variables a session hands to the commands it runs. A claude started with the Claude ones believes it is a
# child session and saves no transcript, measured on 2026-10-16, and the Codex ones would mark the new
# session as running inside a Codex sandbox.
INHERITED = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT",
             "CLAUDE_CONFIG_DIR", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SANDBOX",
             "CODEX_SANDBOX_NETWORK_DISABLED")
# Konsole keeps a tab's command in its profile, so a split or a new tab in the handoff window runs the
# launcher again. The first run swaps the script for one that only starts the user's shell.
ONE_SHOT = r"""printf '#!/bin/sh\nexec "${SHELL:-/bin/sh}"\n' > "$0.tmp" && mv "$0.tmp" "$0" """.rstrip()
# How long a destination may take to register, and how often the boundary and the registration are polled.
# The variables exist for tests and for a forced timeout.
REGISTER_TIMEOUT = float(os.environ.get("AGENT_ETA_HANDOFF_REGISTER_TIMEOUT") or 300)
POLL = float(os.environ.get("AGENT_ETA_HANDOFF_POLL") or 5)
# The states of a handoff record that a repeated request reports instead of starting over.
SETTLED = ("launched", "completed")
SOURCE = re.compile(r"^(claude|codex):([A-Za-z0-9._-]+)$")
PLAN_REQUEST = ("Write a brief plan for the remaining work of this session as Markdown: a title, a "
                "`## Steps` section with a numbered list and a `## Verification` section. Print only the plan.")


class HandoffError(Exception):
    """A request the handoff turns down, with the reason for the user."""


def parse_source(text):
    match = SOURCE.match(text or "")
    if not match:
        raise HandoffError("%s: a source is claude:<session> or codex:<thread>" % text)
    return match.group(1), match.group(2)


# --- plans --------------------------------------------------------------------------------

def steps_of(text):
    """The titles of the top-level numbered items under a plan's `## Steps` heading."""
    found, inside = [], False
    for line in (text or "").splitlines():
        if line.startswith("## "):
            inside = line[3:].strip().lower() == "steps"
            continue
        match = re.match(r"^(\d+)\.\s+(.*)$", line) if inside else None
        if match:
            found.append(re.sub(r"\*\*(.*?)\*\*", r"\1", match.group(2)).strip())
    return found


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError, TypeError):
        return None


def jsonl(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record
    except (OSError, TypeError):
        return


def plan_progress_dir():
    folder = os.environ.get("CLAUDE_PLAN_PROGRESS_DIR")
    if folder:
        return folder
    state = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(state, "claude-plan-progress")


def claude_plan(session_id, transcript):
    """The plan of a Claude Code session, or None.

    The plan-progress record that statusline.py of bestcodename/ai keeps per session names the approved plan
    and the steps `plan-step` recorded. It counts as approved only while the transcript holds the
    ExitPlanMode result with the recorded tool_use_id, whose `toolUseResult` carries the plan and its path.
    Without one, the latest `plan_mode` attachment names the plan file of a session still planning.
    """
    record = None
    try:
        with open(os.path.join(plan_progress_dir(), "%s.json" % session_id), "r", encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError):
        pass
    approvals, planning = {}, None
    for entry in jsonl(transcript):
        result = entry.get("toolUseResult")
        if entry.get("type") == "user" and isinstance(result, dict) and "plan" in result:
            content = ((entry.get("message") or {}).get("content") or [{}])
            call = content[0].get("tool_use_id") if isinstance(content, list) and content else None
            approvals[call] = result.get("filePath")
        attachment = entry.get("attachment")
        if entry.get("type") == "attachment" and isinstance(attachment, dict) and attachment.get("planFilePath"):
            planning = attachment["planFilePath"]
    if isinstance(record, dict) and record.get("approval") in approvals:
        path = record.get("plan") or approvals[record["approval"]]
        text = read_text(path)
        if text is not None:
            return {"path": path, "text": text, "phase": "implementation", "approved": True,
                    "done": record.get("done"), "total": record.get("total"), "origin": "plan-progress"}
    text = read_text(planning) if planning else None
    if text is not None:
        return {"path": planning, "text": text, "phase": "planning", "approved": False, "done": None,
                "total": None, "origin": "transcript"}
    return None


def codex_plan(rollout):
    """The latest plan of a Codex thread from its rollout, or None.

    `~/.codex/plans/<thread>/…/PLAN.md` can keep an older plan of the thread, measured on 2026-10-20, so the
    latest `Plan` item in the rollout wins. It counts as approved once a later turn starts outside plan mode,
    which is how the app's "Implement this plan" shows, measured on Codex 0.163.
    """
    text, approved = None, False
    for record in jsonl(rollout):
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if record.get("type") != "event_msg":
            continue
        if payload.get("type") == "item_completed" and (payload.get("item") or {}).get("type") == "Plan":
            text, approved = payload["item"].get("text"), False
        elif payload.get("type") == "task_started" and text is not None:
            approved = approved or payload.get("collaboration_mode_kind") == "default"
    if not text:
        return None
    return {"path": None, "text": text, "phase": "implementation" if approved else "planning",
            "approved": approved, "done": None, "total": None, "origin": "rollout"}


def given_plan(path):
    text = read_text(path)
    if text is None:
        raise HandoffError("%s: plan file cannot be read" % path)
    return {"path": os.path.abspath(path), "text": text, "phase": "implementation", "approved": True,
            "done": None, "total": None, "origin": "option"}


def fork_command(source, account):
    """The one-shot that asks a fork of the source for a plan, read-only and without a saved session."""
    provider, ident = source
    if provider == "claude":
        claude = ["claude-account", "run", account] if account else ["claude"]
        return claude + ["--resume", ident, "--fork-session", "--no-session-persistence", "-p",
                         "--permission-mode", "plan", PLAN_REQUEST]
    return [codex(), "exec", "fork", "-c", 'sandbox_mode="read-only"', "--ephemeral", ident, PLAN_REQUEST]


def codex():
    """The Codex CLI, which the desktop package keeps off PATH."""
    try:
        return agent_eta_providers.executable("codex")
    except agent_eta_providers.AccountError as exc:
        raise HandoffError(str(exc))


# --- snapshot ------------------------------------------------------------------------------

def git_state(cwd, run):
    """Branch, HEAD and dirty paths of the repository a session works in, or {} outside of one."""
    def git(*args):
        result = run(["git", "-C", cwd] + list(args))
        return result.stdout.strip() if result.returncode == 0 else None
    top = git("rev-parse", "--show-toplevel") if cwd else None
    if not top:
        return {}
    status = git("status", "--porcelain") or ""
    return {"toplevel": top, "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "head": git("rev-parse", "--short", "HEAD"),
            "dirty": [line[3:] for line in status.splitlines() if len(line) > 3]}


def handover_section(handoff, plan, git, now):
    steps = steps_of(plan["text"])
    if plan.get("total") is not None and plan.get("done") is not None:
        progress = "%d/%d steps done" % (plan["done"], plan["total"])
        following = plan["done"] + 1
    else:
        progress, following = "not recorded", None
    lines = ["## Handover", "",
             "- Handoff %s from %s to %s on %s" % (handoff["id"], handoff["source"], handoff["target"],
                                                  datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")),
             "- Phase: %s" % ("implementation, the plan is approved" if plan["approved"]
                              else "planning, the plan is not approved yet"),
             "- Progress: %s" % progress]
    if following and following <= len(steps):
        lines.append("- Next step: %d. %s" % (following, steps[following - 1]))
    elif not following and steps:
        lines.append("- Next step: the first step not done yet, checked against the repository")
    lines.append("- Directory: %s" % handoff["cwd"])
    if git:
        dirty = ", ".join(git["dirty"]) if git["dirty"] else "clean"
        lines.append("- Git: %s at %s in %s, tree %s" % (git["branch"], git["head"], git["toplevel"], dirty))
    if re.search(r"^## Verification", plan["text"], re.M):
        lines.append("- Verification: the plan's `## Verification` section")
    if plan.get("path"):
        lines.append("- Original plan: %s" % plan["path"])
    return "\n".join(lines) + "\n"


def handover_prompt(handoff, plan_path, approved):
    prompt = ("agent-eta handoff %s: you take over the work of %s. Read %s, starting with its section "
              "\"Handover\", and continue at the next unfinished step." % (handoff["id"], handoff["source"], plan_path))
    if not approved:
        prompt += " The plan is not approved yet: continue planning only, and ask the user to approve it before changing anything."
    return prompt


def destination_command(target, account, cwd, session_id, approved, prompt):
    """The command that starts the destination. Each provider uses its own model and effort settings."""
    if target == "claude":
        argv = (["claude-account", "run", account] if account else ["claude"]) + ["--session-id", session_id]
        if not approved:
            argv += ["--permission-mode", "plan"]
    else:
        # Codex has no flag that starts in plan mode, so an unapproved plan starts read-only and asks.
        argv = [codex(), "-C", cwd] + ([] if approved else ["-s", "read-only", "-a", "on-request"])
    return argv + [prompt]


def launcher(argv):
    unset = " ".join("-u %s" % name for name in INHERITED)
    return "#!/bin/sh\n%s\nexec env %s %s\n" % (ONE_SHOT, unset, " ".join(shlex.quote(arg) for arg in argv))


# --- records ---------------------------------------------------------------------------------

def handoff_root():
    root = os.environ.get("AGENT_ETA_HANDOFF_DIR") or os.path.expanduser("~/.local/state/agent-eta/handoff")
    os.makedirs(root, mode=0o700, exist_ok=True)
    return root


def write_record(folder, record):
    record["updated"] = int(time.time())
    temporary = os.path.join(folder, ".status.json.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, os.path.join(folder, "status.json"))


def records(root=None):
    """Every handoff record, the newest first."""
    root = root or handoff_root()
    found = []
    for name in os.listdir(root):
        path = os.path.join(root, name, "status.json")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("source"):
            found.append(record)
    return sorted(found, key=lambda record: record.get("created") or 0, reverse=True)


def latest_by_source(root=None):
    found = {}
    for record in records(root):
        found.setdefault(record["source"], record)
    return found


class SourceLock:
    """One handoff per source at a time, across processes."""

    def __init__(self, root, source):
        os.makedirs(os.path.join(root, "locks"), mode=0o700, exist_ok=True)
        self.path = os.path.join(root, "locks", "%s-%s.lock" % source)
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "a")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise HandoffError("a handoff of this source is already running")
        return self

    def __exit__(self, *exc):
        self.handle.close()


# --- the move --------------------------------------------------------------------------------

class Env:
    """What a handoff needs from the system. agent-eta passes collectors for `inspect` and `accounts`."""

    def __init__(self, inspect, accounts, out=print):
        # inspect(source) -> {"state", "waiting_for", "running", "pid", "proc_start", "gate", "cwd",
        #                     "account", "transcript", "rollout"} of a live session, or None.
        self.inspect = inspect
        # accounts() -> [(name, directory)] of the registered Claude accounts.
        self.accounts = accounts
        self.out = out

    def run(self, argv, timeout=60, cwd=None):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd,
                                  stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            return subprocess.CompletedProcess(argv, 127, "", str(exc))

    def proc_start(self, pid):
        try:
            with open("/proc/%d/stat" % pid, "r") as handle:
                return handle.read().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError, ValueError):
            return None

    def signal(self, pid, start, signum):
        """Send signum to pid only while it is still the process that started at `start`."""
        if not pid or self.proc_start(pid) != start:
            return False
        try:
            os.kill(pid, signum)
            return True
        except OSError:
            return False

    def pause(self, unit, pid, start):
        """Freeze pid in the transient scope `unit`, only while it is still the process that started at
        `start`. Raises HandoffError, with the source still running, when that fails."""
        if not pid or self.proc_start(pid) != start:
            raise HandoffError("the source process is gone or was replaced")
        self.freeze(unit, pid)

    def cgroup(self, pid):
        for line in (read_text("/proc/%d/cgroup" % pid) or "").splitlines():
            if line.startswith("0::"):
                return line[3:]
        return None

    def freeze(self, unit, pid):
        if not (self.cgroup(pid) or "").endswith("/" + unit):
            result = self.run(["busctl", "--user", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                               "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))", unit,
                               "fail", "1", "PIDs", "au", "1", str(pid), "0"])
            if result.returncode != 0:
                raise HandoffError("the source cannot move into a scope: %s" % (result.stderr or "").strip())
            for _ in range(50):
                if (self.cgroup(pid) or "").endswith("/" + unit):
                    break
                time.sleep(0.02)
            else:
                raise HandoffError("the source did not move into %s" % unit)
        result = self.run(["systemctl", "--user", "freeze", unit])
        if result.returncode != 0:
            raise HandoffError("the source cannot be frozen: %s" % (result.stderr or "").strip())

    def resume(self, unit):
        """Thaw `unit`. True when nothing of it stays frozen, which includes a unit that is gone."""
        self.run(["systemctl", "--user", "thaw", unit])
        state = self.run(["systemctl", "--user", "show", "-P", "FreezerState", unit]).stdout.strip()
        return state not in ("frozen", "freezing")

    def open_terminal(self, tabs):
        terminal = shlex.split(os.environ.get("AGENT_ETA_HANDOFF_TERMINAL") or "konsole --tabs-from-file")
        env = {key: value for key, value in os.environ.items() if key not in INHERITED}
        subprocess.Popen(terminal + [tabs], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    def registered(self, handoff):
        """Whether the destination of a launched handoff has shown up."""
        if handoff["target"] == "claude":
            for name, directory in self.accounts():
                if handoff["account"] and name and name != handoff["account"]:
                    continue
                for entry in os.scandir(os.path.join(directory, "sessions")) if os.path.isdir(
                        os.path.join(directory, "sessions")) else []:
                    if entry.name.endswith(".json") and handoff["session_id"] in (read_text(entry.path) or ""):
                        return True
            return False
        root = os.path.join(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"), "sessions")
        for folder, _, files in os.walk(root):
            for name in files:
                path = os.path.join(folder, name)
                try:
                    if os.path.getmtime(path) < handoff["launched"] - 5:
                        continue
                    if prompted(path, handoff["id"]):
                        return True
                except OSError:
                    continue
        return False

    def notify(self, text):
        command = shlex.split(os.environ.get("AGENT_ETA_HANDOFF_NOTIFY", "notify-send --app-name=agent-eta"))
        if command:
            self.run(command + ["agent-eta handoff", text], timeout=10)

    def sleep(self, seconds):
        time.sleep(seconds)

    def now(self):
        return time.time()


def scope(handoff):
    """The transient user scope that holds the paused source of a handoff."""
    return "agent-eta-handoff-%s.scope" % handoff["id"]


def prompted(rollout, text, limit=4 << 20):
    """Whether a user message within the first `limit` bytes of a Codex rollout contains `text`. A rollout
    opens with tens of KiB of instructions and context, and other messages may quote a handoff ID."""
    needle, read = text.encode(), 0
    with open(rollout, "rb") as handle:
        for line in handle:
            read += len(line)
            if read > limit:
                break
            if needle not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") != "response_item":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message" or payload.get("role") != "user":
                continue
            parts = payload.get("content") or []
            if any(isinstance(part, dict) and text in str(part.get("text") or "") for part in parts):
                return True
    return False


def safe(session):
    """Whether a session sits at a boundary where it can move: no turn running, nothing waiting for an
    answer and no verified background writer. A stop at the usage limit counts as a boundary."""
    if session.get("running") or session["state"] not in ("idle", "stopped"):
        return False
    return not session.get("waiting_for") or session.get("waiting_for") == "usage limit"


def recorded_plan(source, session):
    return claude_plan(source[1], session.get("transcript")) if source[0] == "claude" \
        else codex_plan(session.get("rollout"))


def resolve_plan(source, session, plan_path, env):
    if plan_path:
        return given_plan(plan_path)
    found = recorded_plan(source, session)
    if found:
        return found
    result = env.run(fork_command(source, session.get("account")), timeout=900, cwd=session.get("cwd"))
    if result.returncode != 0 or not result.stdout.strip():
        raise HandoffError("preparation needed: the source holds no plan and its fork could not write one (%s)"
                           % ((result.stderr or "").strip().splitlines() or ["exit %d" % result.returncode])[-1])
    return {"path": None, "text": result.stdout.strip() + "\n", "phase": "planning", "approved": False,
            "done": None, "total": None, "origin": "fork"}


def choose_account(target, account, env):
    """The Claude account to start in: the one named, else the first eligible one `claude-account targets`
    lists, else the only registered one."""
    if target != "claude" or account:
        return account
    result = env.run(["claude-account", "targets", "--json"], timeout=60)
    if result.returncode == 0:
        try:
            listed = json.loads(result.stdout)
            names = [entry["name"] for entry in listed.get("targets", []) if entry.get("eligible")]
            if names:
                return names[0]
        except (ValueError, AttributeError, KeyError, TypeError):
            pass
    names = [name for name, _ in env.accounts()]
    if len(names) == 1:
        return names[0]
    raise HandoffError("no eligible Claude account found; name one with --account")


def prepare(source, target, account, plan_path, env, root, dry_run=False):
    """The handoff record, the session, the plan and the snapshot text, written unless dry_run."""
    session = env.inspect(source)
    if session is None:
        raise HandoffError("%s:%s is no running session" % source)
    if session.get("gate") is None:
        raise HandoffError("%s:%s: %s" % (source + (session.get("gate_reason") or "it cannot be paused",)))
    account = choose_account(target, account, env)
    plan = resolve_plan(source, session, plan_path, env)
    now = env.now()
    handoff = {"id": "%s-%s" % (datetime.fromtimestamp(now).strftime("%Y%m%d-%H%M%S"), secrets.token_hex(3)),
               "source": "%s:%s" % source, "target": target, "account": account, "cwd": session["cwd"],
               "created": int(now), "state": "prepared", "plan_origin": plan["origin"],
               "session_id": str(uuid.uuid4()) if target == "claude" else None, "launched": None}
    handoff["resume_source"] = "systemctl --user thaw %s" % scope(handoff)
    folder = os.path.join(root, handoff["id"])
    text = snapshot(handoff, plan, env, folder)
    if dry_run:
        return handoff, session, plan, text
    os.makedirs(folder, mode=0o700)
    save(folder, handoff, text)
    return handoff, session, plan, text


def snapshot(handoff, plan, env, folder):
    """Set the phase and the destination command of a handoff and return the text of its plan.md."""
    git = git_state(handoff["cwd"], env.run)
    handoff["phase"] = plan["phase"]
    prompt = handover_prompt(handoff, os.path.join(folder, "plan.md"), plan["approved"])
    handoff["command"] = destination_command(handoff["target"], handoff["account"], handoff["cwd"],
                                             handoff["session_id"], plan["approved"], prompt)
    return plan["text"].rstrip("\n") + "\n\n" + handover_section(handoff, plan, git, env.now())


def save(folder, handoff, text):
    temporary = os.path.join(folder, ".plan.md.tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, os.path.join(folder, "plan.md"))
    write_record(folder, handoff)


def refresh(handoff, session, plan, env, folder):
    """Bring the snapshot up to date once the source is paused, since the turns it ran while the handoff
    waited may have moved its plan and its tree. A plan from --plan or from a fork keeps its text."""
    if plan["origin"] not in ("fork", "option"):
        plan = recorded_plan(parse_source(handoff["source"]), session) or plan
    save(folder, handoff, snapshot(handoff, plan, env, folder))


def launch(handoff, env, root):
    folder = os.path.join(root, handoff["id"])
    script = os.path.join(folder, "launch.sh")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(launcher(handoff["command"]))
    os.chmod(script, 0o700)
    tabs = os.path.join(folder, "tabs.txt")
    title = "Handoff %s %s" % (os.path.basename(handoff["cwd"].rstrip("/")) or "~", handoff["id"][-6:])
    with open(tabs, "w", encoding="utf-8") as handle:
        handle.write("title: %s;; workdir: %s;; command: /bin/sh %s\n" % (title, handoff["cwd"], script))
    env.open_terminal(tabs)


def transfer(handoff, session, plan, env, root, wait):
    """Wait for a safe boundary, pause the source, launch, confirm and end the source. Every way out thaws
    the source: a cancel through Ctrl-C, SIGTERM or SIGHUP records the move as cancelled, any other error as
    failed before it propagates, and a completed move has sent SIGHUP before the thaw."""
    folder = os.path.join(root, handoff["id"])
    try:
        return gated_transfer(handoff, session, plan, env, folder, root, wait)
    except KeyboardInterrupt:
        handoff.update(state="cancelled", error="cancelled"
                       + ("" if not handoff.get("launched") else "; the destination window stays open"))
        write_record(folder, handoff)
        return False
    except Exception as exc:
        handoff.update(state="failed", error="%s: %s" % (type(exc).__name__, exc))
        write_record(folder, handoff)
        raise
    finally:
        if not env.resume(scope(handoff)):
            handoff.update(error="%s; the source is still frozen, run resume_source" % handoff.get("error"))
            write_record(folder, handoff)


def gated_transfer(handoff, session, plan, env, folder, root, wait):
    source = parse_source(handoff["source"])
    deadline = env.now() + wait
    pid, start, unit = session["gate"], session["proc_start"], scope(handoff)
    while True:
        current = env.inspect(source)
        if current is None:
            handoff.update(state="failed", error="the source ended before the move")
            write_record(folder, handoff)
            return False
        if safe(current):
            try:
                env.pause(unit, pid, start)
            except HandoffError as exc:
                handoff.update(state="failed", error=str(exc))
                write_record(folder, handoff)
                return False
            again = env.inspect(source)
            if again is not None and safe(again):
                break
            if not env.resume(unit):
                raise HandoffError("the source cannot be thawed after it turned busy")
        if env.now() >= deadline:
            handoff.update(state="waiting", error="no safe boundary within %d s; nothing was changed" % wait)
            write_record(folder, handoff)
            return False
        env.sleep(POLL)
    refresh(handoff, again, plan, env, folder)
    try:
        launch(handoff, env, root)
    except OSError as exc:
        handoff.update(state="failed", error="launch failed: %s" % exc)
        write_record(folder, handoff)
        return False
    handoff.update(state="launched", launched=int(env.now()))
    write_record(folder, handoff)
    registered_by = env.now() + REGISTER_TIMEOUT
    while not env.registered(handoff):
        if env.now() >= registered_by:
            handoff.update(state="failed", error="the destination did not register within %d s" % REGISTER_TIMEOUT)
            write_record(folder, handoff)
            return False
        env.sleep(min(1, POLL))
    env.signal(pid, start, signal.SIGHUP)
    handoff.update(state="completed", error=None)
    write_record(folder, handoff)
    return True


def delegate_claude(source, account, wait, env, session):
    """Claude to Claude stays a resume, which claude-account handoff already does."""
    if not account:
        raise HandoffError("name the destination account with --account")
    if session.get("account") is None:
        raise HandoffError("the source account has no registered name")
    result = env.run(["claude-account", "handoff", session["account"], account, "--only", source[1],
                      "--wait", str(int(wait))], timeout=wait + REGISTER_TIMEOUT + 60)
    if result.returncode != 0:
        raise HandoffError((result.stderr or result.stdout or "claude-account handoff failed").strip())
    return result.stdout.strip()


def handoff_one(text, target, account, plan_path, wait, dry_run, env, root):
    source = parse_source(text)
    if dry_run:
        if source[0] == "claude" and target == "claude":
            return {"source": text, "delegate": ["claude-account", "handoff", "…", account or "?", "--only", source[1]]}
        handoff, _, _, text = prepare(source, target, account, plan_path, env, root, dry_run=True)
        return dict(handoff, plan=text)
    with SourceLock(root, source):
        previous = latest_by_source(root).get(text)
        if previous and previous.get("state") in SETTLED:
            return dict(previous, note="already handed off")
        if source[0] == "claude" and target == "claude":
            session = env.inspect(source)
            if session is None:
                raise HandoffError("%s is no running session" % text)
            return {"source": text, "state": "completed", "report": delegate_claude(source, account, wait, env, session)}
        handoff, session, plan, _ = prepare(source, target, account, plan_path, env, root)
        transfer(handoff, session, plan, env, root, wait)
        return handoff


def interrupt(signum, frame):
    raise KeyboardInterrupt


def run(sources, target, account=None, plan_path=None, wait=1800, dry_run=False, env=None, root=None):
    """Hand every source over, one after another, and report each separately. A cancel ends the batch.
    Returns the exit code."""
    root = root or handoff_root()
    previous = {} if dry_run else {signum: signal.signal(signum, interrupt)
                                   for signum in (signal.SIGTERM, signal.SIGHUP)}
    try:
        return run_all(sources, target, account, plan_path, wait, dry_run, env, root)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_all(sources, target, account, plan_path, wait, dry_run, env, root):
    failed = False
    for text in sources:
        try:
            result = handoff_one(text, target, account, plan_path, wait, dry_run, env, root)
        except HandoffError as exc:
            result, failed = {"source": text, "state": "refused", "error": str(exc)}, True
        if result.get("state") in ("failed", "waiting", "cancelled"):
            failed = True
        env.out(json.dumps(result, indent=2, sort_keys=True))
        if not dry_run and result.get("state") in ("completed", "failed", "waiting", "cancelled"):
            env.notify("%s → %s: %s" % (text, target, result.get("error") or result["state"]))
        if result.get("state") == "cancelled":
            break
    return 1 if failed else 0


def add_parser(sub):
    parser = sub.add_parser("handoff", help="hand sessions over to Claude Code or Codex with their plan")
    parser.add_argument("sources", nargs="+", metavar="SOURCE", help="claude:<session> or codex:<thread>")
    parser.add_argument("--to", required=True, choices=("claude", "codex"))
    parser.add_argument("--account", help="the Claude account to start in")
    parser.add_argument("--plan", help="the plan file to continue, instead of the source's own")
    parser.add_argument("--wait", type=int, default=1800, help="seconds to wait for a safe boundary")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen and change nothing")
    return parser
