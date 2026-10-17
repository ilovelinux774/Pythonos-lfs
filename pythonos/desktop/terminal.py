"""A small PythonOS terminal for hosted mode.

It is intentionally a Python command dispatcher rather than a wrapper around
bash/cmd.exe. That keeps the same command vocabulary on Linux, Windows and
macOS and gives native mode a compatible terminal later.
"""

from __future__ import annotations

import ast
import datetime
import shlex
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from .platform import HostPlatform


class TerminalEngine:
    def __init__(self, platform: HostPlatform, opener: Callable[[str], None] | None = None):
        self.platform = platform
        self.opener = opener
        self.commands = {
            "apps": self._apps,
            "clear": self._clear,
            "date": self._date,
            "echo": self._echo,
            "help": self._help,
            "ls": self._ls,
            "pwd": self._pwd,
            "py": self._py,
            "python": self._py,
            "sysinfo": self._sysinfo,
            "whoami": self._whoami,
        }
        self.last_status = 0

    def execute(self, line: str) -> tuple[str, bool]:
        try:
            args = shlex.split(line)
        except ValueError as exc:
            self.last_status = 2
            return f"parse error: {exc}", False
        if not args:
            return "", False
        command, rest = args[0], args[1:]
        if command in ("exit", "quit"):
            return "", True
        fn = self.commands.get(command)
        if fn is None:
            self.last_status = 127
            return f"{command}: command not found — try help", False
        try:
            output = fn(rest)
            self.last_status = 0
            return output, False
        except Exception as exc:  # noqa: BLE001
            self.last_status = 1
            return f"{command}: {exc}", False

    def _help(self, _args: list[str]) -> str:
        return ("PythonOS hosted terminal\n\n"
                "  apps                 list desktop applications\n"
                "  date                 show the host date and time\n"
                "  echo TEXT            print text\n"
                "  ls [PATH]            list PythonOS files\n"
                "  pwd                  show the virtual working directory\n"
                "  py CODE              evaluate Python code\n"
                "  sysinfo              show platform information\n"
                "  clear                clear the terminal\n"
                "  exit                 close the terminal window\n\n"
                "Files live in ~/.pythonos/files in hosted mode.")

    def _apps(self, _args: list[str]) -> str:
        return "Terminal\nFiles\nSettings\nAbout"

    def _date(self, _args: list[str]) -> str:
        return datetime.datetime.now().astimezone().strftime("%a %d %b %Y %H:%M:%S %Z")

    def _echo(self, args: list[str]) -> str:
        return " ".join(args)

    def _ls(self, args: list[str]) -> str:
        entries = self.platform.list_files(args[0] if args else ".")
        return "\n".join(("[DIR] " if p.is_dir() else "      ") + p.name for p in entries) or "(empty)"

    def _pwd(self, _args: list[str]) -> str:
        relative = self.platform.cwd.relative_to(self.platform.paths.files)
        return "~" if str(relative) == "." else "~/" + str(relative)

    def _py(self, args: list[str]) -> str:
        if not args:
            return "usage: py CODE"
        source = " ".join(args)
        allowed = {"__builtins__": {"abs": abs, "len": len, "max": max,
                                    "min": min, "round": round, "sorted": sorted,
                                    "sum": sum}}
        try:
            tree = ast.parse(source, mode="eval")
            value = eval(compile(tree, "<pythonos-terminal>", "eval"), allowed, {})
            return "" if value is None else repr(value)
        except SyntaxError:
            tree = ast.parse(source, mode="exec")
            exec(compile(tree, "<pythonos-terminal>", "exec"), allowed, {})
            return ""

    def _sysinfo(self, _args: list[str]) -> str:
        return "\n".join(f"{key}: {value}" for key, value in self.platform.info().items())

    def _whoami(self, _args: list[str]) -> str:
        return "pythonos-user"

    def _clear(self, _args: list[str]) -> str:
        return "\x1b[2J\x1b[H"


class TerminalWidget(QWidget):
    def __init__(self, platform: HostPlatform, opener: Callable[[str], None] | None = None):
        super().__init__()
        self.engine = TerminalEngine(platform, opener)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("DejaVu Sans Mono", 10))
        self.output.setObjectName("terminalOutput")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type help to see PythonOS commands")
        self.input.setFont(QFont("DejaVu Sans Mono", 10))
        self.input.returnPressed.connect(self.run_line)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.output)
        layout.addWidget(self.input)
        self.history: list[str] = []
        self.history_index = 0
        self.input.installEventFilter(self)
        self.write("PythonOS terminal · hosted mode\nType help for commands.\n")
        self.prompt()

    def prompt(self) -> None:
        self.write("\npythonos:~$ ", newline=False)

    def write(self, text: str, newline: bool = True) -> None:
        if newline:
            self.output.appendPlainText(text)
        else:
            cursor = self.output.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.output.setTextCursor(cursor)

    def run_line(self) -> None:
        line = self.input.text().strip()
        self.input.clear()
        if line:
            self.history.append(line)
            self.history_index = len(self.history)
        self.write(line)
        output, should_close = self.engine.execute(line)
        if output == "\x1b[2J\x1b[H":
            self.output.clear()
        elif output:
            self.write(output)
        if should_close:
            window = self.window()
            if window is not None:
                window.close()
            return
        self.prompt()
        self.output.ensureCursorVisible()

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is self.input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Up and self.history:
                self.history_index = max(0, self.history_index - 1)
                self.input.setText(self.history[self.history_index])
                return True
            if event.key() == Qt.Key.Key_Down and self.history:
                self.history_index = min(len(self.history), self.history_index + 1)
                self.input.setText(self.history[self.history_index] if self.history_index < len(self.history) else "")
                return True
        return super().eventFilter(watched, event)
