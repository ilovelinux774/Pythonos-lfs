"""A real, line-oriented PythonOS terminal for hosted mode.

This is intentionally a terminal screen rather than a chat transcript: the
prompt, command and output share one monospaced buffer, and keyboard editing
happens at the live cursor on that buffer.
"""

from __future__ import annotations

import ast
import datetime
import shlex
from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from .platform import HostPlatform


CLEAR_SCREEN = "\x00PYTHONOS_CLEAR_SCREEN\x00"


class TerminalEngine:
    def __init__(self, platform: HostPlatform, opener: Callable[[str], None] | None = None):
        self.platform = platform
        self.opener = opener
        self.applications = {
            "welcome": "Welcome",
            "terminal": "Terminal",
            "files": "Files",
            "settings": "Settings",
            "about": "About PythonOS",
        }
        self.commands = {
            "apps": self._apps,
            "cd": self._cd,
            "clear": self._clear,
            "date": self._date,
            "echo": self._echo,
            "help": self._help,
            "ls": self._ls,
            "open": self._open_app,
            "pwd": self._pwd,
            "run": self._open_app,
            "py": self._py,
            "python": self._py,
            "sysinfo": self._sysinfo,
            "whoami": self._whoami,
        }
        self.last_status = 0

    def prompt(self) -> str:
        relative = self.platform.cwd.relative_to(self.platform.paths.files)
        location = "~" if str(relative) == "." else "~/" + str(relative)
        return f"pythonos:{location}$ "

    def execute(self, line: str) -> tuple[str, bool]:
        try:
            if self.platform.system == "Windows":
                # Keep backslashes in unquoted Windows paths. ``shlex``'s
                # POSIX mode treats them as escape characters.
                args = shlex.split(line, posix=False)
                args = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1]
                        and arg[0] in "\"'" else arg for arg in args]
            else:
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
        return ("PythonOS terminal\n\n"
                "  apps                 list desktop applications\n"
                "  cd [PATH]            change the virtual directory\n"
                "  date                 show the host date and time\n"
                "  echo TEXT            print text\n"
                "  ls [PATH]            list PythonOS files\n"
                "  open APP             open a PythonOS application window\n"
                "  pwd                  show the virtual working directory\n"
                "  py CODE              evaluate Python code\n"
                "  run APP              alias for open APP\n"
                "  sysinfo              show platform information\n"
                "  clear                clear the terminal\n"
                "  exit                 close the terminal window\n\n"
                "Files live in ~/.pythonos/files in hosted mode.")

    def _apps(self, _args: list[str]) -> str:
        return "\n".join(f"{name:<10} {title}" for name, title in self.applications.items())

    def _open_app(self, args: list[str]) -> str:
        if not args:
            raise ValueError("usage: open APP")
        requested = args[0].casefold()
        aliases = {"home": "welcome", "info": "about"}
        name = aliases.get(requested, requested)
        if name not in self.applications:
            choices = ", ".join(self.applications)
            raise ValueError(f"unknown PythonOS app '{args[0]}' (choose: {choices})")
        if self.opener is None:
            return f"Open {self.applications[name]} from the PythonOS launcher."
        self.opener(name)
        return f"Opening {self.applications[name]}."

    def _cd(self, args: list[str]) -> str:
        target = args[0] if args else "~"
        path = self.platform.virtual_path(target)
        if not path.is_dir():
            raise NotADirectoryError(target)
        self.platform.cwd = path
        return ""

    def _date(self, _args: list[str]) -> str:
        return datetime.datetime.now().astimezone().strftime("%a %d %b %Y %H:%M:%S %Z")

    def _echo(self, args: list[str]) -> str:
        return " ".join(args)

    def _ls(self, args: list[str]) -> str:
        entries = self.platform.list_files(args[0] if args else ".")
        return "\n".join(("[DIR] " if p.is_dir() else "      ") + p.name for p in entries) or "(empty)"

    def _pwd(self, _args: list[str]) -> str:
        return self.prompt().split(":", 1)[1].rsplit("$", 1)[0].strip()

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
        return CLEAR_SCREEN


