# OpenRC integration

PythonOS uses Alpine Linux and OpenRC in native mode.

## Boot sequence

```text
kernel → /init compatibility wrapper → /sbin/init (BusyBox)
       → /sbin/openrc sysinit
       → /sbin/openrc boot
       → /sbin/openrc default
       → pythonos service + tty gettys
```

The build creates the runlevel links explicitly in `builder/build.py`:

* `sysinit`: `devfs`, `procfs`, `sysfs`
* `boot`: `hostname`, `bootmisc`, `localmount`
* `default`: `pythonos` (and `pythonos-gui` when the optional native GUI profile is staged)
* `shutdown`: `killprocs`, `mount-ro`

The service file is `system/etc/init.d/pythonos`. It runs the Python service
entry point at `system/usr/lib/pythonos/openrc_main.py`.

## Why not Python as PID 1?

Python remains the framework and userland language, but PID 1 is a critical
process supervisor. Alpine already gives us a small, tested init path and
OpenRC handles service ordering, respawning and shutdown. Replacing it would
spend time rebuilding infrastructure instead of building the Python desktop.

This also makes the native image easier to extend with future services:
networking, a display server, audio, input and the native PythonOS session
can each become normal OpenRC services.

## Self-test

The QEMU harness boots with:

```text
console=ttyS0 rdinit=/init pythonos.selftest=1
```

`/init` hands off to Alpine's `/sbin/init`; OpenRC starts `pythonos`; the
service runs `selftest.py --guest`, verifies that OpenRC owns PID 1 and that
the default runlevel marker exists, exercises pysh and the tools, then calls
`reboot(2)` to power off.
