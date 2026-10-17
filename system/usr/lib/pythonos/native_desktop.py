"""Native Alpine entry point for the shared PythonOS desktop."""

from __future__ import annotations

import os
import sys

# This file is launched directly by startx, so add the package parent before
# importing the shared desktop module.
if "/usr/lib" not in sys.path:
    sys.path.insert(0, "/usr/lib")
os.environ.setdefault("PYTHONOS_HOME", "/root/.pythonos")

from pythonos.desktop.main import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
