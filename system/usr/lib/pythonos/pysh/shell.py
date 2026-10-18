"""pysh — the PythonOS shell.

A small POSIX-flavoured shell written from scratch in Python. It supports
real pipelines, redirection, quoting, environment expansion, globbing,
command chaining and — being Python — a ``py`` builtin that executes
arbitrary Python inside your session.
"""

import glob as globmod
import os
import shutil
import signal
import sys

from pythonos import __pretty_name__, __version__
from pythonos.tui import ansi

try:  # line editing / history when stdin is a terminal
    import readline  # noqa: F401
    HAVE_READLINE = True
except ImportError:  # pragma: no cover - minimal builds
    HAVE_READLINE = False

OPERATORS = (
    "2>&1", "2>>", "2>", "&&", "||", ">>", "|", ";", ">", "<", "&",
)

REDIRECT_OPS = {"2>&1", "2>>", "2>", ">>", ">", "<"}


# ---------------------------------------------------------------------------
# Tokenising
# ---------------------------------------------------------------------------
def tokenize(line):
    """Split a command line into ('word', text) / ('op', op) tokens.

    Quotes are preserved inside words so that later expansion can tell an
    unquoted ``$VAR`` from a literal one.
    """
    tokens = []
    word = []
    quote = None
    i = 0
    length = len(line)

    def flush():
        if word:
            tokens.append(("word", "".join(word)))
            word.clear()

    while i < length:
        ch = line[i]

        if quote:
            word.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue

        if ch in ("'", '"'):
            quote = ch
            word.append(ch)
            i += 1
            continue

        if ch == "\\" and i + 1 < length:
            word.append(line[i:i + 2])
            i += 2
            continue

        if ch in " \t":
            flush()
            i += 1
            continue

        op = None
        for candidate in OPERATORS:
            if line.startswith(candidate, i):
                # Don't treat a digit inside a word as a redirect (e.g. a2>).
                if candidate in ("2>&1", "2>>", "2>") and word:
                    continue
                op = candidate
                break
        if op:
            flush()
            tokens.append(("op", op))
            i += len(op)
            continue

        word.append(ch)
        i += 1

    flush()
    return tokens


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------
def _lookup_var(name, env):
    if name == "?":
        return env.get("__status__", "0")
    if name == "$":
        return str(os.getpid())
    if name == "0":
        return "pysh"
    return env.get(name, "")


def expand_word(raw, env, do_glob=True):
    """Expand quotes, ``~`` and ``$VARS`` in one raw word.

    Returns a list of strings: globbing can fan one word out into many.
    """
    out = []
    i = 0
    n = len(raw)
    quote = None
    had_glob = False
    first = True

    while i < n:
        ch = raw[i]

        if quote == "'":
            if ch == "'":
                quote = None
            else:
                out.append(ch)
            i += 1
            continue

        if ch == "'" and quote is None:
            quote = "'"
            i += 1
            continue

        if ch == '"' and quote is None:
            quote = '"'
            i += 1
            continue

        if ch == '"' and quote == '"':
            quote = None
            i += 1
            continue

        if quote is None and ch == "\\" and i + 1 < n:
            # Native pysh is POSIX-flavoured, but its host-side tests also
            # run on Windows. There a backslash is normally a path
            # separator, not an escape character; preserving it lets paths
            # such as C:\\Users\\Name\\Temp\\*.txt glob correctly.
            if os.name == "nt":
                out.append(ch)
                i += 1
                continue
            out.append(raw[i + 1])
            i += 2
            continue

        if ch == "$":
            if i + 1 < n and raw[i + 1] == "{":
                end = raw.find("}", i + 2)
                if end != -1:
                    out.append(_lookup_var(raw[i + 2:end], env))
                    i = end + 1
                    continue
            j = i + 1
            if j < n and (raw[j].isalpha() or raw[j] == "_"):
                while j < n and (raw[j].isalnum() or raw[j] == "_"):
                    j += 1
                out.append(_lookup_var(raw[i + 1:j], env))
                i = j
                continue
            if j < n and raw[j] in "?$0":
                out.append(_lookup_var(raw[j], env))
                i = j + 1
                continue
            out.append("$")
            i += 1
            continue

        if quote is None and ch == "~" and first and (i + 1 == n or raw[i + 1] == "/"):
            out.append(env.get("HOME", "/root"))
            i += 1
            first = False
            continue

        if quote is None and ch in "*?[":
            had_glob = True
        out.append(ch)
        first = False
        i += 1

    text = "".join(out)

    if do_glob and had_glob and text and "\x00" not in text:
        matches = sorted(globmod.glob(text))
        if matches:
            return matches

    return [text]


