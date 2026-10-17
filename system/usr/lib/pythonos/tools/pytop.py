"""pytop — a tiny htop for PythonOS.

Pure Python process viewer: header with load/memory/CPU bars and a
refreshing process table. Press q to quit, c/m/p to change the sort.
"""

import os
import select
import sys
import time

from pythonos.pysh import builtins as shellsh
from pythonos.pysh import fmt
from pythonos.tui import ansi

BAR_WIDTH = 24


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _bar(fraction, width=BAR_WIDTH):
    filled = int(_clamp(fraction) * width)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def cpu_times():
    """Return (busy, total) jiffies since boot from /proc/stat."""
    try:
        with open("/proc/stat", "r", encoding="ascii") as fh:
            line = fh.readline()
    except OSError:
        return 0, 1
    fields = [int(x) for x in line.split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    total = sum(fields)
    return total - idle, total


def snapshot(prev_cpu=None, prev_procs=None, interval=0.0):
    now = time.time()
    busy, total = cpu_times()
    cpu_pct = 0.0
    if prev_cpu:
        dbusy = busy - prev_cpu[0]
        dtotal = total - prev_cpu[1]
        if dtotal > 0:
            cpu_pct = dbusy / dtotal * 100.0

    mem = shellsh.read_meminfo()
    mem_total = mem.get("MemTotal", 1)
    mem_available = mem.get("MemAvailable", mem.get("MemFree", 0))
    mem_used = max(mem_total - mem_available, 0)

    procs = shellsh.iter_processes()
    tck = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    prev_map = prev_procs or {}
    rows = []
    for proc in procs:
        cpu = 0.0
        if proc["pid"] in prev_map and interval > 0:
            dticks = (proc["utime"] + proc["stime"]) - prev_map[proc["pid"]]
            cpu = max(dticks, 0) / tck / interval * 100.0
        rss_kb = proc["rss"] * 4
        rows.append({
            "pid": proc["pid"],
            "state": proc["state"],
            "threads": proc["threads"],
            "cpu": cpu,
            "mem": rss_kb / mem_total * 100.0 if mem_total else 0.0,
            "rss": rss_kb,
            "time": proc["utime"] + proc["stime"],
            "name": proc["name"] or "?",
        })

    try:
        load = open("/proc/loadavg", encoding="ascii").read().split()[:3]
    except OSError:
        load = ["0.00", "0.00", "0.00"]
    try:
        uptime = float(open("/proc/uptime", encoding="ascii").read().split()[0])
    except (OSError, ValueError, IndexError):
        uptime = 0.0

    return {
        "cpu_pct": cpu_pct,
        "cpu_raw": (busy, total),
        "mem_total": mem_total,
        "mem_used": mem_used,
        "mem_pct": mem_used / mem_total if mem_total else 0.0,
        "procs": rows,
        "load": load,
        "uptime": uptime,
        "now": now,
        "raw": {p["pid"]: p["utime"] + p["stime"] for p in procs},
    }


def render(state, sort_key="cpu", message=""):
    cols, lines = ansi.terminal_size()
    out = []
    out.append(ansi.colorize("  pytop ", ansi.BOLD, ansi.BRIGHT_WHITE, ansi.REVERSE)
               + ansi.dim(f"  PythonOS process monitor   up {fmt.human_uptime(state['uptime'])}"))
    load = state["load"]
    out.append(
        f"  Load: {load[0]} {load[1]} {load[2]}"
        f"    CPU {_bar(state['cpu_pct'] / 100.0)} {state['cpu_pct']:5.1f}%"
    )
    out.append(
        f"  Mem:  {_bar(state['mem_pct'])} {state['mem_pct'] * 100:4.0f}%"
        f"  {fmt.human_size(state['mem_used'] * 1024)} / {fmt.human_size(state['mem_total'] * 1024)}"
    )
    sort_label = {"cpu": "CPU%", "mem": "MEM%", "pid": "PID", "time": "TIME"}[sort_key]
    out.append(ansi.dim(f"  sort: {sort_label}   keys: c cpu  m mem  p pid  t time  q quit"))
    out.append(ansi.bold(
        f"  {'PID':>6} {'S':<2} {'CPU%':>6} {'MEM%':>6} {'RES':>8} {'TIME':>8} {'THR':>4}  COMMAND"))
    out.append(ansi.dim("  " + "-" * min(cols - 4, 76)))

    key_map = {"cpu": lambda r: (-r["cpu"], r["pid"]),
               "mem": lambda r: (-r["rss"], r["pid"]),
               "pid": lambda r: (r["pid"],),
               "time": lambda r: (-r["time"], r["pid"])}
    procs = sorted(state["procs"], key=key_map[sort_key])

    max_rows = max(lines - 8, 2)
    for row in procs[:max_rows]:
        colour = ansi.GREEN if row["state"] == "R" else ""
        name = row["name"]
        limit = max(cols - 52, 8)
        if len(name) > limit:
            name = name[: max(limit - 1, 1)] + "~"
        line = (f"  {row['pid']:>6} {row['state']:<2} {row['cpu']:>6.1f} {row['mem']:>6.1f} "
                f"{fmt.human_size(row['rss'] * 1024):>8} {fmt.human_cputime(row['time']):>8} "
                f"{row['threads']:>4}  {name}")
        if colour:
            line = ansi.colorize(line, colour)
        out.append(line)

    if len(procs) > max_rows:
        out.append(ansi.dim(f"  ... {len(procs) - max_rows} more"))
    out.append("")
    if message:
        out.append("  " + message)
    return out


def _read_key(timeout):
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    data = os.read(sys.stdin.fileno(), 1)
    if not data:
        return "q"
    try:
        return data.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    once = "--once" in argv
    interval = 1.0
    for arg in argv:
        if arg.startswith("--interval="):
            try:
                interval = float(arg.split("=", 1)[1])
            except ValueError:
                pass

    if once:
        state = snapshot()
        state = snapshot(prev_cpu=state["cpu_raw"], prev_procs=state["raw"], interval=0.2)
        print("\n".join(ansi.strip(line) for line in render(state)))
        return 0

    if not sys.stdin.isatty():
        state = snapshot()
        print("\n".join(ansi.strip(line) for line in render(state)))
        return 0

    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    sort_key = "cpu"
    state = snapshot()
    message = ""
    ansi.enter_alt_screen()
    ansi.hide_cursor()
    try:
        tty.setraw(fd)
        while True:
            prev = state
            time.sleep(interval)
            state = snapshot(prev_cpu=prev["cpu_raw"], prev_procs=prev["raw"],
                             interval=interval)
            ansi.clear()
            ansi.home()
            sys.stdout.write("\n".join(render(state, sort_key, message)) + "\n")
            sys.stdout.flush()
            key = _read_key(0.01)
            if key in ("q", "Q"):
                break
            elif key == "c":
                sort_key, message = "cpu", ""
            elif key == "m":
                sort_key, message = "mem", ""
            elif key == "p":
                sort_key, message = "pid", ""
            elif key == "t":
                sort_key, message = "time", ""
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        ansi.show_cursor()
        ansi.exit_alt_screen()
    return 0
