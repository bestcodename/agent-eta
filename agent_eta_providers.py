"""Bounded native account reads and process launches without handling credentials.

The native clients own authentication. Only allowlisted account metadata and usage
windows cross this boundary; native stderr and full responses never become diagnostics.
"""

import hashlib
import json
import math
import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path


class AccountError(Exception):
    """A safe, user-facing account or launch failure."""


def executable(kind):
    """Resolve desktop binaries even when Plasma's PATH lacks ~/.local/bin."""
    candidates = {
        "codex": [os.environ.get("AGENT_ETA_CODEX_BIN"), shutil.which("codex"), "/usr/lib/chatgpt/resources/codex"],
        "claude": [os.environ.get("CLAUDE_BIN"), str(Path.home() / ".local/bin/claude"), shutil.which("claude")],
        "claude-account": [os.environ.get("AGENT_ETA_CLAUDE_ACCOUNT_BIN"), str(Path.home() / ".local/bin/claude-account"),
                           shutil.which("claude-account")],
        "terminal": [os.environ.get("AGENT_ETA_TERMINAL_BIN"), shutil.which("konsole")],
        "opener": [os.environ.get("AGENT_ETA_OPENER_BIN"), shutil.which("xdg-open")],
    }
    override = candidates[kind][0]
    paths = [override] if override else candidates[kind][1:]
    for path in paths:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise AccountError("%s executable is unavailable" % kind)


def identity(value):
    """Keep an account fingerprint, not an email or a native authentication object."""
    return hashlib.sha256(str(value).encode()).hexdigest() if value else None


def claude_command(account, arguments):
    env = dict(os.environ)
    if account.get("registered"):
        return [executable("claude-account"), "run", account["name"], *arguments], env
    env["CLAUDE_CONFIG_DIR"] = account["directory"]
    return [executable("claude"), *arguments], env


def claude_read(account, timeout=10):
    command, env = claude_command(account, ["auth", "status", "--json"])
    try:
        result = subprocess.run(command, env=env, capture_output=True, timeout=timeout, text=True)
        data = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise AccountError("Claude authentication status is unavailable") from None
    # Claude auth status returns a nonzero code when logged out, alongside valid JSON.
    if not isinstance(data, dict) or not isinstance(data.get("loggedIn"), bool) or (result.returncode and data["loggedIn"]):
        raise AccountError("Claude authentication status is unavailable")
    email = data.get("email")
    mismatch = data["loggedIn"] and email and account.get("email") and email.lower() != account["email"].lower()
    return {"auth_state": "mismatch" if mismatch else "authenticated" if data["loggedIn"] else "logged_out",
            "identity": identity(email), "auth_type": data.get("authMethod"), "windows": None}


class CodexClient:
    """One private stdio connection, with an overall deadline and bounded buffering.

    This process never starts or resumes a thread. Terminating it cannot terminate the
    desktop app's app-server. JSON-RPC notifications may arrive between responses.
    """

    def __init__(self, timeout):
        self.deadline = time.monotonic() + timeout
        self.buffer = b""
        self.number = 0
        self.process = None
        self.selector = selectors.DefaultSelector()

    def __enter__(self):
        try:
            self.process = subprocess.Popen([executable("codex"), "app-server", "--listen", "stdio://"],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL)
            self.selector.register(self.process.stdout, selectors.EVENT_READ)
            self.request("initialize", {"clientInfo": {"name": "agent_eta", "title": "Agent ETA", "version": "1.0.0"}})
            self.send({"method": "initialized"})
            return self
        except (OSError, AccountError):
            self.close()
            raise AccountError("Codex account service is unavailable") from None

    def send(self, message):
        try:
            self.process.stdin.write(json.dumps(message).encode() + b"\n")
            self.process.stdin.flush()
        except (OSError, BrokenPipeError):
            raise AccountError("Codex account service is unavailable") from None

    def request(self, method, params=None):
        self.number += 1
        message = {"id": self.number, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        while time.monotonic() < self.deadline:
            if b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    response = json.loads(line)
                except ValueError:
                    raise AccountError("Codex returned an invalid account response") from None
                if not isinstance(response, dict) or response.get("id") != self.number:
                    continue
                if "error" in response or not isinstance(response.get("result"), dict):
                    raise AccountError("Codex account request failed")
                return response["result"]
            if not self.selector.select(max(0, self.deadline - time.monotonic())):
                break
            data = os.read(self.process.stdout.fileno(), 65536)
            if not data:
                raise AccountError("Codex account service is unavailable")
            self.buffer += data
            if len(self.buffer) > 1024 * 1024:
                raise AccountError("Codex account response is too large")
        raise AccountError("Codex account request timed out")

    def close(self):
        self.selector.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()

    def __exit__(self, *_):
        self.close()


def codex_read(timeout=15):
    with CodexClient(timeout) as client:
        account = client.request("account/read", {"refreshToken": False}).get("account")
        if account is None:
            return {"auth_state": "logged_out", "identity": None, "windows": []}
        if not isinstance(account, dict):
            raise AccountError("Codex returned an invalid account response")
        result = {"auth_state": "authenticated", "auth_type": account.get("type"),
                  "identity": identity(account.get("chatgptAccountId") or account.get("email") or account.get("type")),
                  "windows": None}
        if account.get("type") not in ("chatgpt", "chatgptAuthTokens"):
            result["error"] = "Usage is unavailable for this authentication method"
            return result
        try:
            data = client.request("account/rateLimits/read")
        except AccountError as error:
            result["error"] = str(error)
            return result
        # The session classifier consumes the Codex bucket, not an unrelated premium bucket.
        buckets = data.get("rateLimitsByLimitId")
        bucket = buckets.get("codex") if isinstance(buckets, dict) else data.get("rateLimits")
        if not isinstance(bucket, dict):
            result["error"] = "Codex usage is unavailable"
            return result
        result["windows"] = []
        for name in ("primary", "secondary"):
            window = bucket.get(name)
            if not isinstance(window, dict):
                continue
            used, minutes, reset = window.get("usedPercent"), window.get("windowDurationMins"), window.get("resetsAt")
            if (isinstance(used, (int, float)) and not isinstance(used, bool) and math.isfinite(used) and used >= 0
                    and isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and math.isfinite(minutes) and minutes >= 1):
                result["windows"].append({"used": used, "minutes": int(minutes),
                                          "resets_at": reset if isinstance(reset, (int, float)) else None})
        if not result["windows"]:
            result["error"] = "Codex usage is unavailable"
        return result


def spawn(command, env=None):
    try:
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            code = process.wait(timeout=0.2)
            if code != 0:
                raise AccountError("The account action could not be started")
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        raise AccountError("The account action could not be started") from None


def launch(account, directory, login=False):
    """Pass argv directly to processes; no directory or account name becomes shell code."""
    if account["provider"] == "codex" and not login:
        from urllib.parse import urlencode
        spawn([executable("opener"), "codex://threads/new?" + urlencode({"path": directory})])
        return
    if account["provider"] == "claude":
        command, env = claude_command(account, ["auth", "login"] if login else [])
    else:
        command, env = [executable("codex"), "login"], None
    spawn([executable("terminal"), "--separate", "--workdir", directory, "-e", *command], env)
