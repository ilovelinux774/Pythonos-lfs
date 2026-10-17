# The PythonOS userland

Every command below is a Python function in `system/usr/lib/pythonos/`.
Run `help` inside the shell to see the same list, generated from the same
registry the shell dispatches from.

## Shell syntax (pysh)

```
command arg arg             run a builtin or external binary
cmd1 | cmd2                 pipe stdout into stdin
cmd > file                  redirect stdout (truncate)
cmd >> file                 redirect stdout (append)
cmd 2> file                 redirect stderr
cmd 2>&1                    merge stderr into stdout
cmd < file                  redirect stdin
a && b                      run b only if a succeeded
a || b                      run b only if a failed
a ; b                       run a, then b
echo $HOME ${USER} $?       variable expansion
echo 'literal $HOME'        single quotes: no expansion
ls /usr/*/bin               globbing (* ? [ ])
alias ll='ls -l'            aliases
```

Line editing and history (Up/Down, Ctrl-R) come from `readline`; the
history file is `~/.pysh_history`.

## Hosted desktop terminal

The PySide6 hosted desktop has a real single-buffer terminal with an inline
prompt, cursor editing, blinking caret, history, scrollback and selectable
output. Its app commands target the PythonOS desktop itself:

| Command | Description |
|---|---|
| `apps` | list applications provided by the PythonOS desktop |
| `open APP` | open a PythonOS application window |
| `run APP` | alias for `open APP` |

The available desktop apps are Welcome, Terminal, Files, Settings and About.
They open as managed PythonOS windows with taskbar buttons. The virtual
PythonOS filesystem remains under `~/.pythonos/files`.

## Navigation & session

| Command | Description |
|---|---|
| `cd [dir]` | change directory (`cd -` returns, `~` expands) |
| `pwd` | print working directory |
| `exit [code]` / `logout` | leave the shell |
| `history` | command history with numbers |
| `alias` / `unalias` | manage aliases |
| `help [cmd]` | list commands / help for one |
| `clear` | clear the screen |

## Files

| Command | Description |
|---|---|
| `ls [-lah1] [dir]` | list with colours, sizes, long format |
| `cat [file...]` | write files to stdout |
| `cp [-r] src... dst` | copy |
| `mv src... dst` | move / rename |
| `rm [-rf] path...` | remove (refuses `/`) |
| `mkdir [-p] dir` | create directories |
| `rmdir dir` | remove empty directories |
| `touch file` | create / update timestamp |
| `find [path] -name GLOB [-type f\|d]` | find files |
| `du [-sh] [path]` | disk usage |

## Text

| Command | Description |
|---|---|
| `head [-n N] [file]` | first N lines (10) |
| `tail [-n N] [file]` | last N lines (10) |
| `wc [-lwc] [file]` | lines / words / bytes |
| `grep [-nivc] PATTERN [file...]` | `re`-powered search, outlines matches |

`grep` takes Python regular expressions, not BRE/ERE — `grep -n '^[a-z]{3},'`
just works.

## System

| Command | Description |
|---|---|
| `ps` | process table from `/proc` |
| `pytop` | live process monitor (q quits, c/m/p/t sort) |
| `kill [-SIG] PID...` | send a signal |
| `free [-h]` | memory usage from `/proc/meminfo` |
| `df [-h]` | filesystem usage from `statvfs` |
| `mount` | list mounts from `/proc/mounts` |
| `uname [-a]` | kernel information |
| `uptime` | uptime, load average, process count |
| `date [+fmt]` | current time (`strftime` format) |
| `whoami`, `hostname` | identity |
| `env`, `export`, `unset` | environment |
| `which cmd` | locate a command |
| `poweroff`, `reboot` | `reboot(2)` via `ctypes` |
| `sleep`, `echo`, `printf`, `true`, `false`, `seq`, `yes` | the classics |
| `basename`, `dirname` | path surgery |

## PythonOS extras

| Command | Description |
|---|---|
| `py <code>` | evaluate Python in the live shell; bare `py` opens a REPL bound to the shell (`sh` is in scope) |
| `pyfetch [--plain]` | system summary |
| `pyedit FILE` | full-screen editor: arrows, Enter, Backspace, Tab, Ctrl-K cut, Ctrl-S save, Ctrl-Q quit |
| `pkg list \| search [t] \| info N \| install N \| remove N` | package manager |

### Examples worth typing

```sh
py "import os; print(sorted(os.listdir('/')))"
py 'print(sum(i*i for i in range(1, 11)))'
ps | grep python
free -h; df -h; uptime
seq 1 20 | grep '^1'
pkg install hello && hello PythonOS
```

## Adding a command

Builtins are registered by decorator in `pysh/builtins.py`:

```python
@command("hello", "Misc", "say hello")
def hello(shell, args):
    print("hello from a builtin")
    return 0
```

Rebuild (`make iso`), and `hello` exists in the shell, in `help`, and in
tab completion next. External tools are just launchers in `/usr/bin`:

```python
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/lib/pythonos")
sys.path.insert(0, "/usr/lib")
from pythonos.tools import mytool
sys.exit(mytool.main())
```

## Writing a package

```
myapp/
├── app.json    {"name": "myapp", "version": "1.0", "description": "...", "entry": "myapp"}
└── main.py     your program
```

Drop it into `system/usr/share/pythonos/repo/`, rebuild, then
`pkg install myapp` and run `myapp`.
