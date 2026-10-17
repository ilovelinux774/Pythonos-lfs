"""pyedit — a small full-screen text editor for PythonOS.

Arrow keys move, Enter splits lines, Backspace joins them, Tab indents.
Ctrl-S saves, Ctrl-Q quits, Ctrl-L redraws, Ctrl-K cuts a line.
No dependencies beyond the Python standard library — as is tradition here.
"""

import os
import sys

from pythonos.tui import ansi

TABSTOP = 4


class Editor:
    def __init__(self, path):
        self.path = path
        self.lines = [""]
        self.row = 0
        self.col = 0
        self.top = 0
        self.left = 0
        self.dirty = False
        self.message = ""
        self.running = True
        self.encoding = "utf-8"
        if path and os.path.exists(path) and not os.path.isdir(path):
            try:
                with open(path, "r", encoding=self.encoding, errors="replace") as fh:
                    text = fh.read()
                self.lines = text.split("\n")
                if self.lines and self.lines[-1] == "":
                    self.lines.pop()
                if not self.lines:
                    self.lines = [""]
                self.message = f"opened {path} ({len(self.lines)} lines)"
            except OSError as exc:
                self.message = f"cannot open: {exc.strerror}"
        elif path:
            self.message = f"new file: {path}"

    # -- geometry ----------------------------------------------------------
    def _x_of(self, line, col):
        x = 0
        for ch in line[:col]:
            if ch == "\t":
                x += TABSTOP - (x % TABSTOP)
            else:
                x += 1
        return x

    def _line_display(self, line, left, width):
        out = []
        x = 0
        for ch in line:
            w = TABSTOP - (x % TABSTOP) if ch == "\t" else 1
            start = x
            x += w
            if x <= left:
                continue
            if start < left:  # partial character (tab) at the left edge
                out.append(" " * (min(x, left + width) - left))
            else:
                out.append(ch if ch != "\t" else " " * w)
            if x >= left + width:
                break
        text = "".join(out)
        return text[:width]

    # -- editing -----------------------------------------------------------
    def insert(self, text):
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col] + text + line[self.col:]
        self.col += len(text)
        self.dirty = True

    def newline(self):
        line = self.lines[self.row]
        self.lines[self.row] = line[:self.col]
        self.lines.insert(self.row + 1, line[self.col:])
        self.row += 1
        self.col = 0
        self.dirty = True

    def backspace(self):
        if self.col > 0:
            line = self.lines[self.row]
            self.lines[self.row] = line[:self.col - 1] + line[self.col:]
            self.col -= 1
            self.dirty = True
        elif self.row > 0:
            prev = self.lines[self.row - 1]
            self.col = len(prev)
            self.lines[self.row - 1] = prev + self.lines[self.row]
            del self.lines[self.row]
            self.row -= 1
            self.dirty = True

    def delete(self):
        line = self.lines[self.row]
        if self.col < len(line):
            self.lines[self.row] = line[:self.col] + line[self.col + 1:]
            self.dirty = True
        elif self.row + 1 < len(self.lines):
            self.lines[self.row] = line + self.lines[self.row + 1]
            del self.lines[self.row + 1]
            self.dirty = True

    def kill_line(self):
        if len(self.lines) == 1:
            self.lines[0] = ""
        else:
            del self.lines[self.row]
            if self.row >= len(self.lines):
                self.row = len(self.lines) - 1
        self.col = min(self.col, len(self.lines[self.row]))
        self.dirty = True

    # -- io ----------------------------------------------------------------
    def save(self):
        target = self.path
        if not target:
            self.message = "no filename: run pyedit FILE"
            return False
        try:
            with open(target, "w", encoding=self.encoding) as fh:
                fh.write("\n".join(self.lines) + "\n")
        except OSError as exc:
            self.message = f"save failed: {exc.strerror}"
            return False
        self.dirty = False
        total = sum(len(line) + 1 for line in self.lines)
        self.message = f"wrote {self.path} ({len(self.lines)} lines, {total} bytes)"
        return True

    # -- rendering ---------------------------------------------------------
    def render(self):
        cols, rows = ansi.terminal_size()
        text_rows = max(rows - 3, 3)

        if self.row < self.top:
            self.top = self.row
        elif self.row >= self.top + text_rows:
            self.top = self.row - text_rows + 1

        cursor_x = self._x_of(self.lines[self.row], self.col)
        view_width = cols - 1
        if cursor_x < self.left:
            self.left = cursor_x
        elif cursor_x >= self.left + view_width:
            self.left = cursor_x - view_width + 1

        buf = [f"{ansi.ESC}[H"]
        for offset in range(text_rows):
            index = self.top + offset
            if index < len(self.lines):
                text = self._line_display(self.lines[index], self.left, view_width)
                buf.append(text + "\n")
            else:
                buf.append(ansi.colorize("~", ansi.BLUE) + "\n")

        name = self.path or "[No Name]"
        flag = " [+] " if self.dirty else "     "
        position = f" Ln {self.row + 1}, Col {self.col + 1} "
        pad = max(cols - len(name) - len(flag) - len(position) - 2, 0)
        status = f" {name}{flag}{' ' * pad}{position}"
        buf.append(ansi.colorize(status[:cols], ansi.REVERSE) + "\n")

        hint = self.message or "Ctrl-S save   Ctrl-Q quit   Ctrl-K cut line   arrows move"
        buf.append(ansi.dim(hint[:cols]) + f"{ansi.ESC}[K")

        cursor_row = self.row - self.top + 1
        cursor_col = cursor_x - self.left + 1
        buf.append(f"{ansi.ESC}[{cursor_row};{cursor_col}H")
        sys.stdout.write("".join(buf))
        sys.stdout.flush()

    # -- keys --------------------------------------------------------------
    def read_key(self):
        data = os.read(sys.stdin.fileno(), 1)
        if not data:
            return "EOF"
        if data == b"\x1b":
            seq = b""
            import select
            while select.select([sys.stdin], [], [], 0.02)[0]:
                seq += os.read(sys.stdin.fileno(), 1)
            return self._decode_escape(seq)
        if data in (b"\r", b"\n"):
            return "ENTER"
        if data in (b"\x7f", b"\x08"):
            return "BACKSPACE"
        if data == b"\t":
            return "TAB"
        if data == b"\x13":
            return "SAVE"
        if data == b"\x11":
            return "QUIT"
        if data == b"\x0c":
            return "REDRAW"
        if data == b"\x01":
            return "HOME"
        if data == b"\x05":
            return "END"
        if data == b"\x0b":
            return "KILL_LINE"
        # UTF-8 continuation bytes
        if data[0] >= 0xC0:
            need = 1
            if data[0] >= 0xE0:
                need = 2
            if data[0] >= 0xF0:
                need = 3
            rest = os.read(sys.stdin.fileno(), need)
            data += rest
        try:
            ch = data.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
        if ch and ch.isprintable():
            return ("CHAR", ch)
        return None

    @staticmethod
    def _decode_escape(seq):
        if not seq:
            return None
        if seq in (b"[A",):
            return "UP"
        if seq in (b"[B",):
            return "DOWN"
        if seq in (b"[C",):
            return "RIGHT"
        if seq in (b"[D",):
            return "LEFT"
        if seq in (b"[H", b"[1~", b"OH", b"[7~"):
            return "HOME"
        if seq in (b"[F", b"[4~", b"OF", b"[8~"):
            return "END"
        if seq in (b"[3~",):
            return "DELETE"
        if seq in (b"[5~",):
            return "PGUP"
        if seq in (b"[6~",):
            return "PGDN"
        return None

    def clamp_col(self):
        self.col = min(self.col, len(self.lines[self.row]))

    def handle(self, key):
        if key is None:
            return
        if key == "EOF":
            self.running = False
            return
        if key == "QUIT":
            self.quit_dialog()
            return
        if key == "SAVE":
            self.save()
            return
        if key == "REDRAW":
            return
        if key == "ENTER":
            self.newline()
        elif key == "BACKSPACE":
            self.backspace()
        elif key == "DELETE":
            self.delete()
        elif key == "TAB":
            self.insert(" " * TABSTOP)
        elif key == "KILL_LINE":
            self.kill_line()
        elif key == "LEFT":
            if self.col > 0:
                self.col -= 1
            elif self.row > 0:
                self.row -= 1
                self.col = len(self.lines[self.row])
        elif key == "RIGHT":
            if self.col < len(self.lines[self.row]):
                self.col += 1
            elif self.row + 1 < len(self.lines):
                self.row += 1
                self.col = 0
        elif key == "UP":
            if self.row > 0:
                self.row -= 1
                self.clamp_col()
        elif key == "DOWN":
            if self.row + 1 < len(self.lines):
                self.row += 1
                self.clamp_col()
        elif key == "HOME":
            self.col = 0
        elif key == "END":
            self.col = len(self.lines[self.row])
        elif key == "PGUP":
            _cols, rows = ansi.terminal_size()
            self.row = max(0, self.row - max(rows - 4, 1))
            self.clamp_col()
        elif key == "PGDN":
            _cols, rows = ansi.terminal_size()
            self.row = min(len(self.lines) - 1, self.row + max(rows - 4, 1))
            self.clamp_col()
        elif isinstance(key, tuple) and key[0] == "CHAR":
            self.insert(key[1])

    def quit_dialog(self):
        if not self.dirty:
            self.running = False
            return
        self.message = "Save changes? (y)es (n)o (c)ancel"
        self.render()
        while True:
            key = self.read_key()
            if isinstance(key, tuple) and key[0] == "CHAR":
                choice = key[1].lower()
                if choice == "y":
                    if self.save():
                        self.running = False
                    else:
                        self.render()
                    return
                if choice == "n":
                    self.running = False
                    return
                if choice == "c":
                    self.message = "cancelled"
                    return
            elif key == "QUIT":
                continue


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("pyedit: needs an interactive terminal", file=sys.stderr)
        return 1
    path = argv[0] if argv else None
    if path and os.path.isdir(path):
        print(f"pyedit: {path}: is a directory", file=sys.stderr)
        return 1

    import termios
    import tty

    editor = Editor(path)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    ansi.enter_alt_screen()
    ansi.hide_cursor()
    try:
        tty.setraw(fd)
        while editor.running:
            editor.render()
            key = editor.read_key()
            editor.handle(key)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        ansi.show_cursor()
        ansi.exit_alt_screen()
    return 0


if __name__ == "__main__":
    sys.exit(main())
