"""Starting the tray when the user logs in (XDG autostart).

This is only the icon. Re-applying fan speeds at boot is a different thing
entirely - that happens before anyone logs in, and goes through systemd on the
other side of the helper.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .config import APP_ID, APP_NAME

AUTOSTART_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / f"{APP_ID}.desktop"

# The 1.x package shipped its autostart entry under this name; leaving it in
# place would start the old tray alongside the new one.
LEGACY_FILES = (AUTOSTART_DIR / "fan-tray.desktop",
                AUTOSTART_DIR / "fan-control.desktop")

DESKTOP = """\
[Desktop Entry]
Type=Application
Name={name}
Comment=Fan speed, curves and temperatures in the system tray
Exec={exec}
Icon={icon}
Terminal=false
Categories=System;Monitor;Settings;
X-GNOME-Autostart-enabled=true
X-KDE-autostart-phase=2
"""


def _exec_command() -> str:
    launcher = shutil.which("fan-control") or shutil.which("fan-tray")
    if launcher:
        return launcher
    return f"{sys.executable} -m fancontrol"


def is_enabled() -> bool:
    return AUTOSTART_FILE.is_file()


def set_enabled(enabled: bool) -> bool:
    try:
        for stale in LEGACY_FILES:
            if stale.exists():
                stale.unlink()
        if enabled:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(
                DESKTOP.format(name=APP_NAME, exec=_exec_command(), icon=APP_ID),
                encoding="utf-8")
        elif AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
        return True
    except OSError:
        return False
