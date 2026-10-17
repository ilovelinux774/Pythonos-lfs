"""Smoke test for the portable hosted desktop.

The test is skipped when the optional GUI dependency has not been installed.
CI installs requirements.txt, so the real cross-platform entry point is tested
there with Qt's offscreen backend.
"""

import os
import subprocess
import sys
import unittest


class HostedDesktopTests(unittest.TestCase):
    def test_entrypoint_creates_desktop(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("install requirements.txt for the hosted GUI")
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.run(
            [sys.executable, "-m", "pythonos.desktop.main", "--smoke-test"],
            capture_output=True, text=True, timeout=20, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