class TerminalView(QPlainTextEdit):
    """Single-buffer terminal screen with a real editable prompt."""

    def __init__(self, engine: TerminalEngine):
        super().__init__()
        self.engine = engine
        self.current_line = ""
        self.line_cursor = 0
        self.prompt_position = 0
        self.history: list[str] = []
        self.history_index = 0
        self.history_draft = ""
        self._cursor_visible = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(530)
        self._blink_timer.timeout.connect(self._toggle_cursor)

        self.setObjectName("terminalOutput")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFont("DejaVu Sans Mono", 10))
        # Draw the caret ourselves so its blink is consistent across Qt
        # platforms and terminal focus changes.
        self.setCursorWidth(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._write("PythonOS terminal · hosted mode\n")
        self._write("Type help for commands. Ctrl-L clears the screen.\n\n")
        self._new_prompt()

    def _document_end(self) -> int:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor.position()

    def _write(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def _set_cursor(self, position: int) -> None:
        cursor = self.textCursor()
        cursor.setPosition(max(0, position))
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self._reset_cursor_blink()

    def _toggle_cursor(self) -> None:
        self._cursor_visible = not self._cursor_visible
        self.viewport().update()

    def _reset_cursor_blink(self) -> None:
        self._cursor_visible = True
        self._blink_timer.start()
        self.viewport().update()

    def _refresh_cursor(self) -> None:
        self._set_cursor(self.prompt_position + self.line_cursor)

    def _new_prompt(self) -> None:
        self._write(self.engine.prompt())
        self.prompt_position = self._document_end()
        self.current_line = ""
        self.line_cursor = 0
        self.history_index = len(self.history)
        self.history_draft = ""
        self._refresh_cursor()
        self.setFocus()

    def _replace_current_line(self, text: str) -> None:
        cursor = self.textCursor()
        cursor.setPosition(self.prompt_position)
        cursor.setPosition(self.prompt_position + len(self.current_line),
                           QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        cursor.insertText(text)
        self.current_line = text
        self.line_cursor = len(text)
        self._refresh_cursor()

    def _insert_text(self, text: str) -> None:
        if not text:
            return
        cursor = self.textCursor()
        cursor.setPosition(self.prompt_position + self.line_cursor)
        cursor.insertText(text)
        self.current_line = (self.current_line[:self.line_cursor] + text
                             + self.current_line[self.line_cursor:])
        self.line_cursor += len(text)
        self._refresh_cursor()

    def _backspace(self) -> None:
        if self.line_cursor == 0:
            return
        cursor = self.textCursor()
        cursor.setPosition(self.prompt_position + self.line_cursor - 1)
        cursor.setPosition(self.prompt_position + self.line_cursor,
                           QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.current_line = (self.current_line[:self.line_cursor - 1]
                             + self.current_line[self.line_cursor:])
        self.line_cursor -= 1
        self._refresh_cursor()

    def _delete(self) -> None:
        if self.line_cursor >= len(self.current_line):
            return
        cursor = self.textCursor()
        cursor.setPosition(self.prompt_position + self.line_cursor)
        cursor.setPosition(self.prompt_position + self.line_cursor + 1,
                           QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        self.current_line = (self.current_line[:self.line_cursor]
                             + self.current_line[self.line_cursor + 1:])
        self._refresh_cursor()

    def _submit(self) -> None:
        line = self.current_line
        if line:
            self.history.append(line)
        self.history_index = len(self.history)
        self.history_draft = ""
        self._set_cursor(self._document_end())
        self._write("\n")
        output, should_close = self.engine.execute(line)
        if output == CLEAR_SCREEN:
            self.clear()
        elif output:
            self._write(output)
            if not output.endswith("\n"):
                self._write("\n")
        if should_close:
            self.window().close()
            return
        self._new_prompt()

    def _history_up(self) -> None:
        if not self.history:
            return
        if self.history_index == len(self.history):
            self.history_draft = self.current_line
        self.history_index = max(0, self.history_index - 1)
        self._replace_current_line(self.history[self.history_index])

    def _history_down(self) -> None:
        if not self.history:
            return
        self.history_index = min(len(self.history), self.history_index + 1)
        if self.history_index == len(self.history):
            self._replace_current_line(self.history_draft)
        else:
            self._replace_current_line(self.history[self.history_index])

    def _interrupt(self) -> None:
        self._set_cursor(self._document_end())
        self._write("^C\n")
        self._new_prompt()

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        if not self.hasFocus() or not self._cursor_visible:
            return
        rect = self.cursorRect(self.textCursor())
        painter = QPainter(self.viewport())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#65e6e0"))
        painter.drawRect(rect.left(), rect.top(), 2, max(14, rect.height()))
        painter.end()

    def focusInEvent(self, event):  # noqa: N802
        super().focusInEvent(event)
        self._reset_cursor_blink()

    def focusOutEvent(self, event):  # noqa: N802
        super().focusOutEvent(event)
        self._cursor_visible = False
        self._blink_timer.stop()
        self.viewport().update()

    def keyPressEvent(self, event):  # noqa: N802
        key = event.key()
        modifiers = event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        if control and key == Qt.Key.Key_C:
            if self.textCursor().hasSelection():
                self.copy()
            else:
                self._interrupt()
            return
        if control and key == Qt.Key.Key_L:
            self.clear()
            self._new_prompt()
            return
        if control and key == Qt.Key.Key_A:
            self.line_cursor = 0
            self._refresh_cursor()
            return
        if control and key == Qt.Key.Key_E:
            self.line_cursor = len(self.current_line)
            self._refresh_cursor()
            return
        if control and key == Qt.Key.Key_U:
            self._replace_current_line("")
            return
        if control and key == Qt.Key.Key_W:
            before = self.current_line[:self.line_cursor].rstrip()
            new_cursor = before.rfind(" ") + 1
            self._replace_current_line(before[:new_cursor] + self.current_line[self.line_cursor:])
            self.line_cursor = new_cursor
            self._refresh_cursor()
            return
        if control and key == Qt.Key.Key_D and not self.current_line:
            self.window().close()
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
            return
        if key == Qt.Key.Key_Backspace:
            self._backspace()
            return
        if key == Qt.Key.Key_Delete:
            self._delete()
            return
        if key == Qt.Key.Key_Left:
            self.line_cursor = max(0, self.line_cursor - 1)
            self._refresh_cursor()
            return
        if key == Qt.Key.Key_Right:
            self.line_cursor = min(len(self.current_line), self.line_cursor + 1)
            self._refresh_cursor()
            return
        if key == Qt.Key.Key_Home:
            self.line_cursor = 0
            self._refresh_cursor()
            return
        if key == Qt.Key.Key_End:
            self.line_cursor = len(self.current_line)
            self._refresh_cursor()
            return
        if key == Qt.Key.Key_Up:
            self._history_up()
            return
        if key == Qt.Key.Key_Down:
            self._history_down()
            return
        if key == Qt.Key.Key_Tab:
            self._insert_text("    ")
            return

        if not (modifiers & (Qt.KeyboardModifier.ControlModifier
                             | Qt.KeyboardModifier.AltModifier
                             | Qt.KeyboardModifier.MetaModifier)):
            text = event.text()
            if text and text.isprintable():
                self._insert_text(text)
                return

        # Keep scrolling, selection and other standard read-only behavior.
        super().keyPressEvent(event)
        self._refresh_cursor()

    def mousePressEvent(self, event):  # noqa: N802
        super().mousePressEvent(event)
        # The buffer is selectable, but commands can only be edited after the
        # live prompt. A click therefore returns the insertion point to it.
        self._refresh_cursor()


class TerminalWidget(QWidget):
    def __init__(self, platform: HostPlatform, opener: Callable[[str], None] | None = None):
        super().__init__()
        self.engine = TerminalEngine(platform, opener)
        self.output = TerminalView(self.engine)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.output)