# ---------------------------------------------------------------------------
# Parsing a full command line
# ---------------------------------------------------------------------------
class Segment:
    __slots__ = ("argv", "stdin", "stdout", "stderr_file", "append",
                 "stderr_to_stdout")

    def __init__(self):
        self.argv = []
        self.stdin = None
        self.stdout = None
        self.stderr_file = None
        self.append = False
        self.stderr_to_stdout = False


def parse(tokens):
    """Turn tokens into a list of (connector, [Segment, ...]) jobs.

    connector is one of '', ';', '&&', '||' and describes how the job is
    joined to the previous one.
    """
    jobs = []
    segments = [Segment()]
    connector = ""
    i = 0

    while i < len(tokens):
        kind, value = tokens[i]
        if kind == "word":
            segments[-1].argv.append(value)
        elif value in ("|",):
            segments.append(Segment())
        elif value in ("&&", "||", ";", "&"):
            jobs.append((connector, segments))
            segments = [Segment()]
            connector = value
        elif value == "2>&1":
            segments[-1].stderr_to_stdout = True
        elif value in REDIRECT_OPS:
            target = tokens[i + 1][1] if i + 1 < len(tokens) else ""
            i += 1
            seg = segments[-1]
            if value == "<":
                seg.stdin = target
            elif value in (">", "2>"):
                if value == "2>":
                    seg.stderr_file = target  # type: ignore[attr-defined]
                else:
                    seg.stdout = target
                seg.append = False
            elif value in (">>", "2>>"):
                if value == "2>>":
                    seg.stderr_file = target  # type: ignore[attr-defined]
                else:
                    seg.stdout = target
                seg.append = True
        i += 1

    jobs.append((connector, segments))
    return jobs


