# Modular PythonOS architecture

PythonOS has two ways to run the same Python desktop framework.

## Hosted mode — no VM required

A developer or user can run PythonOS as an ordinary application on a current
Linux, Windows or macOS computer:

Python 3.9 or newer is supported.

Linux/macOS:

```sh
git clone https://github.com/ilovelinux774/Pythonos-lfs.git
cd Pythonos-lfs
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
pythonos-desktop
```

Windows PowerShell:

```powershell
git clone https://github.com/ilovelinux774/Pythonos-lfs.git
cd Pythonos-lfs
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
pythonos-desktop
```

`pythonos-desktop` opens a PythonOS desktop window. Hosted mode uses PySide6
for portable native window creation and drawing. Qt is the native C++ layer;
the desktop logic, widgets, apps, launcher, terminal, taskbar and application
APIs are Python. The taskbar owns open-window buttons, minimize/restore,
status indicators and the clock rather than delegating the desktop experience
to the host OS. Qt selects X11/Wayland, Win32 or macOS graphics underneath, so
PythonOS does not require X11 on every host.

Hosted mode keeps its data in `~/.pythonos/` by default:

```
~/.pythonos/
├── files/       the PythonOS virtual home
├── apps/        installed hosted apps
├── config/      desktop settings
└── cache/       temporary app data
```

The first version deliberately keeps the virtual filesystem inside that
folder. An application cannot mistake the user's real `/`, `C:\\` or home
directory for the PythonOS filesystem. Explicit host integration can be
added through a permissioned platform API.

## Native mode — Alpine + OpenRC

The bootable image uses Alpine because the goal is to build PythonOS, not to
spend the project on reproducing a package manager, C library, kernel and
service manager:

```
Linux kernel
   │
Alpine minirootfs + BusyBox/musl
   │
OpenRC (PID 1 service management)
   │
PythonOS native services
   │
PythonOS desktop and applications
```

OpenRC is now the native service manager. Alpine's BusyBox `init` remains the
kernel-facing PID 1, OpenRC mounts the early filesystems and starts the
`pythonos` service, and `getty` launches `pysh` on tty1 and ttyS0. Python is
the framework and userland layer; it is not pretending to replace init when
a production service manager already exists.

The native image's OpenRC service is:

```
system/etc/init.d/pythonos
```

It runs `openrc_main.py`. With `pythonos.selftest=1`, that service runs the
full guest self-test and powers off. In normal mode it prints the PythonOS
report and leaves the consoles to OpenRC's gettys.

## Platform boundary

The UI and app code uses platform services instead of Linux-only calls:

```python
platform.open_file(path)
platform.get_clipboard()
platform.list_processes()
platform.launch_application(app)
```

The hosted backend implements those contracts with Python and Qt. The native
backend will implement them with Linux `/proc`, devices and OpenRC services.
Applications do not need to know where they run.

This is also the phone boundary later. A mobile backend can add touch,
rotation, battery, power and cellular services without rewriting the Python
application framework.

## What remains native

The project is intentionally not claiming that every byte is Python:

* Linux kernel: C and assembly
* musl, BusyBox and OpenRC: native system components
* Qt/PySide6: native graphics/windowing implementation exposed to Python
* drivers, codecs and hardware services: native components where practical

The part a user configures, sees and programs is Python. The low-level parts
are reused rather than rewritten for novelty.
