"""Account/cache regressions using isolated homes and stub native clients only."""

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import agent_eta_accounts as accounts
import agent_eta_providers as providers
from test_agent_eta import eta


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-eta-accounts-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.registry = self.root / "registry.json"
        self.env = mock.patch.dict(os.environ, {
            "HOME": str(self.home), "PATH": "/usr/bin:/bin", "AGENT_ETA_DIR": str(self.root / "state"),
            "CLAUDE_CONFIG_DIR": str(self.root / "claude"), "CODEX_HOME": str(self.root / "codex"),
            "CLAUDE_ACCOUNTS_FILE": str(self.registry), "DSH_HOME": str(self.root / "dsh"),
            "AGENT_ETA_NO_REFRESH": "1", "PYTHONDONTWRITEBYTECODE": "1",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = accounts.AccountStore()

    def registered(self, names=("work", "private")):
        items = []
        for name in names:
            directory = self.root / ("claude-" + name)
            directory.mkdir(exist_ok=True)
            items.append({"name": name, "dir": str(directory), "email": name + "@example.org"})
        self.registry.write_text(json.dumps({"accounts": items}))

    def reading(self, agent="codex", seen=1000, used=80, reset=1600):
        return {"agent": agent, "seen_at": seen, "minutes": 300, "used": used, "resets_at": reset}

    def seed(self, identifier="codex", **fields):
        account = self.store.find(identifier)
        self.store.update(lambda data: data.setdefault("accounts", {}).update({self.store.cache_key(account): fields}))

    def result(self, auth="authenticated", fingerprint="first", windows=None):
        return {"auth_state": auth, "identity": fingerprint, "windows": windows}

    def args(self, action, identifier="codex", **fields):
        return argparse.Namespace(account_action=action, id=identifier, directory=None, json=False, lock_fd=None, **fields)


class Cache(Isolated):
    def test_inventory_contains_accounts_without_readings_and_keeps_auth_unknown(self):
        self.registered()
        data = self.store.snapshot(now=1000)
        self.assertEqual([a["id"] for a in data["accounts"]], ["claude:work", "claude:private", "codex"])
        self.assertEqual(data["usage"], [])
        self.assertTrue(all(a["auth_state"] == "unknown" for a in data["accounts"]))

    def test_one_registered_account_keeps_legacy_usage_label_and_its_actual_directory(self):
        self.registered(("private",))
        account = self.store.find("claude:private")
        self.assertEqual(account["agent"], "claude")
        self.assertEqual(account["directory"], str(self.root / "claude-private"))

    def test_readings_persist_when_the_bounded_rollout_scan_loses_the_old_record(self):
        directory = pathlib.Path(os.environ["CODEX_HOME"]) / "sessions/2026/10/14"
        directory.mkdir(parents=True)
        old = directory / "rollout-old.jsonl"
        old.write_text(json.dumps({"timestamp": "2026-10-10T00:00:00Z", "payload": {
            "type": "token_count", "rate_limits": {"primary": {"window_minutes": 300,
            "used_percent": 80, "resets_at": 2_000_000_000}}}}) + "\n")
        os.utime(old, (1, 1))
        self.assertEqual(len(eta.codex_usage()), 1)
        self.store.snapshot(eta.codex_usage())
        for index in range(eta.USAGE_ROLLOUTS_MAX):
            (directory / ("rollout-empty-%d.jsonl" % index)).write_text("{}\n")
        self.assertEqual(eta.codex_usage(), [])
        restored = accounts.AccountStore().snapshot(eta.codex_usage())
        self.assertEqual([(w["agent"], w["used"]) for w in restored["usage"]], [("codex", 80)])

    def test_cache_lives_in_xdg_directories_when_no_test_state_override_exists(self):
        os.environ.pop("AGENT_ETA_DIR")
        os.environ["XDG_CONFIG_HOME"] = str(self.root / "config")
        os.environ["XDG_CACHE_HOME"] = str(self.root / "cache")
        store = accounts.AccountStore()
        store.snapshot([self.reading()], now=1000)
        self.assertEqual(store.cache_path, self.root / "cache/agent-eta/accounts.json")
        self.assertEqual(store.config_path, self.root / "config/agent-eta/config.json")
        self.assertEqual(store.cache_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(accounts.AccountStore().snapshot(now=1000)["usage"][0]["used"], 80)

    def test_a_failed_refresh_retains_readings_and_marks_auth_unknown_and_usage_stale(self):
        self.store.snapshot([self.reading()], now=1000)
        with mock.patch.object(accounts, "codex_read", side_effect=providers.AccountError("Unavailable")), \
                mock.patch.object(accounts, "claude_read", return_value=self.result()):
            self.store.refresh(now=1100)
        data = self.store.snapshot(now=1100)
        account = next(a for a in data["accounts"] if a["id"] == "codex")
        self.assertEqual((account["auth_state"], account["usage_status"], account["seen_at"]), ("unknown", "stale", 1000))
        self.assertEqual(data["usage"][0]["used"], 80)

    def test_expired_readings_are_unknown_and_do_not_claim_zero_or_keep_a_session_blocked(self):
        data = self.store.snapshot([self.reading(used=100, reset=1100)], now=1200)
        [window] = eta.usage_view(1200, data["usage"])
        self.assertEqual((window["used"], window["remaining"], window["reached"]), (None, None, False))
        self.assertEqual(next(a for a in data["accounts"] if a["id"] == "codex")["usage_status"], "stale")

    def test_live_readings_replace_cache_and_do_not_need_a_session(self):
        self.store.snapshot([self.reading()], now=1000)
        live = self.result(windows=[{"minutes": 300, "used": 35, "resets_at": 2200}])
        with mock.patch.object(accounts, "codex_read", return_value=live), \
                mock.patch.object(accounts, "claude_read", return_value=self.result()):
            self.store.refresh(now=1300)
        data = self.store.snapshot(now=1300)
        self.assertEqual(data["usage"][0]["used"], 35)
        self.assertEqual(next(a for a in data["accounts"] if a["id"] == "codex")["usage_status"], "current")

    def test_logout_keeps_the_account_but_clears_usage_and_rejects_old_local_readings(self):
        self.store.snapshot([self.reading()], now=1000)
        with mock.patch.object(accounts, "codex_read", return_value=self.result("logged_out", None, [])), \
                mock.patch.object(accounts, "claude_read", return_value=self.result()):
            self.store.refresh(now=1100)
        data = self.store.snapshot([self.reading()], now=1200)
        self.assertEqual(data["usage"], [])
        self.assertEqual(next(a for a in data["accounts"] if a["id"] == "codex")["auth_state"], "logged_out")

    def test_a_mismatch_keeps_the_readings_of_its_own_directory(self):
        # The status line records usage per config directory, so the readings belong to the stored
        # login even when its cached profile names another email.
        self.registered()
        self.store.snapshot([self.reading("claude/work", used=25)], now=1000)
        with mock.patch.object(accounts, "codex_read", return_value=self.result()), \
                mock.patch.object(accounts, "claude_read", return_value=self.result("mismatch")):
            self.store.refresh(now=1100)
        data = self.store.snapshot([self.reading("claude/work", seen=1150, used=30)], now=1200)
        work = next(a for a in data["accounts"] if a["id"] == "claude:work")
        self.assertEqual((work["auth_state"], work["usage_status"]), ("mismatch", "current"))
        self.assertEqual([w["used"] for w in data["usage"] if w["agent"] == "claude/work"], [30])

    def test_login_identity_changes_do_not_reuse_another_accounts_readings(self):
        self.seed(identity="old", auth_state="authenticated", windows=[self.reading()], seen_at=1000)
        with mock.patch.object(accounts, "codex_read", return_value=dict(self.result(fingerprint="new"), error="No reading")), \
                mock.patch.object(accounts, "claude_read", return_value=self.result()):
            self.store.refresh(now=1100)
        self.assertEqual(self.store.snapshot([self.reading()], now=1200)["usage"], [])

    def test_claude_and_codex_readings_stay_isolated_and_moved_registrations_do_not_inherit_cache(self):
        self.registered()
        local = [self.reading("claude/work", used=10), self.reading("claude/private", used=90), self.reading(used=40)]
        self.store.snapshot(local, now=1000)
        self.assertEqual([w["used"] for w in self.store.snapshot(now=1000)["usage"]], [10, 90, 40])
        data = json.loads(self.registry.read_text())
        data["accounts"][0]["dir"] = str(self.root / "new-work")
        self.registry.write_text(json.dumps(data))
        self.assertEqual([w["used"] for w in self.store.snapshot(now=1000)["usage"]], [90, 40])

    def test_overlapping_refreshes_use_one_lock_and_the_five_minute_throttle(self):
        with accounts.file_lock(self.store.worker_lock), mock.patch.object(accounts, "codex_read") as read:
            self.assertFalse(self.store.refresh(now=1000))
            read.assert_not_called()
        with mock.patch.object(accounts, "codex_read", return_value=self.result()), \
                mock.patch.object(accounts, "claude_read", return_value=self.result()):
            self.assertTrue(self.store.refresh(now=1000))
            self.assertFalse(self.store.refresh(now=1299))
            self.assertTrue(self.store.refresh(now=1300))

    def test_poll_schedules_only_one_worker_and_passes_the_lock(self):
        os.environ.pop("AGENT_ETA_NO_REFRESH")
        with mock.patch.object(subprocess, "Popen") as popen:
            self.assertTrue(self.store.maybe_refresh("/fake/agent-eta", now=1000))
            self.assertFalse(self.store.maybe_refresh("/fake/agent-eta", now=1001))
            self.assertEqual(popen.call_count, 1)
            self.assertIn("--lock-fd", popen.call_args.args[0])
            self.assertEqual(len(popen.call_args.kwargs["pass_fds"]), 1)

    def test_a_real_worker_keeps_the_inherited_lock_after_the_poll_process_releases_it(self):
        worker = self.root / "worker.py"
        worker.write_text("import time\ntime.sleep(0.3)\n")
        children = []
        original = subprocess.Popen
        def start(*args, **kwargs):
            process = original(*args, **kwargs)
            children.append(process)
            return process
        os.environ.pop("AGENT_ETA_NO_REFRESH")
        with mock.patch.object(subprocess, "Popen", side_effect=start):
            self.assertTrue(self.store.maybe_refresh(worker, now=1000))
            # Even past the throttle, the worker's inherited descriptor still owns the lock.
            self.assertFalse(self.store.maybe_refresh(worker, now=2000))
        children[0].wait(timeout=2)
        with accounts.file_lock(self.store.worker_lock, nonblocking=True):
            pass


class Actions(Isolated):
    def test_codex_remove_disables_monitoring_without_logout_and_enable_restores_it(self):
        with mock.patch.object(subprocess, "run") as run:
            accounts.account_action(self.args("remove"))
            run.assert_not_called()
        self.assertNotIn("codex", [a["id"] for a in self.store.snapshot()["accounts"]])
        accounts.account_action(self.args("enable"))
        self.assertIn("codex", [a["id"] for a in self.store.snapshot()["accounts"]])

    def test_default_directory_persists_and_one_off_launch_does_not_change_it(self):
        directory = self.root / "spaces ' $(touch wrong) ü"
        directory.mkdir()
        args = self.args("default-directory")
        args.directory = str(directory)
        accounts.account_action(args)
        self.assertEqual(self.store.find("codex")["default_directory"], str(directory))
        args = self.args("launch")
        args.directory = str(self.root)
        with mock.patch.object(accounts, "launch") as launch:
            accounts.account_action(args)
            self.assertEqual(launch.call_args.args[1], str(self.root))
        self.assertEqual(self.store.find("codex")["default_directory"], str(directory))

    def test_invalid_directory_is_reported_before_starting_any_process(self):
        args = self.args("launch")
        args.directory = str(self.root / "missing")
        with mock.patch.object(accounts, "launch") as launch, self.assertRaises(providers.AccountError):
            accounts.account_action(args)
        launch.assert_not_called()

    def test_claude_unregister_uses_the_existing_tool_and_preserves_the_directory(self):
        self.registered(("work",))
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.root / "claude-work")
        # A stand-in for `claude-account remove`, which lives in bestcodename/ai: it drops the entry and keeps the
        # directory, as the real tool does.
        tool = self.root / "claude-account-stub"
        tool.write_text("#!" + sys.executable + "\nimport json,sys\n"
                        "path=" + repr(str(self.registry)) + "\n"
                        "assert sys.argv[1]=='remove'\n"
                        "data=json.load(open(path))\n"
                        "data['accounts']=[a for a in data['accounts'] if a['name']!=sys.argv[2]]\n"
                        "json.dump(data,open(path,'w'))\n")
        tool.chmod(0o700)
        os.environ["AGENT_ETA_CLAUDE_ACCOUNT_BIN"] = str(tool)
        accounts.account_action(self.args("remove", "claude:work"))
        self.assertTrue((self.root / "claude-work").is_dir())
        self.assertEqual([a["id"] for a in self.store.inventory()], ["codex"])
        self.registered(("work",))
        self.assertIn("claude:work", [a["id"] for a in self.store.inventory()])

    def test_move_all_sessions_here_hands_off_every_other_claude_account_detached(self):
        self.registered(("work", "private"))
        with mock.patch.object(accounts, "executable", side_effect=lambda kind: "/fake/" + kind), \
                mock.patch.object(subprocess, "Popen") as popen:
            accounts.account_action(self.args("handoff", "claude:private"))
        self.assertEqual(popen.call_args.args[0],
                         ["/fake/claude-account", "handoff", "work", "private", "--all", "--wait", "1800"])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        with self.assertRaises(providers.AccountError):
            accounts.account_action(self.args("handoff", "codex"))

    def test_claude_launch_uses_konsole_argv_without_shell_interpolation(self):
        self.registered()
        account = self.store.find("claude:work")
        directory = str(self.root / "folder ' $(echo never)")
        with mock.patch.object(providers, "executable", side_effect=lambda kind: "/fake/" + kind), \
                mock.patch.object(providers, "spawn") as spawn:
            providers.launch(account, directory)
            self.assertEqual(spawn.call_args.args[0], ["/fake/terminal", "--separate", "--workdir", directory,
                                                     "-e", "/fake/claude-account", "run", "work"])
            providers.launch(account, directory, login=True)
            self.assertEqual(spawn.call_args.args[0][-2:], ["auth", "login"])

    def test_codex_launch_encodes_the_directory_and_login_uses_the_native_cli(self):
        from urllib.parse import parse_qs, urlparse
        directory = str(self.root / "space ü ' $(no) &")
        with mock.patch.object(providers, "executable", side_effect=lambda kind: "/fake/" + kind), \
                mock.patch.object(providers, "spawn") as spawn:
            providers.launch(self.store.find("codex"), directory)
            command = spawn.call_args.args[0]
            self.assertEqual(command[0], "/fake/opener")
            self.assertEqual(parse_qs(urlparse(command[1]).query)["path"], [directory])
            providers.launch(self.store.find("codex"), directory, login=True)
            self.assertEqual(spawn.call_args.args[0][-2:], ["/fake/codex", "login"])

    def test_spawn_failure_and_early_nonzero_exit_are_reported_without_native_stderr(self):
        with self.assertRaises(providers.AccountError):
            providers.spawn(["/does/not/exist"])
        with self.assertRaises(providers.AccountError):
            providers.spawn([sys.executable, "-c", "raise SystemExit(2)"])


class NativeProviders(Isolated):
    def binary(self, source, variable):
        path = self.root / (variable + "-stub")
        path.write_text("#!" + sys.executable + "\n" + source)
        path.chmod(0o700)
        os.environ[variable] = str(path)

    def rpc(self, account=None, limits=None, error=False, hang=False):
        methods = self.root / "methods.jsonl"
        self.binary("import sys,json,time\n"
                    "account=" + repr(account) + "\nlimits=" + repr(limits) + "\n"
                    "for line in sys.stdin:\n"
                    " r=json.loads(line)\n"
                    " with open(" + repr(str(methods)) + ", 'a') as f:f.write(r['method']+'\\n')\n"
                    " if 'id' not in r:continue\n"
                    " if " + repr(hang) + " and r['method']=='account/read':time.sleep(10)\n"
                    " result={} if r['method']=='initialize' else {'account':account} if r['method']=='account/read' else limits\n"
                    " response={'id':r['id'],'result':result}\n"
                    " if " + repr(error) + " and r['method']=='account/rateLimits/read':response={'id':r['id'],'error':{'message':'PRIVATE-FAILURE'}}\n"
                    " print(json.dumps({'method':'unrelated/notification','params':{}}),flush=True)\n"
                    " print(json.dumps(response),flush=True)\n", "AGENT_ETA_CODEX_BIN")
        return methods

    def test_rpc_reads_auth_and_usage_without_threads_and_only_keeps_allowlisted_fields(self):
        methods = self.rpc({"type": "chatgpt", "email": "test@example.org", "token": "PRIVATE-MARKER"}, {
            "rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": 30, "windowDurationMins": 300, "resetsAt": 2000}},
                                   "premium": {"primary": {"usedPercent": 90, "windowDurationMins": 60, "resetsAt": 2000}}}})
        result = providers.codex_read()
        self.assertEqual(result["auth_state"], "authenticated")
        self.assertEqual(result["windows"], [{"used": 30, "minutes": 300, "resets_at": 2000}])
        self.assertNotIn("PRIVATE-MARKER", json.dumps(result))
        self.assertNotIn("test@example.org", json.dumps(result))
        self.assertEqual(methods.read_text().splitlines(), ["initialize", "initialized", "account/read", "account/rateLimits/read"])

    def test_logged_out_does_not_request_usage_and_non_chatgpt_auth_is_not_logged_out(self):
        methods = self.rpc()
        self.assertEqual(providers.codex_read()["auth_state"], "logged_out")
        self.assertNotIn("account/rateLimits/read", methods.read_text())
        self.rpc({"type": "apiKey"})
        result = providers.codex_read()
        self.assertEqual(result["auth_state"], "authenticated")
        self.assertIsNone(result["windows"])

    def test_usage_error_retains_confirmed_auth_and_does_not_expose_native_errors(self):
        self.rpc({"type": "chatgpt"}, error=True)
        result = providers.codex_read()
        self.assertEqual(result["auth_state"], "authenticated")
        self.assertIsNone(result["windows"])
        self.assertNotIn("PRIVATE-FAILURE", result["error"])

    def test_rpc_timeout_is_bounded_and_closes_its_own_process(self):
        self.rpc({"type": "chatgpt"}, hang=True)
        start = time.monotonic()
        with self.assertRaises(providers.AccountError):
            providers.codex_read(timeout=0.2)
        self.assertLess(time.monotonic() - start, 2)

    def test_claude_status_accepts_explicit_logout_even_with_nonzero_exit(self):
        self.binary("import json\nprint(json.dumps({'loggedIn':False}))\nraise SystemExit(1)\n", "CLAUDE_BIN")
        self.assertEqual(providers.claude_read(self.store.find("claude:default"))["auth_state"], "logged_out")

    def test_claude_status_failure_is_unknown_not_assumed_logged_out(self):
        self.binary("print('PRIVATE-MARKER')\nraise SystemExit(1)\n", "CLAUDE_BIN")
        with self.assertRaises(providers.AccountError) as caught:
            providers.claude_read(self.store.find("claude:default"))
        self.assertNotIn("PRIVATE-MARKER", str(caught.exception))

    def test_claude_status_reports_a_mismatched_registered_identity(self):
        self.registered()
        self.binary("import json\nprint(json.dumps({'loggedIn':True,'email':'other@example.org'}))\n", "AGENT_ETA_CLAUDE_ACCOUNT_BIN")
        self.assertEqual(providers.claude_read(self.store.find("claude:work"))["auth_state"], "mismatch")


if __name__ == "__main__":
    unittest.main()
