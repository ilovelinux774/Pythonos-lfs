"""hello — PythonOS' demo package."""

import os
import sys

GREETINGS = {
    "tr": "Merhaba",
    "es": "Hola",
    "de": "Hallo",
    "fr": "Bonjour",
    "ja": "こんにちは",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        who = " ".join(argv)
    else:
        who = os.environ.get("USER", "world")
    print(f"Hello, {who}! You are running PythonOS, and this program is Python.")
    print(f"It was installed with `pkg install hello` and lives in /usr/lib/pythonos/apps/hello.")
    print(f"Try a language: hello --tr Dunya   ({', '.join(GREETINGS)})")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0].startswith("--") and args[0][2:] in GREETINGS:
        lang = args[0][2:]
        who = " ".join(args[1:]) or "world"
        print(f"{GREETINGS[lang]}, {who}!")
        raise SystemExit(0)
    raise SystemExit(main())
