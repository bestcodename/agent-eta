"""Account inventory, persistent usage cache and shared CLI actions.

Session state remains in /tmp. Account preferences and sanitized readings survive
reboots. Test callers can isolate both through AGENT_ETA_DIR or explicit paths.
"""

import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from agent_eta_providers import AccountError, claude_read, codex_read, executable, launch

REFRESH_SECONDS = 300


def read_json(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            name = handle.name
            json.dump(data, handle, sort_keys=True)
            handle.write("\n")
        os.replace(name, path)
    except OSError:
        raise AccountError("Account preferences or usage cache could not be saved") from None
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def file_lock(path, nonblocking=False):
    try:
        Path(path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        raise AccountError("Account preferences or usage cache cannot be opened") from None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        yield fd
    finally:
        os.close(fd)


class AccountStore:
    def __init__(self):
        isolated = os.environ.get("AGENT_ETA_DIR")
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
        self.config_path = Path(os.environ.get("AGENT_ETA_CONFIG", str(Path(isolated) / "account-config.json" if isolated else config_home / "agent-eta/config.json")))
        self.cache_dir = Path(os.environ.get("AGENT_ETA_CACHE_DIR", str(Path(isolated) / "accounts" if isolated else cache_home / "agent-eta")))
        self.cache_path = self.cache_dir / "accounts.json"
        self.worker_lock = self.cache_dir / "refresh.lock"

    def settings(self):
        return read_json(self.config_path)

    def configure(self, change):
        with file_lock(str(self.config_path) + ".lock"):
            data = self.settings()
            change(data)
            write_json(self.config_path, data)

    def update(self, change):
        with file_lock(self.cache_dir / "cache.lock"):
            data = read_json(self.cache_path)
            change(data)
            write_json(self.cache_path, data)

    def inventory(self, include_disabled=False):
        settings = self.settings()
        registry = Path(os.environ.get("CLAUDE_ACCOUNTS_FILE", str(Path.home() / ".config/claude-account/accounts.json")))
        registered = [a for a in read_json(registry).get("accounts", [])
                      if isinstance(a, dict) and isinstance(a.get("name"), str) and isinstance(a.get("dir"), str)]
        accounts = []
        for item in registered:
            accounts.append({"id": "claude:" + item["name"], "provider": "claude", "name": item["name"],
                             "agent": "claude/" + item["name"] if len(registered) > 1 else "claude",
                             "email": item.get("email"), "directory": str(Path(item["dir"]).expanduser()),
                             "registered": True, "can_remove": True})
        if not registered:
            directory = os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude"))
            if directory not in settings.get("removed_claude_directories", []):
                accounts.append({"id": "claude:default", "provider": "claude", "name": None, "agent": "claude",
                                 "directory": directory, "registered": False, "can_remove": False})
        if include_disabled or not settings.get("codex_disabled", False):
            accounts.append({"id": "codex", "provider": "codex", "name": None, "agent": "codex",
                             "directory": os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
                             "registered": False, "can_remove": True})
        for account in accounts:
            account["default_directory"] = settings.get("default_directories", {}).get(account["id"], str(Path.home()))
        return accounts

    @staticmethod
    def cache_key(account):
        # A directory moved to another registration must not inherit another account's cache.
        return account["id"] + ":" + os.path.realpath(account["directory"])

    def find(self, identifier):
        for account in self.inventory():
            if account["id"] == identifier:
                return account
        raise AccountError("The account is not registered or monitored")

    def snapshot(self, local_windows=(), now=None):
        now = time.time() if now is None else now
        inventory = self.inventory()
        # Import newer local readings once, so bounded transcript scans cannot erase them.
        def ingest(cache):
            records = cache.setdefault("accounts", {})
            for account in inventory:
                record = records.setdefault(self.cache_key(account), {})
                windows = [w for w in local_windows if w.get("agent") == account["agent"]]
                seen = max((w.get("seen_at") or 0 for w in windows), default=0)
                newer = seen > max(record.get("seen_at") or 0, record.get("identity_changed_at") or 0)
                first = windows and not record.get("windows") and not record.get("identity_changed_at")
                if (newer or first) and record.get("auth_state") != "logged_out":
                    record["windows"] = [{k: w.get(k) for k in ("minutes", "used", "resets_at")} for w in windows]
                    record["seen_at"] = seen or None
        if local_windows:
            self.update(ingest)
        records = read_json(self.cache_path).get("accounts", {})
        accounts, windows = [], []
        for account in inventory:
            record = records.get(self.cache_key(account), {})
            auth = record.get("auth_state", "unknown")
            seen = record.get("seen_at")
            # A mismatch keeps its readings. The status line records them per config directory, so they
            # belong to the login stored there, while the email behind a mismatch is a cached profile copy.
            reading = record.get("windows", []) if auth != "logged_out" else []
            expired = any(not w.get("resets_at") or w["resets_at"] <= now for w in reading)
            current = reading and not expired and seen and seen >= now - REFRESH_SECONDS and not record.get("error")
            status = "current" if current else "stale" if reading else "unavailable"
            accounts.append({k: account[k] for k in ("id", "provider", "agent", "name", "can_remove", "default_directory")})
            accounts[-1].update(auth_state=auth, usage_status=status, seen_at=seen, checked_at=record.get("checked_at"),
                                error=record.get("error"))
            for window in reading:
                windows.append(dict(window, agent=account["agent"], account_id=account["id"], seen_at=seen,
                                    usage_status=status, auth_state=auth))
        return {"accounts": accounts, "usage": windows}

    def maybe_refresh(self, cli_path, now=None):
        """Hand one lock to one worker. Repeated polls do not create a queue of workers."""
        if os.environ.get("AGENT_ETA_NO_REFRESH") == "1":
            return False
        now = time.time() if now is None else now
        try:
            with file_lock(self.worker_lock, nonblocking=True) as fd:
                attempted = read_json(self.cache_path).get("refresh_attempted_at")
                if attempted is not None and 0 <= now - attempted < REFRESH_SECONDS:
                    return False
                self.update(lambda cache: cache.update(refresh_attempted_at=now))
                subprocess.Popen([sys.executable, str(cli_path), "account", "refresh", "--lock-fd", str(fd)],
                                 pass_fds=(fd,), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                return True
        except BlockingIOError:
            return False
        except OSError:
            return False

    def refresh(self, lock_fd=None, now=None):
        now = time.time() if now is None else now
        # The inherited worker descriptor already holds the same open-file-description lock.
        if lock_fd is not None:
            try:
                own = os.stat(self.worker_lock)
                inherited = os.fstat(lock_fd)
                if (own.st_dev, own.st_ino) != (inherited.st_dev, inherited.st_ino):
                    raise AccountError("Invalid refresh worker lock")
                return self._refresh(now)
            finally:
                os.close(lock_fd)
        try:
            with file_lock(self.worker_lock, nonblocking=True):
                attempted = read_json(self.cache_path).get("refresh_attempted_at")
                if attempted is not None and 0 <= now - attempted < REFRESH_SECONDS:
                    return False
                self.update(lambda cache: cache.update(refresh_attempted_at=now))
                return self._refresh(now)
        except BlockingIOError:
            return False

    def _refresh(self, now):
        deadline = time.monotonic() + 30
        for account in self.inventory():
            timeout = min(10, deadline - time.monotonic())
            try:
                if timeout <= 0:
                    raise AccountError("Account refresh timed out")
                result = codex_read(timeout) if account["provider"] == "codex" else claude_read(account, timeout)
            except AccountError as error:
                result = {"auth_state": "unknown", "error": str(error)}
            def save(cache):
                record = cache.setdefault("accounts", {}).setdefault(self.cache_key(account), {})
                if result.get("identity") and record.get("identity") and result["identity"] != record["identity"]:
                    record.update(windows=[], seen_at=None, identity_changed_at=now)
                if result["auth_state"] == "logged_out":
                    record.update(windows=[], seen_at=None, identity_changed_at=now)
                record.update({k: result[k] for k in ("identity", "auth_state", "auth_type") if k in result})
                record.update(checked_at=now, error=result.get("error"))
                if result.get("windows"):
                    record.update(windows=result["windows"], seen_at=now)
            self.update(save)
        return True


def valid_directory(directory):
    path = Path(directory).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise AccountError("The session directory must be an existing absolute directory")
    return str(path)


def account_action(args):
    store = AccountStore()
    action = args.account_action
    if action == "enable":
        store.configure(lambda data: data.update(codex_disabled=False))
    elif action == "refresh":
        store.refresh(args.lock_fd)
    elif action not in ("list",):
        account = store.find(args.id)
        if action in ("launch", "login"):
            chosen = getattr(args, "directory", None)
            directory = valid_directory(account["default_directory"] if chosen is None else chosen)
            launch(account, directory, login=action == "login")
        elif action == "default-directory":
            if args.directory is None:
                print(account["default_directory"])
            else:
                directory = valid_directory(args.directory)
                store.configure(lambda data: data.setdefault("default_directories", {}).update({account["id"]: directory}))
        elif action == "remove":
            if account["provider"] == "codex":
                store.configure(lambda data: data.update(codex_disabled=True))
            elif account["registered"]:
                try:
                    result = subprocess.run([executable("claude-account"), "remove", account["name"]],
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    raise AccountError("Claude account could not be removed") from None
                if result.returncode:
                    raise AccountError("Claude account could not be removed")
                store.configure(lambda data: data.setdefault("removed_claude_directories", []).append(account["directory"]))
            else:
                raise AccountError("The primary account is not registered and cannot be removed")
    if action in ("list", "refresh"):
        data = store.snapshot()
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            for account in data["accounts"]:
                print("%s  %s  %s  %s" % (account["id"], account["auth_state"], account["usage_status"], account["default_directory"]))
    return 0


def add_parser(sub):
    account = sub.add_parser("account", help="account status, login, monitoring and session launch")
    actions = account.add_subparsers(dest="account_action", required=True)
    for action in ("list", "refresh"):
        parser = actions.add_parser(action)
        parser.add_argument("--json", action="store_true")
        if action == "refresh":
            parser.add_argument("--lock-fd", type=int, help=argparse.SUPPRESS)
    parser = actions.add_parser("enable", help="restore Codex monitoring")
    parser.add_argument("id", choices=["codex"])
    for action in ("login", "remove", "launch", "default-directory"):
        parser = actions.add_parser(action)
        parser.add_argument("id", help="codex, claude:NAME or claude:default")
        if action == "launch":
            parser.add_argument("--directory")
        elif action == "default-directory":
            parser.add_argument("directory", nargs="?")
