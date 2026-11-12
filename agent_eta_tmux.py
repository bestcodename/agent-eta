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
import signal
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
# The private server's only configuration; the user's own tmux configuration is never loaded.
CONFIG = str(Path(__file__).resolve().with_name("tmux.conf"))
VIEWER_PREFIX = "view-"
# The CLI the session-window-changed hook calls; see Runtime.guard.
SCRIPT = str(Path(__file__).resolve().with_name("agent-eta"))
PLAIN_PATH = re.compile(r"[A-Za-z0-9_./+-]+")


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


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


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


def config_path():
    """The config.json this process reads, which the guard hook hands on to the CLI."""
    import agent_eta_accounts
    return str(agent_eta_accounts.AccountStore().config_path)


def viewer_duplicates():
    """Whether "viewer_duplicates": true in config.json allows one agent in several viewers."""
    import agent_eta_accounts
    return agent_eta_accounts.AccountStore().settings().get("viewer_duplicates") is True


def remote_client(pid):
    """Whether a tmux client runs below an SSH server, as a viewer opened from another machine does."""
    for parent in lineage(pid):
        try:
            if Path(f"/proc/{parent}/comm").read_text().strip().startswith("sshd"):
                return True
        except OSError:
            pass
    return False


def launcher(argv, environment=None):
    """Clear parent automation markers, then explicitly apply the chosen account.

    NO_COLOR from a tool runner must not disable an interactive agent terminal.
    Keep TERM/COLORTERM so the destination retains its real color capabilities.
    """
    unset = " ".join("-u " + name for name in INHERITED + SERVICE_CONTEXT + ("NO_COLOR",))
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
        return self.run(["tmux", "-f", CONFIG, "-S", self.socket, *args], check=check)

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
        # tmux can asynchronously move its pane leader into a tmux-spawn scope.
        # Keep that leader separate from the child entering our agent scope.
        command = ["/bin/sh", "-c", '"$@"; exit $?', "agent-eta-pane", *command]
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
                          "tmux", "-f", CONFIG, "-S", self.socket, "new-session", "-d",
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
            self.watch(record["window"])
        return record

    def watch(self, window):
        """Keep the pane after its agent exits, so a pane-died hook can close every viewer showing it
        before the window goes; tmux would otherwise show another agent in those viewers. The hook
        only kills sessions and the window, never detaches a client (docs/agent-eta.md)."""
        if not re.fullmatch(r"@\d+", window or ""):
            raise TmuxError("invalid tmux window ID")
        # #{hook_window} is empty in pane-died, so the window ID is written into the hook itself.
        close = ("run-shell -C \"#{S:#{?#{&&:#{m:%s*,#{session_name}},#{==:#{window_id},%s}},"
                 "kill-session -t '=#{session_name}' ; ,}}kill-window -t %s\"") % (VIEWER_PREFIX, window, window)
        self.tmux("set-option", "-w", "-t", window, "remain-on-exit", "on")
        self.tmux("set-hook", "-w", "-t", window, "pane-died", close)

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
        """Cancel the owned launcher group and agent scope; confirm both are gone."""
        try:
            record = self.read(identifier)
        except TmuxError:
            # start() writes its intent before it can create a pane or scope.
            if re.fullmatch(r"[a-f0-9]{32}", identifier) and not (self.root / (identifier + ".json")).exists():
                return True
            raise
        pane = self.pane(record)
        owner = pane or record
        pid, start = owner.get("pane_pid"), owner.get("pane_start")
        if pid and proc_start(pid) == start:
            try:
                if os.getpgid(pid) != pid:
                    return False
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                raise TmuxError(f"cannot cancel the managed launcher: {exc.strerror}") from None
        if pane and proc_start(record.get("server_pid")) == record.get("server_start"):
            self.tmux("kill-pane", "-t", pane["pane"], check=False)
        # A frozen source must never run again after its replacement registers.
        # SIGKILL also works while frozen; stop alone can reject a frozen scope.
        self.run(["systemctl", "--user", "kill", "--signal=SIGKILL", "--kill-whom=all", record["scope"]], check=False)
        # Once the launcher has exited it cannot enqueue another scope creation.
        deadline = time.monotonic() + 5
        if not pid or not start:
            return False
        while proc_start(pid) == start or (proc_start(pid) is None and group_alive(pid)):
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

    def follow(self, source, destination):
        """Show the destination in every session showing the source, so a handoff keeps its viewers."""
        new = self.pane(destination)
        if not new:
            raise TmuxError("the managed terminal has ended")
        old = self.pane(source)
        if not old:
            return
        result = self.tmux("list-sessions", "-F", "#{session_id}\t#{window_id}", check=False)
        for line in result.stdout.splitlines():
            session, _, window = line.partition("\t")
            if window == old["window"]:
                self.tmux("select-window", "-t", session + ":" + new["window"], check=False)

    def clients(self):
        result = self.tmux("list-clients", "-F",
                           "#{client_pid}\t#{client_activity}\t#{client_tty}\t#{session_id}\t#{window_id}",
                           check=False)
        found = []
        for line in result.stdout.splitlines():
            fields = line.split("\t")
            if len(fields) == 5:
                try:
                    found.append({"pid": int(fields[0]), "activity": int(fields[1]),
                                  "tty": fields[2], "session": fields[3], "window": fields[4]})
                except ValueError:
                    pass
        return sorted(found, key=lambda item: item["activity"], reverse=True)

    def binary(self, record):
        """The running server's own executable for a viewer, else tmux from PATH.
        A package upgrade replaces /usr/bin/tmux while the server keeps the old binary, and a
        client of another version cannot attach ("open terminal failed: not a terminal")."""
        pid = record.get("server_pid")
        if pid and record.get("server_start") and proc_start(pid) == record["server_start"]:
            executable = f"/proc/{int(pid)}/exe"
            if os.access(executable, os.X_OK):
                return executable
        return "tmux"

    def local_client(self, window, session=None):
        """The most recently active client on this machine showing window, other than session's own.
        A client that comes in over SSH has no window here, so it neither counts nor can be focused."""
        return next((c for c in self.clients() if c["window"] == window and c["session"] != session
                     and not remote_client(c["pid"])), None)

    def focus(self, client):
        """Point at a client: a tmux message in it and, under Konsole, its tab made current.
        Raising the window needs KWin, which only the tray widget reaches (WindowJumper.qml)."""
        self.tmux("display-message", "-c", client["tty"], "-d", "3000", "agent-eta: this viewer shows the agent",
                  check=False)
        import agent_eta_konsole as konsole
        try:
            binary = konsole.qdbus()
            found = konsole.find_tab(binary, lineage(client["pid"])) if binary else None
            if found:
                konsole.select(binary, *found)
        except konsole.Unavailable:
            pass
        return lineage(client["pid"])

    def guard(self, name, window):
        """The session-window-changed hook: a viewer that selects an agent another local viewer shows goes
        back to its previous window, and the other viewer is pointed at. Returns whether it went back."""
        if not re.fullmatch(re.escape(VIEWER_PREFIX) + r"[a-f0-9]{12}", name or "") \
                or not re.fullmatch(r"@\d+", window or ""):
            raise TmuxError("invalid viewer session or window")
        if viewer_duplicates():
            return False
        sessions = self.tmux("list-sessions", "-F", "#{session_name}\t#{session_id}", check=False).stdout
        session = next((line.split("\t")[1] for line in sessions.splitlines() if line.startswith(name + "\t")), None)
        if not session:
            return False
        # A viewer that came in over SSH shows the agent on another machine's screen, so it duplicates nothing here.
        own = [client for client in self.clients() if client["session"] == session]
        if own and all(remote_client(client["pid"]) for client in own):
            return False
        other = self.local_client(window, session)
        if not other:
            return False
        listed = self.tmux("list-windows", "-t", session, "-F", "#{window_last_flag}\t#{window_id}", check=False)
        last = next((line.split("\t")[1] for line in listed.stdout.splitlines() if line.startswith("1\t")), None)
        # Going back fires the hook again, so a previous window shown elsewhere too would bounce forever.
        back = bool(last) and not self.local_client(last, session)
        if back:
            self.tmux("last-window", "-t", session, check=False)
        for client in self.clients():
            if client["session"] == session:
                self.tmux("display-message", "-c", client["tty"], "-d", "3000",
                          "agent-eta: another viewer shows this agent (%s)" % other["tty"], check=False)
        self.focus(other)
        return back

    def guard_hook(self):
        """session-window-changed hook for viewers, or None when a path cannot be written unquoted.

        tmux counts the clients showing the window, so the CLI runs only when another client may show
        it. AGENT_ETA_DIR makes the CLI act on this server rather than the default one, and
        AGENT_ETA_CONFIG keeps the config this process reads, which AGENT_ETA_DIR would otherwise move."""
        state, config = str(self.root.parent), config_path()
        if not all(PLAIN_PATH.fullmatch(item) for item in (sys.executable, SCRIPT, state, config)):
            return None
        condition = "#{&&:#{m:%s*,#{hook_session_name}},#{>:#{window_active_clients},1}}" % VIEWER_PREFIX
        command = "env AGENT_ETA_DIR=%s AGENT_ETA_CONFIG=%s %s %s viewer-guard #{hook_session_name} #{window_id}" % (
            state, config, sys.executable, SCRIPT)
        return "if-shell -F '%s' \"run-shell -b '%s'\"" % (condition, command)

    def viewer(self, pane, binary="tmux"):
        """tmux argv for a client with its own grouped session, so each viewer keeps its own window.
        destroy-unattached removes that session again once the viewer closes. The last command installs
        the guard hook, or removes it when duplicates are allowed, after the viewer's own window change."""
        name = VIEWER_PREFIX + uuid.uuid4().hex[:12]
        hook = None if viewer_duplicates() else self.guard_hook()
        install = ["set-hook", "-g", "session-window-changed", hook] if hook else \
            ["set-hook", "-gu", "session-window-changed"]
        return [binary, "-f", CONFIG, "-S", self.socket, "new-session", "-t", pane["session"], "-s", name, ";",
                "set-option", "-t", name, "destroy-unattached", "on", ";",
                "select-window", "-t", name + ":" + pane["window"], ";", *install]

    def attach(self, record, interactive=False):
        """Focus a viewer showing the agent, or open one of its own; other viewers keep their window.
        A caller that came in over SSH always gets a viewer of its own, because a viewer on this
        machine's screen is no use to someone at another machine."""
        pane = self.pane(record)
        if not pane:
            raise TmuxError("the managed terminal has ended")
        if interactive:
            inside = os.environ.get("TMUX", "").rsplit(",", 2)[0] == self.socket
            # Without a target tmux resolves the calling viewer's session.
            current = self.tmux("display-message", "-p", "#{session_id}").stdout.strip() if inside else None
            single = not viewer_duplicates() and not remote_client(os.getpid())
            other = self.local_client(pane["window"], current) if single else None
            if other:
                print("agent-eta: a viewer on %s already shows this agent" % other["tty"], file=sys.stderr)
                return {"opened": False, "pids": self.focus(other)}
            if inside:
                self.tmux("select-window", "-t", current + ":" + pane["window"])
                return {"opened": False, "pids": []}
            env = dict(os.environ)
            env.pop("TMUX", None)
            argv = self.viewer(pane, self.binary(record))
            os.execvpe(argv[0], argv, env)
        client = self.local_client(pane["window"])
        if client:
            return {"opened": False, "pids": lineage(client["pid"])}
        open_terminal(self.viewer(pane, self.binary(record)))
        return {"opened": True, "pids": []}


def open_terminal(argv):
    """Run argv in a terminal window of its own, outside any tmux the caller runs in.

    The terminal runs in a transient unit of the user manager, so it gets the graphical session's environment even
    when the caller came in over SSH without DISPLAY, and it outlives a caller that is itself a unit, such as a
    claude-account host move. Without systemd-run the terminal starts from the caller directly.
    """
    from agent_eta_providers import executable, spawn
    terminal = executable("terminal")
    command = [terminal] + (["--separate"] if Path(terminal).name == "konsole" else [])
    command += ["-e", *argv]
    runner = os.environ.get("AGENT_ETA_SYSTEMD_RUN_BIN") or shutil.which("systemd-run")
    if runner:
        command = [runner, "--user", "--collect", "--quiet", "--expand-environment=no", "--"] + command
    env = dict(os.environ)
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    spawn(command, env)


def account_tabs(path):
    """claude-account's terminal extension: every tab of a handoff tabs file becomes a managed tmux agent with a
    viewer. Locally claude-account finds it through CLAUDE_HANDOFF_TERMINAL, and a host move reaches it as
    `agent-eta account-tabs FILE` on the host. Account and transcript migration stay native."""
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
