#!/usr/bin/env python3
"""Tests for `agent-eta tab`, against a fake qdbus that serves a Konsole from a JSON fixture.

Run with:  python3 -m unittest discover -s . -v
"""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

_SRC = pathlib.Path(__file__).with_name("agent-eta")

# One Konsole process, 900, with two windows, the way a handoff leaves it after a tab was dragged out:
# window 1 shows its second tab, window 3 holds the third tab alone.
KONSOLE = {
    "services": [":1.140", "org.kde.KWin", "org.kde.konsole-900"],
    "konsole": {
        "org.kde.konsole-900": {
            "windows": {"/Windows/1": {"sessions": ["1", "2"], "current": "2"},
                        "/Windows/3": {"sessions": ["3"], "current": "3"}},
            "sessions": {"1": {"pid": 101, "title": "sec"},
                         "2": {"pid": 102, "title": "other tab"},
                         "3": {"pid": 103, "title": "Handoff 3d"}},
        },
    },
}

# The fake answers the way qdbus6 prints: services, then object paths, then one value per line.
FAKE = """
import json, os, sys
data = json.load(open(os.environ["FAKE_KONSOLE"]))
with open(os.environ["FAKE_CALLS"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if not args:
    print("\\n".join(" " + name for name in data["services"]))
    sys.exit(0)
konsole = data["konsole"].get(args[0])
if konsole is None:
    sys.exit(1)
if len(args) == 1:
    paths = ["/", "/Sessions", "/Windows", "/konsole/MainWindow_1"]
    paths += ["/Sessions/" + s for s in konsole["sessions"]] + list(konsole["windows"])
    print("\\n".join(paths))
    sys.exit(0)
path, method, rest = args[1], args[2], args[3:]
if path in konsole["windows"]:
    window = konsole["windows"][path]
    if method == "sessionList":
        print("\\n".join(window["sessions"]))
    elif method == "currentSession":
        print(window["current"])
    elif method == "setCurrentSession" and rest[0] in window["sessions"]:
        pass
    else:
        sys.exit(1)
    sys.exit(0)
session = konsole["sessions"].get(path.rsplit("/", 1)[-1]) if path.startswith("/Sessions/") else None
if session is None:
    sys.exit(1)
if method == "processId":
    print(session["pid"])
elif method == "title" and rest == ["1"]:
    print(session["title"])
else:
    sys.exit(1)
"""


class Tab(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-eta-konsole-")
        self.addCleanup(self.tmp.cleanup)
        root = pathlib.Path(self.tmp.name)
        self.fixture = root / "konsole.json"
        self.fixture.write_text(json.dumps(KONSOLE))
        self.calls = root / "calls.log"
        self.qdbus = root / "qdbus"
        self.qdbus.write_text("#!" + sys.executable + "\n" + FAKE)
        self.qdbus.chmod(0o700)
        self.env = dict(os.environ, AGENT_ETA_DIR=str(root / "state"), AGENT_ETA_QDBUS_BIN=str(self.qdbus),
                        FAKE_KONSOLE=str(self.fixture), FAKE_CALLS=str(self.calls), PYTHONDONTWRITEBYTECODE="1")

    def tab(self, *pids):
        return subprocess.run([sys.executable, str(_SRC), "tab", *map(str, pids)], capture_output=True, text=True,
                              env=self.env, timeout=30)

    def switches(self):
        log = self.calls.read_text() if self.calls.exists() else ""
        return [line for line in log.splitlines() if "setCurrentSession" in line]

    def test_the_tab_running_a_lineage_pid_becomes_current_in_its_own_window(self):
        result = self.tab(101, 900)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"window": "/Windows/1", "titles": ["other tab", "sec"]}, json.loads(result.stdout))
        self.assertEqual(["org.kde.konsole-900 /Windows/1 setCurrentSession 1"], self.switches())

    def test_a_second_window_of_the_same_process_is_told_apart(self):
        result = self.tab(103, 900)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"window": "/Windows/3", "titles": ["Handoff 3d", "Handoff 3d"]}, json.loads(result.stdout))
        self.assertEqual(["org.kde.konsole-900 /Windows/3 setCurrentSession 3"], self.switches())

    def test_the_tab_process_may_sit_anywhere_in_the_lineage(self):
        result = self.tab(4711, 102, 900)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("/Windows/1", json.loads(result.stdout)["window"])

    def test_a_lineage_without_konsole_switches_nothing(self):
        result = self.tab(101, 777)
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual([], self.switches())

    def test_a_konsole_without_the_tab_switches_nothing(self):
        result = self.tab(999, 900)
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual([], self.switches())

    def test_a_missing_or_failing_qdbus_falls_back(self):
        self.env["AGENT_ETA_QDBUS_BIN"] = str(pathlib.Path(self.tmp.name) / "absent")
        self.assertEqual(1, self.tab(101, 900).returncode)
        self.env["AGENT_ETA_QDBUS_BIN"] = str(self.qdbus)
        self.fixture.write_text(json.dumps(dict(KONSOLE, konsole={})))
        result = self.tab(101, 900)
        self.assertEqual(1, result.returncode)
        self.assertEqual("", result.stdout)


if __name__ == "__main__":
    unittest.main()
