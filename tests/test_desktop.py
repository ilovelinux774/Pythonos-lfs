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
    def _gui_env(self):
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return env

    def _require_qt(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("install requirements.txt for the hosted GUI")

    def test_entrypoint_creates_desktop(self):
        self._require_qt()
        proc = subprocess.run(
            [sys.executable, "-m", "pythonos.desktop.main", "--smoke-test"],
            capture_output=True, text=True, timeout=20, env=self._gui_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_taskbar_tracks_open_apps(self):
        self._require_qt()
        code = """
from PySide6.QtWidgets import QApplication
from pythonos.desktop.main import DesktopWindow
app = QApplication([])
window = DesktopWindow()
for name in (\"terminal\", \"files\", \"settings\", \"about\"):
    window.open_app(name)
assert set(window.task_buttons) == {\"welcome\", \"terminal\", \"files\", \"settings\", \"about\"}
window.show_desktop()
assert all(item.isMinimized() for item in window.windows.values())
window.show_desktop()
assert all(not item.isMinimized() for item in window.windows.values())
app.quit()
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=20, env=self._gui_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_native_session_uses_shared_desktop_labels(self):
        self._require_qt()
        code = """
from PySide6.QtWidgets import QApplication, QLabel
from pythonos.desktop.main import DesktopWindow
app = QApplication([])
window = DesktopWindow()
assert window.native
assert window.windowTitle().endswith(\"native desktop\")
window.open_app(\"welcome\")
labels = [label.text().lower() for label in window.windows[\"welcome\"].widget().findChildren(QLabel)]
assert any(\"native alpine linux\" in label for label in labels)
assert set(window.task_buttons) == {\"welcome\"}
app.quit()
"""
        env = self._gui_env()
        env["PYTHONOS_NATIVE"] = "1"
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=20, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_terminal_cursor_blinks(self):
        self._require_qt()
        code = """
from PySide6.QtWidgets import QApplication
from pythonos.desktop.platform import HostPlatform
from pythonos.desktop.terminal import TerminalEngine, TerminalView
app = QApplication([])
view = TerminalView(TerminalEngine(HostPlatform()))
assert view.cursorWidth() == 0
assert view._blink_timer.interval() == 530
assert view._cursor_visible
view._toggle_cursor()
assert not view._cursor_visible
view._toggle_cursor()
assert view._cursor_visible
app.quit()
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=20, env=self._gui_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_terminal_is_single_buffer_not_chat_input(self):
        self._require_qt()
        code = """
from PySide6.QtWidgets import QApplication
from pythonos.desktop.platform import HostPlatform
from pythonos.desktop.terminal import TerminalEngine, TerminalView
app = QApplication([])
view = TerminalView(TerminalEngine(HostPlatform()))
assert not hasattr(view, \"input\")
view._insert_text(\"echo hello\")
view._submit()
assert \"pythonos:~$ echo hello\\nhello\\npythonos:~$ \" in view.toPlainText()
app.quit()
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=20, env=self._gui_env(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_terminal_opens_pythonos_app(self):
        self._require_qt()
        code = """
from pythonos.desktop.platform import HostPlatform
from pythonos.desktop.terminal import TerminalEngine
opened = []
engine = TerminalEngine(HostPlatform(), opened.append)
output, should_close = engine.execute(\"open files\")
assert opened == [\"files\"]
assert output == \"Opening Files.\"
assert not should_close
assert \"terminal\" in engine.execute(\"apps\")[0]
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=20, env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
