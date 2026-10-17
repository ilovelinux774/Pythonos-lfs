"""pysh builtins — the entire classic userland, in Python.

Every entry in COMMANDS is (shell, argv_after_command) -> exit status.
External binaries are only used when no builtin matches.
"""

import os
import re
import shutil
import signal
import stat as statmod
import sys
import time

from pythonos import __pretty_name__, __version__, syscalls
from pythonos.tui import ansi

from . import fmt

COMMANDS = {}
HELP_ENTRIES = []


def command(name, category="Misc", help_text="", aliases=()):
    def register(fn):
        fn.pyos_help = help_text
        fn.pyos_category = category
        fn.pyos_aliases = aliases
        COMMANDS[name] = fn
        for alias in aliases:
            COMMANDS[alias] = fn
        HELP_ENTRIES.append((name, tuple(aliases), category, help_text))
        return fn
    return register


def _out(text=""):
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _err(text):
    sys.stderr.write(text + "\n")
    sys.stderr.flush()


def _use_color():
    return ansi.supports_color()


def _expand(shell, path):
    return os.path.expanduser(path) if path else path


# ---------------------------------------------------------------------------
# Navigation & session
# ---------------------------------------------------------------------------
@command("cd", "Navigation", "change directory", aliases=())
def cd(shell, args):
    target = args[0] if args else shell.env.get("HOME", "/root")
    if target == "-":
        target = shell.prev_dir
        print(target)
    if target == "~" or target.startswith("~/"):
        target = shell.env.get("HOME", "/root") + target[1:]
    try:
        os.chdir(target)
    except FileNotFoundError:
        _err(f"cd: {target}: no such directory")
        return 1
    except NotADirectoryError:
        _err(f"cd: {target}: not a directory")
        return 1
    except PermissionError:
        _err(f"cd: {target}: permission denied")
        return 1
    old = shell.env.get("PWD", "")
    shell.env["PWD"] = os.getcwd()
    if old and old != shell.env["PWD"]:
        shell.prev_dir = old
    return 0


@command("pwd", "Navigation", "print working directory")
def pwd(shell, args):
    _out(os.getcwd())
    return 0


@command("exit", "Navigation", "leave the shell", aliases=("logout",))
def do_exit(shell, args):
    code = 0
    if args:
        try:
            code = int(args[0]) & 0xFF
        except ValueError:
            _err(f"exit: {args[0]}: numeric argument required")
            code = 2
    shell.exit_code = code
    shell.running = False
    return code


@command("history", "Navigation", "show command history")
def history(shell, args):
    try:
        import readline
        length = readline.get_current_history_length()
        for index in range(1, length + 1):
            _out(f"  {index:>4}  {readline.get_history_item(index)}")
    except ImportError:
        _err("history: line editing is unavailable in this build")
        return 1
    return 0


@command("clear", "Navigation", "clear the screen")
def clear(shell, args):
    ansi.clear()
    return 0


@command("alias", "Navigation", "define or list aliases")
def alias(shell, args):
    if not args:
        for name in sorted(shell.aliases):
            _out(f"alias {name}='{shell.aliases[name]}'")
        return 0
    status = 0
    for item in args:
        if "=" in item:
            name, _, value = item.partition("=")
            shell.aliases[name.strip()] = value.strip().strip("'\"")
        elif item in shell.aliases:
            _out(f"alias {item}='{shell.aliases[item]}'")
        else:
            _err(f"alias: {item}: not found")
            status = 1
    return status


@command("unalias", "Navigation", "remove an alias")
def unalias(shell, args):
    status = 0
    for name in args:
        if name in shell.aliases:
            del shell.aliases[name]
        else:
            _err(f"unalias: {name}: not found")
            status = 1
    return status


