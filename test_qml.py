#!/usr/bin/env python3
"""Runs the widget's QML tests in test_qml/ through Qt Quick Test, offscreen.

Run with:  python3 -m unittest discover -s . -v
It needs qmltestrunner of Qt 6 and the Plasma 6 QML modules, which the `qml` job of CI installs. Elsewhere it
is skipped, since /usr/bin/qmltestrunner is often the Qt 5 qtchooser wrapper. AGENT_ETA_QMLTESTRUNNER names
the binary instead.
"""

import os
import pathlib
import shutil
import subprocess
import unittest

_HERE = pathlib.Path(__file__).resolve().parent


def runner():
    override = os.environ.get("AGENT_ETA_QMLTESTRUNNER")
    for path in [override] if override else ["/usr/lib/qt6/bin/qmltestrunner", shutil.which("qmltestrunner6")]:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


@unittest.skipUnless(runner(), "qmltestrunner of Qt 6 is not installed")
class Qml(unittest.TestCase):
    def test_widget_qml(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run([runner(), "-import", str(_HERE / "test_qml" / "stubs"), "-input",
                                 str(_HERE / "test_qml")], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 failed", result.stdout)
        self.assertIn("SessionRow::test_a_click_jumps_to_the_session", result.stdout)
        self.assertIn("WindowJumper::test_konsole_tab_titles_pick_the_window", result.stdout)


if __name__ == "__main__":
    unittest.main()
