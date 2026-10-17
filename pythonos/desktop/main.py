"""PythonOS hosted desktop entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QDateTime, QTimer, Qt
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
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pythonos import __codename__, __pretty_name__, __version__
from .platform import HostPlatform
from .terminal import TerminalWidget


STYLE = """
QMainWindow, QWidget#desktopRoot { background: #0d1321; color: #e7edf7; }
QWidget#panel { background: #121c2f; border-bottom: 1px solid #263650; }
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
    def __init__(self, platform: HostPlatform | None = None):
        super().__init__()
        self.platform = platform or HostPlatform()
        self.setWindowTitle(f"PythonOS {__version__} · hosted desktop")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.setObjectName("desktopRoot")
        self.setStyleSheet(STYLE)
        self.windows: dict[str, QMdiSubWindow] = {}
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
        panel = QWidget()
        panel.setObjectName("panel")
        panel_layout = QGridLayout(panel)
        panel_layout.setContentsMargins(14, 8, 14, 8)
        brand = QLabel("PythonOS")
        brand.setObjectName("brand")
        panel_layout.addWidget(brand, 0, 0)
        version = QLabel(f"{__version__} · {__codename__}")
        version.setObjectName("version")
        panel_layout.addWidget(version, 0, 1)
        launcher = QToolButton()
        launcher.setText("Applications ▾")
        launcher.clicked.connect(self.show_launcher)
        panel_layout.addWidget(launcher, 0, 2)
        panel_layout.setColumnStretch(3, 1)
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        panel_layout.addWidget(self.clock, 0, 4)
        layout.addWidget(panel)

        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        self.mdi.setBackground(QColor("#0d1321"))
        layout.addWidget(self.mdi)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Hosted mode · private files in ~/.pythonos/files")
        self.open_app("welcome")

    def update_clock(self):
        self.clock.setText(QDateTime.currentDateTime().toString("ddd  dd MMM  HH:mm"))

    def show_launcher(self):
        menu = self.menuBar().addMenu("Applications")
        menu.aboutToHide.connect(menu.deleteLater)
        for name, title in (("terminal", "Terminal"), ("files", "Files"),
                            ("settings", "Settings"), ("about", "About")):
            action = QAction(title, menu)
            action.triggered.connect(lambda checked=False, n=name: self.open_app(n))
            menu.addAction(action)
        menu.popup(self.mapToGlobal(self.rect().topLeft() + self.rect().topLeft()))

    def open_app(self, name: str):
        if name in self.windows:
            window = self.windows[name]
            window.show()
            window.raise_()
            self.mdi.setActiveSubWindow(window)
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
        sub.setWindowTitle(title)
        sub.resize(600, 430)
        sub.destroyed.connect(lambda _obj=None, n=name: self.windows.pop(n, None))
        self.windows[name] = sub
        sub.show()
        if name == "welcome":
            sub.resize(760, 500)
            sub.move(70, 55)
        else:
            sub.move(110 + len(self.windows) * 20, 70 + len(self.windows) * 15)

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
