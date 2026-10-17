"""Formatting helpers shared by pysh and the userland tools."""

import time


def human_size(num, suffix="B"):
    num = float(num)
    for unit in ("", "K", "M", "G", "T"):
        if abs(num) < 1024.0:
            if unit == "":
                return f"{int(num)}{suffix}"
            return f"{num:.1f}{unit}{suffix}" if num < 100 else f"{num:.0f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}P{suffix}"


def human_uptime(seconds):
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def human_cputime(ticks):
    seconds = ticks / 100.0
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(int(mins), 60)
    if hours:
        return f"{hours}:{mins:02d}:{int(secs):02d}"
    return f"{int(mins)}:{int(secs):02d}"


def human_date(timestamp=None):
    timestamp = time.time() if timestamp is None else timestamp
    return time.strftime("%a %b %d %H:%M:%S %Z %Y", time.localtime(timestamp))