# ---------------------------------------------------------------------------
# The shell
# ---------------------------------------------------------------------------
class Shell:
    def __init__(self, interactive=None):
        self.env = dict(os.environ)
        self.env.setdefault("HOME", "/root")
        self.env.setdefault("USER", "root")
        self.env.setdefault("LOGNAME", "root")
        self.env.setdefault("TERM", "linux")
        self.env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
        self.env.setdefault("LANG", "C.UTF-8")
        try:
            self.env["PWD"] = os.getcwd()
        except OSError:
            os.chdir("/")
            self.env["PWD"] = "/"
        self.prev_dir = self.env["HOME"]
        self.last_status = 0
        self.running = True
        self.exit_code = 0
        self.aliases = {
            "ll": "ls -l",
            "la": "ls -a",
            "l": "ls -la",
            "..": "cd ..",
            "q": "exit",
        }
        self.history_file = os.path.join(self.env["HOME"], ".pysh_history")
        if interactive is None:
            interactive = sys.stdin.isatty()
        self.interactive = interactive
        self._load_history()
        if HAVE_READLINE:
            try:
                readline.parse_and_bind("set editing-mode emacs")
            except Exception:
                pass

    # -- history -----------------------------------------------------------
    def _load_history(self):
        if not HAVE_READLINE:
            return
        try:
            readline.read_history_file(self.history_file)
            readline.set_history_length(500)
        except (OSError, ValueError):
            pass

    def _save_history(self):
        if not HAVE_READLINE:
            return
        try:
            readline.write_history_file(self.history_file)
        except OSError:
            pass

    # -- prompt ------------------------------------------------------------
    def cwd_display(self):
        try:
            cwd = os.getcwd()
        except OSError:
            os.chdir("/")
            cwd = "/"
        home = self.env.get("HOME", "/root")
        if home and cwd.startswith(home):
            cwd = "~" + cwd[len(home):]
        return cwd or "/"

    def prompt(self):
        user = self.env.get("USER", "root")
        host = "pythonos"
        sigil = "#" if user == "root" else "$"
        use_color = ansi.supports_color()
        return (
            ansi.colorize(f"{user}@{host}", ansi.BOLD, ansi.GREEN, enabled=use_color)
            + ansi.colorize(":", ansi.DIM, enabled=use_color)
            + ansi.colorize(self.cwd_display(), ansi.BOLD, ansi.BLUE, enabled=use_color)
            + ansi.colorize(f"{sigil} ", ansi.BOLD, ansi.RED if user == "root" else ansi.GREEN,
                            enabled=use_color)
        )

    # -- execution ---------------------------------------------------------
    def execute(self, line):
        """Run one line. Returns the exit status."""
        line = line.strip()
        if not line or line.startswith("#"):
            return 0

        try:
            tokens = self._expand_aliases(tokenize(line))
        except Exception as exc:  # noqa: BLE001
            print(ansi.red(f"pysh: parse error: {exc}"), file=sys.stderr)
            return 2

        if not tokens:
            return 0

        status = self.last_status
        for connector, segments in parse(tokens):
            if connector == "&&" and status != 0:
                continue
            if connector == "||" and status == 0:
                continue
            self.env["__status__"] = str(status)
            status = self.run_pipeline(segments)
        self.last_status = status
        return status

    def _expand_aliases(self, tokens):
        """Rewrite the first word of every simple command through aliases."""
        out = []
        queue = list(tokens)
        at_cmd_start = True
        expansions = 0
        while queue:
            kind, value = queue.pop(0)
            if (at_cmd_start and kind == "word" and value in self.aliases
                    and expansions < 25):
                queue = tokenize(self.aliases[value]) + queue
                expansions += 1
                continue
            out.append((kind, value))
            if kind == "op" and value in (";", "&&", "||", "|"):
                at_cmd_start = True
            else:
                at_cmd_start = False
        return out

    def _builtin(self, name):
        from . import builtins

        return builtins.COMMANDS.get(name)

    def run_pipeline(self, segments):
        segments = [seg for seg in segments if seg.argv or seg.stdin]
        if not segments:
            return 0

        if len(segments) == 1:
            return self.run_segment(segments[0])

        pids = []
        prev_read = None
        statuses = []
        for index, seg in enumerate(segments):
            read_end, write_end = os.pipe()
            pid = os.fork()
            if pid == 0:  # child
                try:
                    if prev_read is not None:
                        os.dup2(prev_read, 0)
                    if index < len(segments) - 1:
                        os.dup2(write_end, 1)
                    for fd in (read_end, write_end, prev_read):
                        if fd is not None and fd > 2:
                            try:
                                os.close(fd)
                            except OSError:
                                pass
                    self._apply_redirects(seg)
                    code = self._exec_in_child(seg)
                except Exception as exc:  # noqa: BLE001
                    print(f"pysh: {exc}", file=sys.stderr)
                    code = 1
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                except Exception:  # noqa: BLE001
                    pass
                os._exit(code)
            pids.append(pid)
            if prev_read is not None:
                os.close(prev_read)
            os.close(write_end)
            prev_read = read_end
        if prev_read is not None:
            os.close(prev_read)

        for pid in pids:
            _, status = os.waitpid(pid, 0)
            statuses.append(os.waitstatus_to_exitcode(status))
        return statuses[-1] if statuses else 0

    def _exec_in_child(self, seg):
        """Run a segment in a forked child (pipeline member)."""
        argv = []
        for raw in seg.argv:
            argv.extend(expand_word(raw, self.env))
        if not argv:
            return 0
        builtin = self._builtin(argv[0])
        if builtin:
            return builtin(self, argv[1:])
        return self._exec_external(argv)

    def _apply_redirects(self, seg):
        try:
            if seg.stdin:
                path = expand_word(seg.stdin, self.env)[0]
                fd = os.open(path, os.O_RDONLY)
                os.dup2(fd, 0)
                os.close(fd)
            if seg.stdout:
                path = expand_word(seg.stdout, self.env)[0]
                flags = os.O_WRONLY | os.O_CREAT
                flags |= os.O_APPEND if seg.append else os.O_TRUNC
                fd = os.open(path, flags, 0o644)
                os.dup2(fd, 1)
                os.close(fd)
            if getattr(seg, "stderr_file", None):
                path = expand_word(seg.stderr_file, self.env)[0]
                flags = os.O_WRONLY | os.O_CREAT
                flags |= os.O_APPEND if seg.append else os.O_TRUNC
                fd = os.open(path, flags, 0o644)
                os.dup2(fd, 2)
                os.close(fd)
            if seg.stderr_to_stdout:
                os.dup2(1, 2)
        except OSError as exc:
            print(f"pysh: redirect: {exc}", file=sys.stderr)
            raise

    def run_segment(self, seg):
        """Run a single segment: builtin in-process, external forked."""
        if not seg.argv and seg.stdin is None:
            return 0

        argv = []
        for raw in seg.argv:
            argv.extend(expand_word(raw, self.env))
        if not argv:
            return 0

        builtin = self._builtin(argv[0])
        needs_redirect = bool(seg.stdout or getattr(seg, "stderr_file", None)
                              or seg.stdin or seg.stderr_to_stdout)

        if builtin is None:
            status = self._exec_external(argv, redirect=seg if needs_redirect else None)
            return status

        saved = []
        try:
            if needs_redirect:
                for tgt in (0, 1, 2):
                    try:
                        saved.append((tgt, os.dup(tgt)))
                    except OSError:
                        saved.append((tgt, None))
                try:
                    self._apply_redirects(seg)
                except OSError:
                    return 1
            status = builtin(self, argv[1:])
            sys.stdout.flush()
            sys.stderr.flush()
        except BrokenPipeError:
            status = 0
        finally:
            for tgt, dup in saved:
                if dup is None:
                    continue
                try:
                    os.dup2(dup, tgt)
                    os.close(dup)
                except OSError:
                    pass
        return status

    def _exec_external(self, argv, redirect=None):
        name = argv[0]
        if "/" in name:
            path = name
        else:
            path = shutil.which(name, path=self.env.get("PATH", ""))

        if not path:
            print(ansi.red(f"pysh: {name}: command not found"),
                  file=sys.stderr)
            hint = self._did_you_mean(name)
            if hint:
                print(ansi.dim(f"       did you mean '{hint}'?  (try 'help')"),
                      file=sys.stderr)
            return 127

        pid = os.fork()
        if pid == 0:
            try:
                if redirect is not None:
                    self._apply_redirects(redirect)
                os.execvpe(path, argv, self.env)
            except FileNotFoundError:
                print(f"pysh: {name}: no such file", file=sys.stderr)
                os._exit(127)
            except PermissionError:
                print(f"pysh: {name}: permission denied", file=sys.stderr)
                os._exit(126)
            except Exception as exc:  # noqa: BLE001
                print(f"pysh: {name}: {exc}", file=sys.stderr)
                os._exit(1)

        try:
            _, status = os.waitpid(pid, 0)
        except KeyboardInterrupt:
            try:
                os.kill(pid, signal.SIGINT)
            except OSError:
                pass
            _, status = os.waitpid(pid, 0)
            print()
            return 130
        return os.waitstatus_to_exitcode(status)

    def _did_you_mean(self, name):
        from . import builtins

        candidates = list(builtins.COMMANDS)
        best = None
        best_score = 3
        for cand in candidates:
            score = _edit_distance(name, cand)
            if score < best_score:
                best, best_score = cand, score
        return best

    # -- REPL --------------------------------------------------------------
    def banner(self):
        from pythonos.tui.logo import LOGO_SMALL

        use_color = ansi.supports_color()
        print()
        for line in LOGO_SMALL.strip("\n").splitlines():
            print("  " + ansi.colorize(line, ansi.BOLD, ansi.CYAN, enabled=use_color))
        print()
        print("  " + ansi.bold(f"Welcome to {__pretty_name__}"))
        print(f"  {ansi.dim('The shell and userland are Python; Alpine/BusyBox and OpenRC own PID 1. Python ' + sys.version.split()[0] + '.')}")
        print()
        print(f"  {ansi.green('help')}      list commands        "
              f"{ansi.green('pyfetch')}   system info")
        print(f"  {ansi.green('pytop')}     process monitor       "
              f"{ansi.green('pyedit')}    text editor")
        print(f"  {ansi.green('pkg')}       package manager       "
              f"{ansi.green('py')}        run Python code")
        print()

    def repl(self):
        if self.interactive:
            self.banner()
        while self.running:
            try:
                line = input(self.prompt())
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print("^C")
                continue
            if not line.strip():
                continue
            try:
                self.execute(line)
            except KeyboardInterrupt:
                print("^C")
                self.last_status = 130
            except SystemExit as exc:
                self.exit_code = int(exc.code or 0) if isinstance(exc.code, int) else 0
                break
            except Exception as exc:  # noqa: BLE001
                print(ansi.red(f"pysh: unexpected error: {exc}"), file=sys.stderr)
                import traceback
                traceback.print_exc()
                self.last_status = 1
        self._save_history()
        if self.interactive:
            print(ansi.dim("logout"))


def _edit_distance(a, b):
    if abs(len(a) - len(b)) > 3:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    shell = Shell()

    if "-c" in argv:
        idx = argv.index("-c")
        if idx + 1 < len(argv):
            return shell.execute(argv[idx + 1])
        print("pysh: -c requires an argument", file=sys.stderr)
        return 2

    if "--login" in argv or "-l" in argv:
        if sys.stdin.isatty():
            shell.interactive = True

    try:
        shell.repl()
    finally:
        shell._save_history()
    return shell.exit_code


if __name__ == "__main__":
    sys.exit(main())