@command("help", "Navigation", "list available commands")
def help_cmd(shell, args):
    if args:
        topic = args[0]
        fn = COMMANDS.get(topic)
        if not fn:
            _err(f"help: no help for '{topic}'")
            return 1
        _out(f"{ansi.bold(topic)} — {fn.pyos_help}")
        if fn.pyos_aliases:
            _out(f"aliases: {', '.join(fn.pyos_aliases)}")
        return 0

    categories = {}
    for name, aliases, category, text in HELP_ENTRIES:
        categories.setdefault(category, []).append((name, aliases, text))

    _out()
    _out("  " + ansi.bold("PythonOS commands"))
    _out("  " + ansi.dim("builtins run inside pysh; everything else is a forked process"))
    for category in ("Navigation", "Files", "Text", "System", "PythonOS", "Misc"):
        rows = categories.get(category)
        if not rows:
            continue
        _out()
        _out(f"  {ansi.cyan(category)}")
        for name, aliases, text in rows:
            label = name + (f" ({', '.join(aliases)})" if aliases else "")
            _out(f"    {label:<22} {ansi.dim(text)}")
    _out()
    _out("  " + ansi.dim("Python is a first-class citizen here: try  py import platform; print(platform.python_version())"))
    _out()
    return 0


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def _colorize_ls(name, path, use_color):
    if not use_color:
        return name
    try:
        st = os.lstat(path)
    except OSError:
        return name
    if statmod.S_ISLNK(st.st_mode):
        return ansi.colorize(name, ansi.BOLD, ansi.CYAN)
    if statmod.S_ISDIR(st.st_mode):
        return ansi.colorize(name, ansi.BOLD, ansi.BLUE)
    if st.st_mode & statmod.S_IXUSR:
        return ansi.colorize(name, ansi.BOLD, ansi.GREEN)
    return name


@command("ls", "Files", "list directory contents  (-l long, -a all, -h human)")
def ls(shell, args):
    show_all = long_fmt = human = one_per_line = False
    paths = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1 and not paths:
            for flag in arg[1:]:
                if flag == "a":
                    show_all = True
                elif flag == "l":
                    long_fmt = True
                    one_per_line = True
                elif flag == "h":
                    human = True
                elif flag == "1":
                    one_per_line = True
                else:
                    _err(f"ls: invalid option -- '{flag}'")
                    return 2
        else:
            paths.append(arg)
    if not paths:
        paths = ["."]

    status = 0
    multi = len(paths) > 1
    for path in paths:
        try:
            entries = sorted(os.listdir(path))
        except FileNotFoundError:
            _err(f"ls: {path}: no such file or directory")
            status = 1
            continue
        except NotADirectoryError:
            _show_file(path, long_fmt, human)
            continue
        except PermissionError:
            _err(f"ls: {path}: permission denied")
            status = 1
            continue

        if not show_all:
            entries = [e for e in entries if not e.startswith(".")]
        if multi:
            _out(f"{path}:")
        use_color = _use_color() and sys.stdout.isatty()
        if long_fmt:
            _ls_long(path, entries, human)
        elif one_per_line:
            for entry in entries:
                _out(_colorize_ls(entry, os.path.join(path, entry), use_color))
        else:
            _ls_columns(path, entries, use_color)
        if multi:
            _out()
    return status


def _show_file(path, long_fmt, human):
    if long_fmt:
        try:
            _out(_long_line(path, path, human))
        except OSError as exc:
            _err(f"ls: {path}: {exc.strerror}")
    else:
        _out(path)


def _long_line(parent, name, human):
    st = os.lstat(os.path.join(parent, name))
    mode = statmod.filemode(st.st_mode)
    size = fmt.human_size(st.st_size) if human else str(st.st_size)
    mtime = time.strftime("%b %d %H:%M", time.localtime(st.st_mtime))
    link = ""
    if statmod.S_ISLNK(st.st_mode):
        link = f" -> {os.readlink(os.path.join(parent, name))}"
    return f"{mode} {st.st_nlink:>3} {st.st_uid:>5} {st.st_gid:>5} {size:>8} {mtime} {name}{link}"


def _ls_long(parent, entries, human):
    if not entries:
        return
    blocks = 0
    for entry in entries:
        try:
            blocks += os.lstat(os.path.join(parent, entry)).st_blocks // 2
        except OSError:
            pass
    _out(f"total {blocks}")
    for entry in entries:
        try:
            _out(_long_line(parent, entry, human))
        except OSError:
            _out(entry)


