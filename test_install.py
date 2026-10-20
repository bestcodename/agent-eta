#!/usr/bin/env python3
"""Tests for install.sh and the widget's logic.mjs.

Run with: python3 -m unittest discover -s . -v
"""

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

_HERE = pathlib.Path(__file__).resolve().parent
_ID = "com.github.bestcodename.agenteta"


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.env = dict(os.environ, HOME=str(self.tmp), BIN_DIR=str(self.tmp / "bin"),
                        PLASMOID_DIR=str(self.tmp / "plasmoids"), AGENT_ETA_TRAY="0")
        self.package = self.tmp / "plasmoids" / _ID

    def install(self):
        return subprocess.run(["bash", str(_HERE / "install.sh")], env=self.env, capture_output=True, text=True)

    def test_links_the_tool_and_copies_the_widget_and_a_second_run_changes_nothing(self):
        for _ in range(2):
            result = self.install()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(os.readlink(self.tmp / "bin" / "agent-eta"), str(_HERE / "agent-eta"))
            self.assertTrue(self.package.is_dir())
            self.assertFalse(self.package.is_symlink())
            self.assertEqual((self.package / "metadata.json").read_text(),
                             (_HERE / "plasmoid" / "metadata.json").read_text())
            self.assertTrue((self.package / "contents" / "ui" / "main.qml").is_file())
        self.assertEqual(sorted(p.name for p in self.package.parent.iterdir()), [_ID])

    def test_a_reinstall_drops_files_the_widget_no_longer_has(self):
        self.install()
        (self.package / "contents" / "stale.qml").write_text("")
        self.assertEqual(self.install().returncode, 0)
        self.assertFalse((self.package / "contents" / "stale.qml").exists())

    def test_replaces_a_package_link_from_the_first_version(self):
        self.package.parent.mkdir(parents=True)
        self.package.symlink_to(_HERE / "plasmoid")
        self.assertEqual(self.install().returncode, 0)
        self.assertFalse(self.package.is_symlink())
        self.assertTrue((_HERE / "plasmoid" / "metadata.json").is_file())

    def test_refuses_a_foreign_directory_and_a_foreign_file(self):
        self.package.mkdir(parents=True)
        (self.package / "metadata.json").write_text('{"KPlugin": {"Id": "someone.else"}}')
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not this widget", result.stderr)
        self.assertTrue((self.package / "metadata.json").exists())

        target = self.tmp / "bin" / "agent-eta"
        target.unlink()
        target.write_text("mine")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_text(), "mine")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class Plasmoid(unittest.TestCase):
    def test_logic_module(self):
        # node:test runs the registered tests directly as well. Avoid another child
        # runner, which some sandboxed Node builds report as one file without its tests.
        result = subprocess.run(["node", str(_HERE / "test_plasmoid.mjs")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stopped and dormant ones open independently", result.stdout)


if __name__ == "__main__":
    unittest.main()
