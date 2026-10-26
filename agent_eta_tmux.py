"""Managed CLI terminals, independent of their viewers and handoff controllers.

One private tmux server runs in a transient user service. Each agent runs in its own
scope, so freezing or cancelling one agent never affects another pane. The records
are runtime ownership metadata; native clients remain authoritative for session IDs.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import uuid

INHERITED = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SSE_PORT", "CLAUDE_CODE_ENTRYPOINT",
             "CLAUDE_CONFIG_DIR", "CLAUDE_PID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SANDBOX",
             "CODEX_SANDBOX_NETWORK_DISABLED")
SERVICE_CONTEXT = ("INVOCATION_ID", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID", "NOTIFY_SOCKET", "LISTEN_PID",
                   "LISTEN_FDS", "LISTEN_FDNAMES", "WATCHDOG_PID", "WATCHDOG_USEC")


class TmuxError(Exception):
    """A bounded launch, ownership or navigation failure."""


def proc_start(pid):
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()
        return fields[19] if fields[0] != "Z" else None
    except (OSError, ValueError, IndexError, TypeError):
        return None


def cgroup(pid):
    try:
        return next(line[3:] for line in Path(f"/proc/{int(pid)}/cgroup").read_text().splitlines()
                    if line.startswith("0::"))
    except (OSError, ValueError, StopIteration, TypeError):
        return None


def lineage(pid):
    found = []
    while pid and pid > 1 and len(found) < 16 and pid not in found:
        found.append(pid)
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            break
    return found


def launcher(argv, environment=None):
    """Clear provider/service markers, then explicitly apply the chosen account."""
    unset = " ".join("-u " + name for name in INHERITED + SERVICE_CONTEXT)
    values = [name + "=" + str(value) for name, value in (environment or {}).items()
              if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)]
    return "#!/bin/sh\nexec env %s %s\n" % (unset, shlex.join(values + list(argv)))


def protected(path):
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
    except OSError as exc:
        raise TmuxError(f"{path}: cannot prepare the private runtime ({exc.strerror})") from None
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise TmuxError(f"{path}: expected an owned directory with mode 0700")
    return path


def account_environment():
    adapter = shlex.join([sys.executable, str(Path(__file__).resolve()), "account-tabs"])
    return dict(os.environ, CLAUDE_HANDOFF_TERMINAL=adapter)


class Runtime:
    def __init__(self, root=None):
        state = Path(root or os.environ.get("AGENT_ETA_DIR") or f"/tmp/agent-eta-{os.getuid()}")
        self.root = protected(protected(state) / "tmux")
        self.socket = str(self.root / "socket")
        if len(os.fsencode(self.socket)) > 100:
            raise TmuxError("AGENT_ETA_DIR is too long for a tmux socket; use a shorter runtime path")
        digest = hashlib.sha256(self.socket.encode()).hexdigest()[:12]
        self.unit = f"agent-eta-tmux-{digest}.service"

    def run(self, argv, check=True, timeout=30):
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise TmuxError(str(exc)) from None
        if check and result.returncode:
            raise TmuxError((result.stderr or result.stdout or "command failed").strip())
        return result

    def tmux(self, *args, check=True):
        if not shutil.which("tmux"):
            raise TmuxError("tmux is required for managed CLI sessions; install tmux first")
        return self.run(["tmux", "-f", "/dev/null", "-S", self.socket, *args], check=check)

    def write(self, record):
        path = self.root / (record["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2) + "\n")
        temporary.replace(path)

    def read(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise TmuxError("invalid managed terminal ID")
        try:
            return json.loads((self.root / (identifier + ".json")).read_text())
        except (OSError, ValueError):
            raise TmuxError("managed terminal record is unavailable") from None

    def host(self):
        """Identify the private server before creating or targeting any pane."""
        result = self.tmux("display-message", "-p", "#{pid}", check=False)
        if result.returncode:
            return None
        try:
            pid = int(result.stdout.strip())
        except ValueError:
            raise TmuxError("the private tmux server returned an invalid identity") from None
        start = proc_start(pid)
        if not start or not (cgroup(pid) or "").endswith("/" + self.unit):
            raise TmuxError("the private tmux server is outside its managed service")
        return {"server_pid": pid, "server_start": start}

    def pane(self, record):
        """Validate server and pane identities; tmux IDs can be reused after a server restart."""
        if record.get("server_start"):
            if proc_start(record.get("server_pid")) != record["server_start"]:
                return None
        else:
            # A failed start can leave only the pre-launch intent. Locate it on our
            # independently owned server before cancelling, never on another socket.
            if not self.host():
                return None
        target = record.get("pane") or record["target"]
        result = self.tmux("display-message", "-p", "-t", target,
                           "#{session_id}\t#{window_id}\t#{pane_id}\t#{pane_pid}", check=False)
        fields = result.stdout.strip().split("\t")
        if result.returncode or len(fields) != 4:
            return None
        try:
            pid = int(fields[3])
        except ValueError:
            return None
        start = proc_start(pid)
        if not start:
            return None
        if record.get("pane_pid") and (pid != record["pane_pid"] or start != record["pane_start"]):
            return None
        return {"session": fields[0], "window": fields[1], "pane": fields[2],
                "pane_pid": pid, "pane_start": start}

    def start(self, argv, cwd, session=None, environment=None, identifier=None):
        """Launch detached; write ownership before starting so failed launches can be cancelled."""
        identifier = identifier or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise TmuxError("invalid managed terminal ID")
        scope = "agent-eta-agent-" + identifier + ".scope"
        folder = protected(self.root / identifier)
        script = folder / "launch.sh"
        adapter = account_environment()["CLAUDE_HANDOFF_TERMINAL"]
        script.write_text(launcher(argv, dict(environment or {}, CLAUDE_HANDOFF_TERMINAL=adapter)))
        script.chmod(0o700)
        command = ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--expand-environment=no", "--unit=" + scope,
                   "--", "/bin/sh", str(script)]
        record = {"id": identifier, "scope": scope, "cwd": str(cwd), "created": time.time()}
        with (self.root / "host.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            sessions = self.tmux("list-sessions", "-F", "#{session_id}", check=False)
            existing = sessions.stdout.splitlines() if sessions.returncode == 0 else []
            if existing:
                host = self.host()
                if not host:
                    raise TmuxError("the private tmux server exited before launch")
                record.update(host)
                session = session if session in existing else existing[0]
                record["target"] = session + ":" + identifier
                self.write(record)
                self.tmux("new-window", "-d", "-t", session + ":", "-n", identifier,
                          "-c", str(cwd), "--", *command)
            else:
                record["target"] = "agents:" + identifier
                self.write(record)
                variables = ["--setenv=" + name for name in sorted(os.environ)
                             if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
                             and name not in INHERITED + SERVICE_CONTEXT + ("TMUX", "TMUX_PANE")]
                self.run(["systemd-run", "--user", "--collect", "--quiet", "--service-type=forking",
                          "--property=ExitType=cgroup", "--property=GuessMainPID=no", "--unit=" + self.unit,
                          "--expand-environment=no", "--property=UnsetEnvironment="
                          + " ".join(INHERITED + ("TMUX", "TMUX_PANE")), *variables, "--",
                          "tmux", "-f", "/dev/null", "-S", self.socket, "new-session", "-d",
                          "-s", "agents", "-n", identifier, "-c", str(cwd), "--", *command])
            host = self.host()
            if not host:
                raise TmuxError("the managed command exited during launch")
            record.update(host)
            self.write(record)
            pane = self.pane(record)
            if not pane:
                self.write(record)
                raise TmuxError("the managed command exited during launch")
            record.update(pane)
            self.write(record)
            self.tmux("set-option", "-w", "-t", record["window"], "remain-on-exit", "off")
        return record

    def find(self, pid, start):
        if not start or proc_start(pid) != start:
            return None
        group = cgroup(pid)
        for path in self.root.glob("*.json"):
            try:
                record = json.loads(path.read_text())
                if group and group.endswith("/" + record["scope"]) and self.pane(record):
                    return record
            except (OSError, ValueError, KeyError, TypeError, TmuxError):
                continue
        return None

    def stop(self, identifier):
        """Cancel the pane's launcher first, then its complete scope; confirm both are gone."""
        try:
            record = self.read(identifier)
        except TmuxError:
            # start() writes its intent before it can create a pane or scope.
            if re.fullmatch(r"[a-f0-9]{32}", identifier) and not (self.root / (identifier + ".json")).exists():
                return True
            raise
        pane = self.pane(record)
        if pane:
            self.tmux("kill-pane", "-t", pane["pane"], check=False)
        # A frozen source must never run again after its replacement registers.
        # SIGKILL also works while frozen; stop alone can reject a frozen scope.
        self.run(["systemctl", "--user", "kill", "--signal=SIGKILL", "--kill-whom=all", record["scope"]], check=False)
        # Once the launcher has exited it cannot enqueue another scope creation.
        deadline = time.monotonic() + 5
        owner = pane or record
        while owner.get("pane_start") and proc_start(owner["pane_pid"]) == owner["pane_start"]:
            if time.monotonic() >= deadline:
                return False
            time.sleep(.05)
        self.run(["systemctl", "--user", "stop", record["scope"]], check=False)
        while True:
            state = self.run(["systemctl", "--user", "show", "-P", "ActiveState", record["scope"]], check=False)
            if not self.pane(record) and state.stdout.strip() in ("", "inactive", "failed"):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(.05)

    def select(self, record):
        pane = self.pane(record)
        if not pane:
            raise TmuxError("the managed terminal has ended")
        self.tmux("select-window", "-t", pane["window"])
        self.tmux("select-pane", "-t", pane["pane"])

    def clients(self):
        result = self.tmux("list-clients", "-F", "#{client_pid}\t#{client_activity}\t#{client_tty}\t#{session_id}",
                           check=False)
        found = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 4:
                try:
                    found.append({"pid": int(fields[0]), "activity": int(fields[1]),
                                  "tty": fields[2], "session": fields[3]})
                except ValueError:
                    pass
        return sorted(found, key=lambda item: item["activity"], reverse=True)

    def attach(self, record, interactive=False):
        self.select(record)
        if interactive:
            if os.environ.get("TMUX", "").rsplit(",", 2)[0] == self.socket:
                self.tmux("switch-client", "-t", record["session"])
                return {"opened": False, "pids": []}
            env = dict(os.environ)
            env.pop("TMUX", None)
            os.execvpe("tmux", ["tmux", "-S", self.socket, "attach-session", "-t", record["session"]], env)
        clients = self.clients()
        if clients:
            client = next((c for c in clients if c["session"] == record["session"]), clients[0])
            self.tmux("switch-client", "-c", client["tty"], "-t", record["session"])
            return {"opened": False, "pids": lineage(client["pid"])}
        from agent_eta_providers import executable, spawn
        terminal = executable("terminal")
        command = [terminal] + (["--separate"] if Path(terminal).name == "konsole" else [])
        command += ["-e", "tmux", "-S", self.socket, "attach-session", "-t", record["session"]]
        env = dict(os.environ)
        env.pop("TMUX", None)
        env.pop("TMUX_PANE", None)
        spawn(command, env)
        return {"opened": True, "pids": []}


def account_tabs(path):
    """claude-account's local terminal extension; account/transcript migration stays native."""
    runtime = Runtime()
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = dict(part.split(":", 1) for part in line.split(";;") if ":" in part)
        fields = {key.strip(): value.strip() for key, value in fields.items()}
        identifier = uuid.uuid4().hex
        try:
            record = runtime.start(shlex.split(fields["command"]), fields["workdir"], identifier=identifier)
        except (TmuxError, OSError) as error:
            try:
                cancelled = runtime.stop(identifier)
            except TmuxError:
                cancelled = False
            if not cancelled:
                raise TmuxError(str(error) + "; terminal cleanup is unconfirmed") from None
            raise
        runtime.attach(record)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 3 or sys.argv[1] != "account-tabs":
            raise TmuxError("expected account-tabs FILE")
        account_tabs(sys.argv[2])
    except (TmuxError, OSError, KeyError, ValueError) as error:
        print("agent-eta tmux: " + str(error), file=sys.stderr)
        sys.exit(1)