def _ls_columns(parent, entries, use_color):
    if not entries:
        return
    decorated = [_colorize_ls(e, os.path.join(parent, e), use_color) for e in entries]
    columns, _ = ansi.terminal_size()
    width = max(ansi.width(e) for e in decorated) + 2
    per_row = max(1, columns // max(width, 1))
    for i in range(0, len(decorated), per_row):
        row = decorated[i:i + per_row]
        line = ""
        for item in row:
            pad = width - ansi.width(item)
            line += item + " " * pad
        _out(line.rstrip())


@command("cat", "Files", "concatenate files to stdout")
def cat(shell, args):
    if not args:
        try:
            data = sys.stdin.buffer.read()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        except (BrokenPipeError, KeyboardInterrupt):
            pass
        return 0
    status = 0
    for path in args:
        try:
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        except OSError as exc:
            _err(f"cat: {path}: {exc.strerror}")
            status = 1
    return status


def _read_text_stream(paths):
    """Yield (line, source, line_number) from stdin or the given files."""
    if not paths:
        for number, line in enumerate(sys.stdin, 1):
            yield line, "<stdin>", number
        return
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for number, line in enumerate(fh, 1):
                    yield line, path, number
        except OSError as exc:
            _err(f"{path}: {exc.strerror}")


@command("head", "Text", "first lines of a file or stdin  (-n N)")
def head(shell, args):
    count = 10
    paths = []
    i = 0
    while i < len(args):
        if args[i] == "-n" and i + 1 < len(args):
            count = int(args[i + 1])
            i += 2
        elif re.fullmatch(r"-\d+", args[i]):
            count = int(args[i][1:])
            i += 1
        else:
            paths.append(args[i])
            i += 1
    shown = 0
    for line, _src, _num in _read_text_stream(paths):
        if shown >= count:
            break
        sys.stdout.write(line)
        shown += 1
    return 0


@command("tail", "Text", "last lines of a file or stdin  (-n N)")
def tail(shell, args):
    count = 10
    paths = []
    i = 0
    while i < len(args):
        if args[i] == "-n" and i + 1 < len(args):
            count = int(args[i + 1])
            i += 2
        elif re.fullmatch(r"-\d+", args[i]):
            count = int(args[i][1:])
            i += 1
        else:
            paths.append(args[i])
            i += 1
    for path in (paths or [None]):
        try:
            if path is None:
                lines = sys.stdin.readlines()
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()
        except OSError as exc:
            _err(f"tail: {path}: {exc.strerror}")
            return 1
        for line in lines[-count:]:
            sys.stdout.write(line)
    return 0


@command("wc", "Text", "count lines, words and bytes")
def wc(shell, args):
    flags = set()
    paths = []
    for arg in args:
        if arg.startswith("-"):
            flags.update(arg[1:])
        else:
            paths.append(arg)
    def counts(text):
        return text.count("\n"), len(text.split()), len(text.encode())

    total = [0, 0, 0]
    rows = []
    if paths:
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
            except OSError as exc:
                _err(f"wc: {path}: {exc.strerror}")
                return 1
            c = counts(text)
            total = [a + b for a, b in zip(total, c)]
            rows.append((c, path))
        if len(paths) > 1:
            rows.append((total, "total"))
    else:
        text = sys.stdin.read()
        rows.append((counts(text), ""))

    for (lines, words, chars), name in rows:
        parts = []
        if not flags or "l" in flags:
            parts.append(f"{lines:>8}")
        if not flags or "w" in flags:
            parts.append(f"{words:>8}")
        if "c" in flags or "m" in flags:
            parts.append(f"{chars:>8}")
        if flags and not ({"l", "w", "c", "m"} & flags):
            parts = [f"{lines:>8}", f"{words:>8}", f"{chars:>8}"]
        _out(" ".join(parts) + (f" {name}" if name else ""))
    return 0


@command("grep", "Text", "search with Python regex  (-n line no, -i ignore case, -v invert, -c count)")
def grep(shell, args):
    flags = set()
    rest = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1 and not rest:
            flags.update(arg[1:])
        else:
            rest.append(arg)
    if not rest:
        _err("usage: grep [-nivc] PATTERN [FILE...]")
        return 2
    pattern, paths = rest[0], rest[1:]
    try:
        regex = re.compile(pattern, re.IGNORECASE if "i" in flags else 0)
    except re.error as exc:
        _err(f"grep: bad regex: {exc}")
        return 2

    use_color = _use_color() and sys.stdout.isatty()
    matched = 0
    prefix_files = len(paths) > 1
    for line, source, number in _read_text_stream(paths):
        line = line.rstrip("\n")
        hit = bool(regex.search(line))
        if "v" in flags:
            hit = not hit
        if not hit:
            continue
        matched += 1
        if "c" in flags:
            continue
        shown = line
        if use_color and "v" not in flags:
            shown = regex.sub(
                lambda m: ansi.colorize(m.group(0), ansi.BOLD, ansi.RED), line)
        prefix = ""
        if prefix_files:
            prefix += f"{source}:"
        if "n" in flags:
            prefix += f"{number}:"
        _out(prefix + shown)
    if "c" in flags:
        _out(str(matched))
    return 0 if matched else 1


@command("find", "Files", "find files  (find [path] -name GLOB [-type f|d])")
def find(shell, args):
    root = "."
    name_pat = None
    type_filter = None
    i = 0
    if args and not args[0].startswith("-"):
        root = args[0]
        i = 1
    while i < len(args):
        if args[i] == "-name" and i + 1 < len(args):
            name_pat = args[i + 1]
            i += 2
        elif args[i] == "-type" and i + 1 < len(args):
            type_filter = args[i + 1]
            i += 2
        else:
            _err(f"find: unknown predicate '{args[i]}' (supported: -name, -type)")
            return 2

    if not os.path.exists(root):
        _err(f"find: {root}: no such file or directory")
        return 1

    import fnmatch
    found = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(dirnames) + sorted(filenames):
            path = os.path.join(dirpath, name)
            is_dir = os.path.isdir(path)
            if type_filter and type_filter != ("d" if is_dir else "f"):
                continue
            if name_pat and not fnmatch.fnmatch(name, name_pat):
                continue
            _out(path)
            found += 1
    return 0 if found or root != "." else 0


@command("cp", "Files", "copy files  (-r recursive)")
def cp(shell, args):
    recursive = False
    rest = []
    for arg in args:
        if arg == "-r" or arg == "-R":
            recursive = True
        else:
            rest.append(arg)
    if len(rest) < 2:
        _err("usage: cp [-r] SOURCE... DEST")
        return 2
    *sources, dest = rest
    dest_is_dir = os.path.isdir(dest)
    if len(sources) > 1 and not dest_is_dir:
        _err("cp: target is not a directory")
        return 1
    status = 0
    for src in sources:
        try:
            if os.path.isdir(src):
                if not recursive:
                    _err(f"cp: -r not specified; omitting directory '{src}'")
                    status = 1
                    continue
                target = os.path.join(dest, os.path.basename(src.rstrip("/"))) if dest_is_dir else dest
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                target = os.path.join(dest, os.path.basename(src)) if dest_is_dir else dest
                shutil.copy2(src, target)
        except OSError as exc:
            _err(f"cp: {src}: {exc.strerror or exc}")
            status = 1
    return status


@command("mv", "Files", "move or rename files")
def mv(shell, args):
    if len(args) < 2:
        _err("usage: mv SOURCE... DEST")
        return 2
    *sources, dest = args
    dest_is_dir = os.path.isdir(dest)
    status = 0
    for src in sources:
        target = os.path.join(dest, os.path.basename(src)) if dest_is_dir else dest
        try:
            shutil.move(src, target)
        except OSError as exc:
            _err(f"mv: {src}: {exc.strerror or exc}")
            status = 1
    return status


@command("rm", "Files", "remove files  (-r recursive, -f force)")
def rm(shell, args):
    recursive = force = False
    paths = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1:
            recursive = recursive or "r" in arg or "R" in arg
            force = force or "f" in arg
        else:
            paths.append(arg)
    if not paths:
        _err("usage: rm [-rf] FILE...")
        return 2
    status = 0
    for path in paths:
        if path in ("/", "/*", "."):
            _err(f"rm: refusing to remove '{path}'")
            status = 1
            continue
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                if not recursive:
                    _err(f"rm: {path}: is a directory (use -r)")
                    status = 1
                    continue
                shutil.rmtree(path)
            else:
                os.remove(path)
        except FileNotFoundError:
            if not force:
                _err(f"rm: {path}: no such file")
                status = 1
        except OSError as exc:
            _err(f"rm: {path}: {exc.strerror or exc}")
            status = 1
    return status


@command("mkdir", "Files", "create directories  (-p parents)")
def mkdir(shell, args):
    parents = False
    paths = []
    for arg in args:
        if arg == "-p":
            parents = True
        else:
            paths.append(arg)
    if not paths:
        _err("usage: mkdir [-p] DIR...")
        return 2
    status = 0
    for path in paths:
        try:
            if parents:
                os.makedirs(path, exist_ok=True)
            else:
                os.mkdir(path)
        except FileExistsError:
            _err(f"mkdir: {path}: already exists")
            status = 1
        except OSError as exc:
            _err(f"mkdir: {path}: {exc.strerror or exc}")
            status = 1
    return status


@command("rmdir", "Files", "remove empty directories")
def rmdir(shell, args):
    if not args:
        _err("usage: rmdir DIR...")
        return 2
    status = 0
    for path in args:
        try:
            os.rmdir(path)
        except OSError as exc:
            _err(f"rmdir: {path}: {exc.strerror or exc}")
            status = 1
    return status


@command("touch", "Files", "create files or update timestamps")
def touch(shell, args):
    status = 0
    for path in args:
        try:
            with open(path, "a"):
                pass
            os.utime(path, None)
        except OSError as exc:
            _err(f"touch: {path}: {exc.strerror or exc}")
            status = 1
    return 0 if args else 2


@command("du", "Files", "disk usage  (-s summary, -h human)")
def du(shell, args):
    summary = human = False
    paths = []
    for arg in args:
        if arg.startswith("-"):
            summary = summary or "s" in arg
            human = human or "h" in arg
        else:
            paths.append(arg)
    paths = paths or ["."]

    def size_of(path):
        try:
            if os.path.isfile(path):
                return os.stat(path).st_size
        except OSError:
            return 0
        total = 0
        for dirpath, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.lstat(os.path.join(dirpath, name)).st_size
                except OSError:
                    pass
        return total

    status = 0
    for path in paths:
        if not os.path.exists(path):
            _err(f"du: {path}: no such file or directory")
            status = 1
            continue
        if summary:
            value = size_of(path)
            shown = fmt.human_size(value) if human else str(value // 1024)
            _out(f"{shown}\t{path}")
        else:
            for dirpath, dirs, _files in os.walk(path):
                dirs.sort()
                value = size_of(dirpath)
                shown = fmt.human_size(value) if human else str(value // 1024)
                _out(f"{shown}\t{dirpath}")
    return status


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------
def _read_proc_stat(pid):
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="ascii", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return None
    try:
        lparen = raw.index("(")
        rparen = raw.rindex(")")
    except ValueError:
        return None
    name = raw[lparen + 1:rparen]
    rest = raw[rparen + 2:].split()
    return {
        "pid": pid,
        "name": name,
        "state": rest[0],
        "ppid": int(rest[1]),
        "tty": int(rest[4]),
        "utime": int(rest[11]),
        "stime": int(rest[12]),
        "priority": int(rest[15]),
        "threads": int(rest[17]),
        "starttime": int(rest[19]),
        "vsize": int(rest[20]),
        "rss": int(rest[21]),
    }


def iter_processes():
    procs = []
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            info = _read_proc_stat(entry)
            if info:
                procs.append(info)
    procs.sort(key=lambda p: p["pid"])
    return procs


def read_meminfo():
    info = {}
    try:
        with open("/proc/meminfo", "r", encoding="ascii", errors="replace") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                fields = rest.split()
                if fields:
                    info[key.strip()] = int(fields[0])
    except OSError:
        pass
    return info


@command("ps", "System", "list processes")
def ps(shell, args):
    procs = iter_processes()
    _out(f"{'PID':>6} {'PPID':>6} {'STAT':<5} {'RSS':>8} {'TIME':>8}  COMMAND")
    for proc in procs:
        rss_kb = proc["rss"] * 4
        _out(f"{proc['pid']:>6} {proc['ppid']:>6} {proc['state']:<5} "
             f"{fmt.human_size(rss_kb * 1024):>8} "
             f"{fmt.human_cputime(proc['utime'] + proc['stime']):>8}  {proc['name']}")
    return 0


@command("kill", "System", "send a signal to processes  (-9, -TERM, ...)")
def kill(shell, args):
    sig = signal.SIGTERM
    pids = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1:
            name = arg[1:].upper()
            try:
                sig = int(name)
            except ValueError:
                try:
                    sig = getattr(signal, f"SIG{name}")
                except AttributeError:
                    _err(f"kill: unknown signal '{arg}'")
                    return 2
        else:
            pids.append(arg)
    if not pids:
        _err("usage: kill [-SIGNAL] PID...")
        return 2
    status = 0
    for pid in pids:
        try:
            os.kill(int(pid), signal.Signals(sig) if isinstance(sig, int) else sig)
        except (ValueError, ProcessLookupError):
            _err(f"kill: {pid}: no such process")
            status = 1
        except PermissionError:
            _err(f"kill: {pid}: permission denied")
            status = 1
    return status


@command("free", "System", "show memory usage")
def free(shell, args):
    human = any("h" in a for a in args if a.startswith("-"))
    mem = read_meminfo()
    total = mem.get("MemTotal", 0)
    free_kb = mem.get("MemFree", 0)
    buffers = mem.get("Buffers", 0)
    cached = mem.get("Cached", 0)
    available = mem.get("MemAvailable", free_kb + buffers + cached)
    used = total - free_kb - buffers - cached

    def show(value):
        return fmt.human_size(value * 1024) if human else str(value)

    _out(f"{'':>10} {'total':>9} {'used':>9} {'free':>9} {'buff/cache':>12} {'available':>12}")
    _out(f"{'Mem:':>10} {show(total):>9} {show(used):>9} {show(free_kb):>9} "
         f"{show(buffers + cached):>12} {show(available):>12}")
    swap_total = mem.get("SwapTotal", 0)
    swap_free = mem.get("SwapFree", 0)
    if swap_total:
        _out(f"{'Swap:':>10} {show(swap_total):>9} {show(swap_total - swap_free):>9} "
             f"{show(swap_free):>9} {'-':>12} {'-':>12}")
    return 0


@command("df", "System", "show filesystem usage  (-h human)")
def df(shell, args):
    human = any("h" in a for a in args if a.startswith("-"))
    paths = [a for a in args if not a.startswith("-")]
    entries = []
    if paths:
        for path in paths:
            try:
                st = os.statvfs(path)
                entries.append((path, st))
            except OSError as exc:
                _err(f"df: {path}: {exc.strerror}")
                return 1
    else:
        seen = set()
        try:
            with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    source, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
                    if fstype in ("proc", "sysfs", "devtmpfs", "devpts", "tmpfs",
                                  "cgroup", "cgroup2", "debugfs", "tracefs", "securityfs",
                                  "pstore", "bpf", "mqueue", "configfs", "fusectl", "ramfs"):
                        continue
                    if mount in seen:
                        continue
                    seen.add(mount)
                    try:
                        entries.append((mount, os.statvfs(mount)))
                    except OSError:
                        continue
        except OSError:
            pass
        if not entries:
            try:
                entries.append(("/", os.statvfs("/")))
            except OSError:
                return 1

    _out(f"{'Filesystem':<20} {'Size':>8} {'Used':>8} {'Avail':>8} {'Use%':>5}  Mounted on")
    for name, st in entries:
        size = st.f_blocks * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        used = size - st.f_bfree * st.f_frsize
        pct = (used / size * 100) if size else 0
        if human:
            vals = (fmt.human_size(size), fmt.human_size(used), fmt.human_size(avail))
        else:
            vals = (str(size // 1024), str(used // 1024), str(avail // 1024))
        _out(f"{name:<20} {vals[0]:>8} {vals[1]:>8} {vals[2]:>8} {pct:>4.0f}%  {name}")
    return 0


@command("uname", "System", "print system information  (-a all)")
def uname(shell, args):
    all_info = any("a" in a for a in args if a.startswith("-"))
    machine = os.uname().machine
    if all_info:
        _out(f"Linux {os.uname().nodename} {os.uname().release} {os.uname().version} "
             f"{machine} PythonOS")
    else:
        _out(os.uname().sysname)
    return 0


@command("uptime", "System", "show uptime and load average")
def uptime(shell, args):
    try:
        with open("/proc/uptime", "r", encoding="ascii") as fh:
            seconds = float(fh.read().split()[0])
    except OSError:
        seconds = 0.0
    try:
        with open("/proc/loadavg", "r", encoding="ascii") as fh:
            load = " ".join(fh.read().split()[:3])
    except OSError:
        load = "0.00 0.00 0.00"
    now = time.strftime("%H:%M:%S")
    procs = len(iter_processes())
    _out(f" {now} up {fmt.human_uptime(seconds)},  {procs} processes,  "
         f"load average: {load}")
    return 0


@command("date", "System", "show the current date and time")
def date(shell, args):
    if args and args[0].startswith("+"):
        _out(time.strftime(args[0][1:]))
    else:
        _out(fmt.human_date())
    return 0


@command("whoami", "System", "print the current user")
def whoami(shell, args):
    _out(shell.env.get("USER", "root"))
    return 0


@command("hostname", "System", "show or set the hostname")
def hostname(shell, args):
    if args:
        try:
            syscalls.sethostname(args[0])
            shell.env["HOSTNAME"] = args[0]
            if os.path.exists("/etc/hostname"):
                with open("/etc/hostname", "w", encoding="utf-8") as fh:
                    fh.write(args[0] + "\n")
            return 0
        except OSError as exc:
            _err(f"hostname: {exc.strerror}")
            return 1
    _out(os.uname().nodename)
    return 0


@command("env", "System", "print the environment")
def env_cmd(shell, args):
    for key in sorted(shell.env):
        if key.startswith("__"):
            continue
        _out(f"{key}={shell.env[key]}")
    return 0


@command("export", "System", "set an environment variable  (export NAME=VALUE)")
def export(shell, args):
    status = 0
    for item in args:
        if "=" in item:
            name, _, value = item.partition("=")
            shell.env[name] = value
            os.environ[name] = value
        elif item in shell.env:
            os.environ[item] = shell.env[item]
        else:
            _err(f"export: {item}: not set")
            status = 1
    return status


@command("unset", "System", "remove an environment variable")
def unset(shell, args):
    for name in args:
        shell.env.pop(name, None)
        os.environ.pop(name, None)
    return 0


@command("which", "System", "locate a command")
def which(shell, args):
    status = 0
    for name in args:
        if name in COMMANDS:
            _out(f"{name}: pysh builtin")
            continue
        path = shutil.which(name, path=shell.env.get("PATH", ""))
        if path:
            _out(path)
        else:
            _err(f"which: no {name} in PATH")
            status = 1
    return status


@command("mount", "System", "list mounted filesystems")
def mount_cmd(shell, args):
    if not args:
        try:
            with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) >= 4:
                        _out(f"{parts[0]} on {parts[1]} type {parts[2]} ({parts[3]})")
        except OSError as exc:
            _err(f"mount: {exc.strerror}")
            return 1
        return 0
    _err("mount: this build only lists mounts (pythonos init does the mounting)")
    return 1


def _poweroff(shell, reason, cmd):
    print(ansi.yellow(f"\n  {reason}"))
    try:
        syscalls.reboot(cmd)
    except OSError as exc:
        _err(f"{reason.lower()}: {exc.strerror}")
        return 1
    return 0


@command("poweroff", "System", "halt and power off the machine", aliases=("halt", "shutdown"))
def poweroff_cmd(shell, args):
    return _poweroff(shell, "Powering off PythonOS...", syscalls.RB_POWER_OFF)


@command("reboot", "System", "restart the machine")
def reboot_cmd(shell, args):
    return _poweroff(shell, "Rebooting PythonOS...", syscalls.RB_AUTOBOOT)


@command("sleep", "Misc", "pause for N seconds")
def sleep_cmd(shell, args):
    if not args:
        _err("usage: sleep SECONDS")
        return 2
    try:
        time.sleep(float(args[0]))
    except ValueError:
        _err(f"sleep: invalid time '{args[0]}'")
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


@command("echo", "Misc", "print arguments  (-n no newline)")
def echo(shell, args):
    newline = True
    if args and args[0] == "-n":
        newline = False
        args = args[1:]
    text = " ".join(args)
    if newline:
        _out(text)
    else:
        sys.stdout.write(text)
        sys.stdout.flush()
    return 0


@command("printf", "Misc", "format and print data")
def printf_cmd(shell, args):
    if not args:
        return 0
    fmtstr = args[0].replace("\\n", "\n").replace("\\t", "\t")
    values = args[1:]
    try:
        sys.stdout.write(fmtstr % tuple(values) if values else fmtstr)
    except (TypeError, ValueError):
        sys.stdout.write(fmtstr + " " + " ".join(values))
    return 0


@command("true", "Misc", "do nothing, successfully")
def true_cmd(shell, args):
    return 0


@command("false", "Misc", "do nothing, unsuccessfully")
def false_cmd(shell, args):
    return 1


@command("seq", "Misc", "print a sequence of numbers")
def seq_cmd(shell, args):
    try:
        numbers = [int(a) for a in args]
    except ValueError:
        _err("seq: numeric arguments required")
        return 2
    if len(numbers) == 1:
        start, step, stop = 1, 1, numbers[0]
    elif len(numbers) == 2:
        start, step, stop = numbers[0], 1, numbers[1]
    elif len(numbers) == 3:
        start, step, stop = numbers
    else:
        _err("usage: seq [START [STEP]] STOP")
        return 2
    if step == 0:
        _err("seq: step cannot be zero")
        return 2
    value = start
    if step > 0:
        while value <= stop:
            _out(str(value))
            value += step
    else:
        while value >= stop:
            _out(str(value))
            value += step
    return 0


@command("yes", "Misc", "print a string until interrupted")
def yes_cmd(shell, args):
    text = " ".join(args) if args else "y"
    try:
        while True:
            _out(text)
    except (KeyboardInterrupt, BrokenPipeError):
        return 130


@command("basename", "Misc", "strip directory from a path")
def basename_cmd(shell, args):
    if not args:
        _err("usage: basename PATH")
        return 2
    result = os.path.basename(args[0].rstrip("/")) or "/"
    if len(args) > 1 and result.endswith(args[1]):
        result = result[:-len(args[1])]
    _out(result)
    return 0


@command("dirname", "Misc", "strip the last component from a path")
def dirname_cmd(shell, args):
    if not args:
        _err("usage: dirname PATH")
        return 2
    _out(os.path.dirname(args[0]) or ".")
    return 0


# ---------------------------------------------------------------------------
# PythonOS extras
# ---------------------------------------------------------------------------
@command("py", "PythonOS", "run Python in the shell: py <code>, or bare py for a REPL")
def py_cmd(shell, args):
    import code as codemod

    if not args:
        namespace = {"sh": shell, "os": os, "sys": sys}
        print(ansi.dim("Python REPL inside pysh — Ctrl-D returns to the shell"))
        codemod.interact(banner="", exitmsg=ansi.dim("back to pysh"))
        return 0

    source = " ".join(args)
    namespace = {"sh": shell, "os": os, "sys": sys, "__name__": "__pysh__"}
    try:
        try:
            result = eval(compile(source, "<py>", "eval"), namespace)  # noqa: S307
            if result is not None:
                if hasattr(result, "__next__"):
                    for item in result:
                        print(item)
                else:
                    print(result)
        except SyntaxError:
            exec(compile(source, "<py>", "exec"), namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        _err(f"py: {type(exc).__name__}: {exc}")
        return 1
    return 0


@command("pyfetch", "PythonOS", "display system information")
def pyfetch_cmd(shell, args):
    from pythonos.tools import pyfetch
    return pyfetch.main([a for a in args if a != ""])


@command("pytop", "PythonOS", "interactive process monitor  (q to quit)")
def pytop_cmd(shell, args):
    from pythonos.tools import pytop
    return pytop.main(args)


@command("pyedit", "PythonOS", "full-screen text editor  (pyedit FILE)")
def pyedit_cmd(shell, args):
    from pythonos.tools import pyedit
    return pyedit.main(args)


@command("pkg", "PythonOS", "PythonOS package manager  (pkg list|install|remove|search)")
def pkg_cmd(shell, args):
    from pythonos.tools import pkg
    return pkg.main(args)
