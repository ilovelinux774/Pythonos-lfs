#!/usr/bin/env python3
"""Capture a hosted desktop proof image without requiring a host display.

Qt's offscreen backend renders the same PythonOS window used by hosted mode.
This is useful in CI and keeps the README screenshot reproducible.
"""

import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, BASE)

from PySide6.QtWidgets import QApplication  # noqa: E402
from pythonos.desktop.main import DesktopWindow  # noqa: E402


app = QApplication(["pythonos-desktop-shot"])
window = DesktopWindow()
window.resize(1180, 760)
window.show()
app.processEvents()
output = os.path.join(BASE, "docs", "screenshots", "hosted-desktop.png")
os.makedirs(os.path.dirname(output), exist_ok=True)
window.grab().save(output)
print(f"saved {output}")
app.quit()
