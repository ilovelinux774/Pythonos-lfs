"""pkg — PythonOS' package manager.

Packages are plain directories with an ``app.json`` manifest. Installing
copies the package into /usr/lib/pythonos/apps/<name> and drops a launcher
into /usr/bin. The repo is a directory on disk, so the whole thing works
offline.
"""

import json
import os
import shutil
import sys

from pythonos.tui import ansi

APPS_DIR = os.environ.get("PYTHONOS_APPS_DIR", "/usr/lib/pythonos/apps")
BIN_DIR = os.environ.get("PYTHONOS_BIN_DIR", "/usr/bin")
DB_PATH = os.environ.get("PYTHONOS_PKG_DB", "/var/lib/pythonos/pkg/installed.json")
REPO_DIRS = tuple(os.environ.get("PYTHONOS_REPO_DIRS",
                                 "/usr/share/pythonos/repo").split(":"))


def _color(text, code):
    return ansi.colorize(text, code)


def load_db():
    try:
        with open(DB_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"packages": {}}


def save_db(db):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as fh:
        json.dump(db, fh, indent=2, sort_keys=True)


def repo_packages():
    found = {}
    for root in REPO_DIRS:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            manifest = os.path.join(root, name, "app.json")
            if os.path.isfile(manifest):
                try:
                    with open(manifest, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    data["path"] = os.path.join(root, name)
                    found[name] = data
                except (OSError, json.JSONDecodeError):
                    continue
    return found


def find_repo_package(name):
    packages = repo_packages()
    if name in packages:
        return packages[name]
    print(_color(f"pkg: no package '{name}' in the repository", ansi.RED))
    similar = [p for p in packages if name.lower() in p.lower() or p.lower() in name.lower()]
    if similar:
        print(f"     did you mean: {', '.join(sorted(similar))}")
    return None


def cmd_help():
    print("""
  PythonOS package manager

    pkg list                 installed packages
    pkg search [term]        browse the on-disk repository
    pkg info NAME            show details
    pkg install NAME         install a package
    pkg remove NAME          uninstall a package

  Packages install to /usr/lib/pythonos/apps and expose a command in /usr/bin.
""")
    return 0


def cmd_list(argv):
    db = load_db()
    packages = db.get("packages", {})
    if not packages:
        print("  " + ansi.dim("no packages installed — try: pkg search"))
        return 0
    print(f"  {'NAME':<18} {'VERSION':<10} DESCRIPTION")
    for name in sorted(packages):
        info = packages[name]
        print(f"  {name:<18} {info.get('version', '?'):<10} {info.get('description', '')}")
    return 0


def cmd_search(argv):
    term = argv[0].lower() if argv else ""
    installed = load_db().get("packages", {})
    packages = repo_packages()
    rows = 0
    for name in sorted(packages):
        info = packages[name]
        blob = (name + " " + info.get("description", "")).lower()
        if term and term not in blob:
            continue
        mark = _color("[installed]", ansi.GREEN) if name in installed else ansi.dim("[ ]")
        print(f"  {mark:<14} {name:<18} {info.get('version', '?'):<8} "
              f"{info.get('description', '')}")
        rows += 1
    if not rows:
        print("  " + ansi.dim("nothing matched"))
    return 0


def cmd_info(argv):
    if not argv:
        print("usage: pkg info NAME", file=sys.stderr)
        return 2
    name = argv[0]
    db = load_db().get("packages", {})
    info = None
    if name in db:
        info = dict(db[name])
        info["source"] = "installed"
    else:
        repo = find_repo_package(name)
        if not repo:
            return 1
        info = dict(repo)
        info["source"] = "repository"
    print(f"  {_color(info.get('name', name), ansi.BOLD, ansi.CYAN)} "
          f"{info.get('version', '?')}")
    print(f"  {info.get('description', '')}")
    print(f"  entry: {info.get('entry', name)}   source: {info['source']}")
    if "author" in info:
        print(f"  author: {info['author']}")
    return 0


def _write_launcher(entry, name):
    launcher = os.path.join(BIN_DIR, entry)
    content = (
        "#!/usr/bin/python3\n"
        f"# PythonOS launcher for package '{name}'\n"
        "import sys\n"
        "sys.path.insert(0, '/usr/lib')\n"
        "sys.path.insert(0, '/usr/lib/pythonos')\n"
        "import runpy\n"
        f"runpy.run_path('{APPS_DIR}/{name}/main.py', run_name='__main__')\n"
    )
    with open(launcher, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.chmod(launcher, 0o755)
    return launcher


def cmd_install(argv):
    if not argv:
        print("usage: pkg install NAME", file=sys.stderr)
        return 2
    name = argv[0]
    repo = find_repo_package(name)
    if not repo:
        return 1
    db = load_db()
    if name in db.get("packages", {}):
        print(f"  package {name} is already installed "
              f"({db['packages'][name].get('version')}) — reinstalling")

    target = os.path.join(APPS_DIR, name)
    try:
        os.makedirs(APPS_DIR, exist_ok=True)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(repo["path"], target)
        entry = repo.get("entry", name)
        launcher = _write_launcher(entry, name)
    except OSError as exc:
        print(_color(f"pkg: install failed: {exc.strerror or exc}", ansi.RED))
        return 1

    db.setdefault("packages", {})[name] = {
        "version": repo.get("version", "0.1"),
        "description": repo.get("description", ""),
        "entry": entry,
        "launcher": launcher,
    }
    save_db(db)
    print(f"  {ansi.green('installed')} {name} {repo.get('version')}  →  "
          f"run it with '{ansi.bold(entry)}'")
    return 0


def cmd_remove(argv):
    if not argv:
        print("usage: pkg remove NAME", file=sys.stderr)
        return 2
    name = argv[0]
    db = load_db()
    packages = db.get("packages", {})
    if name not in packages:
        print(_color(f"pkg: {name} is not installed", ansi.RED))
        return 1
    info = packages.pop(name)
    try:
        target = os.path.join(APPS_DIR, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
        launcher = info.get("launcher")
        if launcher and os.path.exists(launcher):
            os.remove(launcher)
    except OSError as exc:
        print(_color(f"pkg: remove failed: {exc.strerror or exc}", ansi.RED))
        return 1
    save_db(db)
    print(f"  {ansi.yellow('removed')} {name}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return cmd_help()
    cmd, rest = argv[0], argv[1:]
    table = {
        "list": cmd_list,
        "search": cmd_search,
        "info": cmd_info,
        "install": cmd_install,
        "remove": cmd_remove,
        "uninstall": cmd_remove,
        "help": lambda _a: cmd_help(),
    }
    fn = table.get(cmd)
    if not fn:
        print(_color(f"pkg: unknown command '{cmd}'", ansi.RED))
        return cmd_help() and 2
    return fn(rest)


if __name__ == "__main__":
    sys.exit(main())
