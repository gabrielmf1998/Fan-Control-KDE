#!/usr/bin/env python3
"""Grab the documentation screenshots offscreen, so they can be regenerated.

Run with a live helper on the machine and the readings are real; run without one
and the widgets still draw, just with nothing in them. Either way this beats a
hand-cropped PNG that goes stale the first time a label changes.

    python3 assets/gen_screenshots.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fancontrol import curveeditor, curves, system  # noqa: E402
from fancontrol.config import Config  # noqa: E402
from fancontrol.devices import Monitor  # noqa: E402
from fancontrol.settings import SettingsDialog  # noqa: E402
from fancontrol.updates import UpdateChecker  # noqa: E402

DOCS = HERE.parent / "docs"


def shot_curve_editor() -> None:
    editor = curveeditor.CurveEditor()
    editor.resize(760, 300)
    editor.set_curve(curves.with_preset("Balanced"))
    editor.curve["min_percent"] = 25
    editor.curve["zero_below"] = 0
    editor.warn_temp, editor.critical_temp = 75, 90
    # a plausible warm-up, so the trail is not one lonely dot
    for i in range(60):
        temp = 42.0 + 22.0 * (i / 60.0) ** 1.4
        editor.set_live(temp, curves.effective_at(editor.curve, temp) - 3.0,
                        1240 + i * 6, "CPU · Tctl")
    editor.grab().save(str(DOCS / "curve-editor.png"), "PNG")
    print("wrote curve-editor.png")


def shot_tabs() -> None:
    cfg = Config()
    monitor = Monitor(cfg)
    dialog = SettingsDialog(cfg, monitor, system.Privileged(), UpdateChecker())
    dialog.resize(960, 800)
    monitor.start()

    names = ["appearance", "states", "fans", "curves", "behaviour", "updates"]

    def grab() -> None:
        for index, name in enumerate(names):
            dialog.tabs.setCurrentIndex(index)
            QApplication.processEvents()
            dialog.grab().save(str(DOCS / f"tab-{name}.png"), "PNG")
            print(f"wrote tab-{name}.png")
        QApplication.instance().quit()

    # Give the helper one poll, so the Fans and Curves tabs have real hardware
    # in them rather than "Looking for fan controllers…".
    QTimer.singleShot(9000, grab)
    QApplication.instance().exec()


def main() -> int:
    QApplication([])
    DOCS.mkdir(exist_ok=True)
    shot_curve_editor()
    shot_tabs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
