"""Opt-in compositor integration tests, always on disposable buses and displays.

AGENT_ETA_KWIN_TESTS=1 python3 -m unittest -v test_workspace_kwin
The harness never targets the user's compositor, terminals or configuration.
"""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import agent_eta_workspace as workspace


def until(function, timeout=10):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = function()
            if last:
                return last
        except workspace.WorkspaceError:
            pass
        time.sleep(0.1)
    raise AssertionError("Disposable compositor did not reach the expected state: %r" % last)


def worker(platform):
    """Called only by this module's isolated parent. All spawned processes are owned fixtures."""
    root = Path(os.environ["XDG_RUNTIME_DIR"])
    assert root.name.startswith("eta-kwin-") and root.stat().st_mode & 0o777 == 0o700
    assert os.environ.get("DBUS_SESSION_BUS_ADDRESS") and os.environ.get("AGENT_ETA_KWIN_WORKER") == "1"
    if platform == "x11":
        assert os.environ.get("XAUTHORITY", "").startswith("/tmp/xvfb-run.")
        command = ["kwin_x11", "--no-kactivities"]
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    else:
        os.environ.pop("DISPLAY", None)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        command = ["kwin_wayland", "--virtual", "--no-lockscreen", "--no-global-shortcuts",
                   "--socket", "workspace-test", "--width", "1280", "--height", "800"]
    processes = []
    log = (root / "compositor.log").open("w+")
    try:
        processes.append(subprocess.Popen(command, stdout=log, stderr=log))
        backend = workspace.Backend()
        until(lambda: backend.snapshot())
        app_env = dict(os.environ, QT_QPA_PLATFORM="xcb" if platform == "x11" else "wayland")
        if platform == "wayland":
            app_env["WAYLAND_DISPLAY"] = "workspace-test"
        processes.append(subprocess.Popen(["konsole", "--separate", "--nofork", "--hide-menubar",
                                           "--hide-tabbar", "-e", "/bin/sleep", "120"],
                                          env=app_env, stdout=log, stderr=log))
        before = until(lambda: (value if (value := backend.snapshot())["windows"] else None))
        # Wait for the fixture application's initial profile and surface commit.
        time.sleep(0.5)
        before = backend.snapshot()
        source = deepcopy(before)
        source["host"] = "fixture-other-host"
        source["desktops"].append({"id": "source-id", "name": "TEST-731"})
        source["windows"] = [source["windows"][0]]
        source["windows"][0].update(desktops=["TEST-731"], rect=[0.25, 0.2, 0.5, 0.6])
        preview = workspace.apply_snapshot(source, backend=backend)
        assert preview["creates"] and not preview["applied"]
        assert backend.snapshot()["desktops"] == before["desktops"]
        result = workspace.apply_snapshot(source, apply=True, backend=backend)
        assert not result["skipped"], result
        assert not result["result"]["skipped"], result
        assert not result["verification"], result
        after = backend.snapshot()
        assert after["current"] == before["current"], "Background apply changed the current desktop"
        assert after["desktops"][:len(before["desktops"])] == before["desktops"]
        again = workspace.apply_snapshot(source, apply=True, backend=backend)
        assert not again["creates"] and not again["verification"], again
        # The caption recheck happens in the compositor, immediately before a write.
        target = backend.snapshot()
        plan = workspace.reconcile(source, target)
        backend.raw_windows[plan["windows"][0]["id"]]["identity"][-1] = "changed"
        try:
            backend.apply(plan)
        except workspace.WorkspaceError:
            pass
        else:
            raise AssertionError("Changed window identity was accepted")
        print(json.dumps({"platform": platform, "desktop_ids_preserved": True,
                          "geometry_verified": True, "idempotent": True, "focus_preserved": True}))
    except Exception:
        log.flush()
        log.seek(0)
        print(log.read()[-1500:], file=sys.stderr)
        raise
    finally:
        for process in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.close()


@unittest.skipUnless(os.environ.get("AGENT_ETA_KWIN_TESTS") == "1", "opt-in isolated KWin tests")
class CompositorTests(unittest.TestCase):
    def run_platform(self, platform):
        for binary in ("kwin_" + platform, "konsole", "dbus-run-session", "xvfb-run"):
            self.assertIsNotNone(shutil.which(binary), binary + " is required for the requested integration tests")
        with tempfile.TemporaryDirectory(prefix="eta-kwin-") as folder:
            root = Path(folder)
            root.chmod(0o700)
            environment = dict(os.environ, HOME=folder, XDG_RUNTIME_DIR=folder, XDG_CONFIG_HOME=folder + "/config",
                               XDG_DATA_HOME=folder + "/data", XDG_CACHE_HOME=folder + "/cache",
                               AGENT_ETA_DIR=folder + "/eta", AGENT_ETA_KWIN_WORKER="1",
                               LIBGL_ALWAYS_SOFTWARE="1", QT_LOGGING_RULES="*.debug=false")
            if platform == "wayland":
                environment["KWIN_COMPOSE"] = "Q"
            for name in ("DBUS_SESSION_BUS_ADDRESS", "WAYLAND_DISPLAY", "SESSION_MANAGER", "DISPLAY", "XAUTHORITY"):
                environment.pop(name, None)
            # No service activation can escape this fixture into desktop portals.
            config = root / "bus.conf"
            config.write_text('<busconfig><type>session</type><listen>unix:tmpdir=' + folder + '</listen>'
                              '<auth>EXTERNAL</auth><policy context="default"><allow own="*"/>'
                              '<allow send_destination="*"/><allow receive_sender="*"/></policy></busconfig>')
            command = ["dbus-run-session", "--config-file=" + str(config), "--", sys.executable,
                       str(Path(__file__).resolve()), "--worker", platform]
            if platform == "x11":
                command = ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", *command]
            result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr[-5000:])
            self.assertIn('"geometry_verified": true', result.stdout)

    def test_x11(self):
        self.run_platform("x11")

    def test_wayland(self):
        self.run_platform("wayland")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
    else:
        unittest.main()
