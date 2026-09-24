"""Fan Control KDE - a tray front end for every fan the machine will let us drive."""

import importlib.util
import os
import sys
from pathlib import Path

__version__ = "2.4.0"


def _pick_pyside6() -> None:
    """Use the distribution's PySide6, or else the copy shipped for the tray.

    Ubuntu 24.04 and its derivatives - Kubuntu, KDE neon - and Debian 12
    package no PySide6 at all. The fan-control-kde-pyside6 package and the
    AppImage carry a trimmed one at <prefix>/lib/fan-control-kde/pyside6,
    beside this package's <prefix>/share/fan-control-kde. It is only a
    fallback: a PySide6 built against the system's own Qt fits the desktop
    better, so that one wins whenever it is installed.
    FAN_CONTROL_PYSIDE6=bundled forces the copy.
    """
    try:
        bundled = (Path(__file__).resolve().parents[3]
                   / "lib" / "fan-control-kde" / "pyside6")
    except IndexError:
        return
    if not bundled.is_dir() or "PySide6" in sys.modules:
        return
    forced = os.environ.get("FAN_CONTROL_PYSIDE6") == "bundled"
    if not forced and importlib.util.find_spec("PySide6") is not None:
        return
    sys.path.insert(0, str(bundled))
    # This Qt must not load plugins built for the system's Qt - the KDE
    # platform theme above all, which would pull a second Qt into the process.
    for var in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE"):
        os.environ.pop(var, None)


_pick_pyside6()
