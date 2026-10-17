"""PythonOS hosted desktop entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QDateTime, QPoint, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMdiArea,
    QMdiSubWindow,
    QMessageBox,
    QPushButton,
    QMenu,
    QToolButton,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from pythonos import __codename__, __pretty_name__, __version__
from .platform import HostPlatform
from .terminal import TerminalWidget


STYLE = """
QMainWindow, QWidget#desktopRoot { background: #0d1321; color: #e7edf7; }
QWidget#panel { background: #121c2f; border-bottom: 1px solid #263650; }
QWidget#taskbar { background: #121c2f; border-top: 1px solid #263650; }
QPushButton#startButton { background: #1b5362; border-color: #65e6e0; font-weight: 700; padding: 8px 15px; }
QPushButton#startButton:hover { background: #257487; }
QPushButton#desktopButton { padding: 8px 11px; }
QPushButton#taskButton { padding: 7px 12px; min-width: 130px; max-width: 220px; text-align: left; }
QPushButton#taskButton:checked { background: #2a486a; border-color: #65e6e0; }
QLabel#tray { color: #8fa5bf; padding: 0 5px; }
QLabel#brand { color: #65e6e0; font-size: 18px; font-weight: 700; }
QLabel#version { color: #8191aa; font-size: 11px; }
QPushButton, QToolButton { background: #1c2a43; border: 1px solid #314566; border-radius: 7px; color: #e7edf7; padding: 7px 13px; }
QPushButton:hover, QToolButton:hover { background: #28405f; border-color: #65e6e0; }
QPushButton:pressed, QToolButton:pressed { background: #356078; }
QLabel#clock { color: #a8b8ce; font-size: 12px; }
QMdiArea { background: #0d1321; border: 0; }
QMdiSubWindow { background: #162238; border: 1px solid #314566; }
QGroupBox { border: 1px solid #314566; border-radius: 8px; margin-top: 10px; padding: 14px; color: #65e6e0; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QListWidget, QPlainTextEdit { background: #0a101c; border: 1px solid #283b59; border-radius: 6px; color: #e7edf7; }
QLineEdit { background: #0a101c; border: 1px solid #36547a; border-radius: 6px; color: #e7edf7; padding: 7px; }
QLabel#hero { color: #ffffff; font-size: 27px; font-weight: 700; }
QLabel#muted { color: #91a0b5; }
QLabel#accent { color: #65e6e0; font-weight: 700; }
QStatusBar { background: #101a2c; color: #8191aa; }
"""


class WelcomeWidget(QWidget):
    def __init__(self, platform: HostPlatform, open_app):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 25, 30, 25)
        hero = QLabel("Welcome to PythonOS")
        hero.setObjectName("hero")
        layout.addWidget(hero)
        subtitle = QLabel(
            "A modular desktop environment written in Python.\n"
            "You are running the hosted version; the native Alpine version uses the same framework."
        )
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)
        layout.addSpacing(18)

        cards = QGridLayout()
        cards.setHorizontalSpacing(14)
        cards.setVerticalSpacing(14)
        entries = [
            ("▣  Terminal", "Run PythonOS commands and Python code", "terminal"),
            ("▤  Files", "Explore your private PythonOS files", "files"),
            ("⚙  Settings", "Configure the desktop", "settings"),
            ("▦  Host Applications", "Launch applications installed by the host OS", "hostapps"),
            ("ⓘ  About", "Learn how the modular system works", "about"),
        ]
        for index, (title, description, name) in enumerate(entries):
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)
            label = QLabel(description)
            label.setObjectName("muted")
            box_layout.addWidget(label)
            button = QPushButton("Open")
            button.clicked.connect(lambda checked=False, n=name: open_app(n))
            box_layout.addWidget(button)
            cards.addWidget(box, index // 2, index % 2)
        layout.addLayout(cards)
        layout.addStretch()
        footer = QLabel(f"{platform.display_name()}  ·  Python {platform.python}  ·  PythonOS {__version__}")
        footer.setObjectName("muted")
        layout.addWidget(footer)


class FilesWidget(QWidget):
    def __init__(self, platform: HostPlatform):
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel("~/.pythonos/files")
        label.setObjectName("accent")
        layout.addWidget(label)
        self.list = QListWidget()
        layout.addWidget(self.list)
        buttons = QWidget()
        button_layout = QGridLayout(buttons)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        create = QPushButton("Create welcome file")
        create.clicked.connect(self.create_welcome)
        button_layout.addWidget(refresh, 0, 0)
        button_layout.addWidget(create, 0, 1)
        layout.addWidget(buttons)
        self.platform = platform
        self.refresh()

    def refresh(self):
        self.list.clear()
        try:
            entries = self.platform.list_files()
        except OSError as exc:
            self.list.addItem(str(exc))
            return
        if not entries:
            self.list.addItem("(empty — create your first PythonOS file)")
        for path in entries:
            prefix = "📁 " if path.is_dir() else "📄 "
            item = QListWidgetItem(prefix + path.name)
            item.setToolTip(str(path))
            self.list.addItem(item)

    def create_welcome(self):
        path = self.platform.paths.files / "welcome.py"
        path.write_text("# A file in the hosted PythonOS filesystem\nprint('Hello from PythonOS')\n", encoding="utf-8")
        self.refresh()


class HostAppsWidget(QWidget):
    """Browse and launch applications registered by the host operating system."""

    def __init__(self, platform: HostPlatform):
        super().__init__()
        self.platform = platform
        layout = QVBoxLayout(self)
        title = QLabel("Host Applications")
        title.setObjectName("hero")
        layout.addWidget(title)
        description = QLabel(
            "These applications belong to the host OS. PythonOS discovers them\n"
            "without copying or reimplementing them, then launches them directly."
        )
        description.setObjectName("muted")
        layout.addWidget(description)
        self.list = QListWidget()
        self.list.setToolTip("Double-click an application to launch it")
        self.list.itemDoubleClicked.connect(self.launch_selected)
        layout.addWidget(self.list)
        controls = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        controls.addStretch()
        self.status = QLabel("Double-click an application to launch it.")
        self.status.setObjectName("muted")
        controls.addWidget(self.status)
        layout.addLayout(controls)
        self.refresh()

    def refresh(self):
        self.list.clear()
        try:
            apps = self.platform.list_host_apps()
        except OSError as exc:
            self.status.setText(str(exc))
            return
        if not apps:
            self.list.addItem("No host applications found.")
            self.status.setText("No applications discovered.")
            return
        for app in apps:
            item = QListWidgetItem(f"{app.name}   ·   {app.kind}")
            item.setData(Qt.ItemDataRole.UserRole, app)
            item.setToolTip(app.target)
            self.list.addItem(item)
        self.status.setText(f"{len(apps)} host applications discovered.")

    def launch_selected(self, item: QListWidgetItem):
        app = item.data(Qt.ItemDataRole.UserRole)
        if app is None:
            return
        try:
            self.platform.launch_host_app(app)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Could not launch {app.name}: {exc}")
        else:
            self.status.setText(f"Launched {app.name}.")


class SettingsWidget(QWidget):
    def __init__(self, window: "DesktopWindow"):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Desktop settings")
        title.setObjectName("hero")
        layout.addWidget(title)
        group = QGroupBox("Session")
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(QLabel("Hosted mode keeps its files in ~/.pythonos."))
        group_layout.addWidget(QLabel("The native image will use Alpine + OpenRC and a Linux platform backend."))
        fullscreen = QPushButton("Toggle fullscreen")
        fullscreen.clicked.connect(window.toggle_fullscreen)
        group_layout.addWidget(fullscreen)
        layout.addWidget(group)
        layout.addStretch()


class AboutWidget(QWidget):
    def __init__(self, platform: HostPlatform):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel(__pretty_name__)
        title.setObjectName("hero")
        layout.addWidget(title)
        text = QLabel(
            "PythonOS is a desktop environment and a Linux distribution.\n\n"
            "Hosted mode runs on an existing operating system, so development\n"
            "does not require a virtual machine or a second computer. Native\n"
            "mode will boot Alpine Linux with OpenRC and reuse this Python UI.\n\n"
            f"Host: {platform.display_name()}\n"
            f"Python: {platform.python}"
        )
        text.setWordWrap(True)
        text.setObjectName("muted")
        layout.addWidget(text)
        layout.addStretch()


class DesktopWindow(QMainWindow):
    """The PythonOS desktop shell.

    The taskbar is deliberately part of the Python UI rather than a host-OS
    integration. It owns the launcher, window buttons, desktop toggle and
    status tray, so the same shell can be reused by native mode later.
    """

    def __init__(self, platform: HostPlatform | None = None):
        super().__init__()
        self.platform = platform or HostPlatform()
        self.setWindowTitle(f"PythonOS {__version__} · hosted desktop")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.setObjectName("desktopRoot")
        self.setStyleSheet(STYLE)
        self.windows: dict[str, QMdiSubWindow] = {}
        self.task_buttons: dict[str, QPushButton] = {}
        self._desktop_hidden = False
        self._build_ui()
        self._clock = QTimer(self)
        self._clock.timeout.connect(self.update_clock)
        self._clock.start(1000)
        self.update_clock()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("desktopRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # A slim top identity bar. The actual desktop taskbar is at the
        # bottom, like a conventional desktop environment.
        panel = QWidget()
        panel.setObjectName("panel")
        panel_layout = QHBoxLayout(panel)
        panel_layout.setContentsMargins(14, 8, 14, 8)
        panel_layout.setSpacing(9)
        brand = QLabel("PythonOS")
        brand.setObjectName("brand")
        panel_layout.addWidget(brand)
        version = QLabel(f"{__version__} · {__codename__}")
        version.setObjectName("version")
        panel_layout.addWidget(version)
        panel_layout.addStretch()
        mode = QLabel("HOSTED DESKTOP")
        mode.setObjectName("version")
        panel_layout.addWidget(mode)
        layout.addWidget(panel)

        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        self.mdi.setBackground(QColor("#0d1321"))
        self.mdi.subWindowActivated.connect(self._active_window_changed)
        layout.addWidget(self.mdi, 1)

        # Bottom taskbar: launcher, desktop toggle, live app buttons, tray and clock.
        taskbar = QWidget()
        taskbar.setObjectName("taskbar")
        taskbar_layout = QHBoxLayout(taskbar)
        taskbar_layout.setContentsMargins(10, 7, 10, 7)
        taskbar_layout.setSpacing(7)

        self.start_button = QPushButton("◈  PythonOS")
        self.start_button.setObjectName("startButton")
        self.start_button.clicked.connect(self.show_launcher)
        taskbar_layout.addWidget(self.start_button)

        desktop_button = QPushButton("Desktop")
        desktop_button.setObjectName("desktopButton")
        desktop_button.setToolTip("Show or restore desktop windows")
        desktop_button.clicked.connect(self.show_desktop)
        taskbar_layout.addWidget(desktop_button)

        self.window_button_host = QWidget()
        self.window_buttons_layout = QHBoxLayout(self.window_button_host)
        self.window_buttons_layout.setContentsMargins(4, 0, 0, 0)
        self.window_buttons_layout.setSpacing(5)
        taskbar_layout.addWidget(self.window_button_host, 1)

        host_label = QLabel("● HOST")
        host_label.setObjectName("tray")
        online_label = QLabel("⌁ ONLINE")
        online_label.setObjectName("tray")
        taskbar_layout.addWidget(host_label)
        taskbar_layout.addWidget(online_label)
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        taskbar_layout.addWidget(self.clock)
        layout.addWidget(taskbar)

        self.setCentralWidget(root)
        self.open_app("welcome")

    def update_clock(self):
        self.clock.setText(QDateTime.currentDateTime().toString("ddd  dd MMM  HH:mm"))

    def show_launcher(self):
        menu = QMenu(self)
        menu.setStyleSheet(STYLE)
        menu.addAction("Open Welcome", lambda: self.open_app("welcome"))
        menu.addSeparator()
        for name, title in (("terminal", "Terminal"), ("files", "Files"),
                            ("hostapps", "Host Applications"),
                            ("settings", "Settings"), ("about", "About")):
            menu.addAction(title, lambda n=name: self.open_app(n))
        menu.addSeparator()
        menu.addAction("Toggle fullscreen", self.toggle_fullscreen)
        menu.addAction("Exit PythonOS", self.close)
        point = self.start_button.mapToGlobal(QPoint(0, -menu.sizeHint().height()))
        menu.exec(point)

    def show_desktop(self):
        windows = list(self.windows.values())
        if not windows:
            self.open_app("welcome")
            return
        if self._desktop_hidden:
            for window in windows:
                window.showNormal()
            self._desktop_hidden = False
        else:
            for window in windows:
                window.showMinimized()
            self._desktop_hidden = True

    def _add_task_button(self, name: str, window: QMdiSubWindow):
        button = QPushButton(window.windowTitle())
        button.setObjectName("taskButton")
        button.setCheckable(True)
        button.setToolTip(f"Switch to {window.windowTitle()}")
        button.clicked.connect(lambda checked=False, n=name: self.activate_app(n))
        self.window_buttons_layout.addWidget(button)
        self.task_buttons[name] = button

    def _remove_task_button(self, name: str):
        button = self.task_buttons.pop(name, None)
        if button is not None:
            self.window_buttons_layout.removeWidget(button)
            button.deleteLater()

    def _active_window_changed(self, window):
        active = self.mdi.activeSubWindow()
        for name, button in self.task_buttons.items():
            button.setChecked(self.windows.get(name) is active)

    def activate_app(self, name: str):
        window = self.windows.get(name)
        if window is None:
            self.open_app(name)
            return
        if self.mdi.activeSubWindow() is window and not window.isMinimized():
            window.showMinimized()
            return
        window.showNormal()
        window.raise_()
        self.mdi.setActiveSubWindow(window)
        self._desktop_hidden = False

    def open_app(self, name: str):
        if name in self.windows:
            self.activate_app(name)
            return
        if name == "welcome":
            widget = WelcomeWidget(self.platform, self.open_app)
            title = "Welcome"
        elif name == "terminal":
            widget = TerminalWidget(self.platform, self.open_app)
            title = "PythonOS Terminal"
        elif name == "files":
            widget = FilesWidget(self.platform)
            title = "Files"
        elif name == "hostapps":
            widget = HostAppsWidget(self.platform)
            title = "Host Applications"
        elif name == "settings":
            widget = SettingsWidget(self)
            title = "Settings"
        elif name == "about":
            widget = AboutWidget(self.platform)
            title = "About PythonOS"
        else:
            QMessageBox.warning(self, "Unknown application", name)
            return
        sub = self.mdi.addSubWindow(widget)
        sub.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sub.setWindowTitle(title)
        sub.resize(600, 430)
        sub.destroyed.connect(lambda _obj=None, n=name: self._window_destroyed(n))
        self.windows[name] = sub
        self._add_task_button(name, sub)
        sub.show()
        if name == "welcome":
            sub.resize(760, 500)
            sub.move(70, 55)
        else:
            sub.move(110 + len(self.windows) * 20, 70 + len(self.windows) * 15)
        self.mdi.setActiveSubWindow(sub)

    def _window_destroyed(self, name: str):
        self.windows.pop(name, None)
        self._remove_task_button(name)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()


def _app_palette(app: QApplication) -> None:
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0d1321"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e7edf7"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#0a101c"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e7edf7"))
    app.setPalette(palette)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start the hosted PythonOS desktop")
    parser.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    parser.add_argument("--smoke-test", action="store_true", help="create the desktop and exit")
    parser.add_argument("--version", action="version", version=f"PythonOS {__version__} ({__codename__})")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("PythonOS")
    app.setApplicationVersion(__version__)
    _app_palette(app)
    window = DesktopWindow()
    if args.fullscreen:
        window.showFullScreen()
    else:
        window.show()
    if args.smoke_test:
        QTimer.singleShot(150, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
