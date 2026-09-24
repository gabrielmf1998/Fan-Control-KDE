"""The settings window must not change anything by being opened.

It used to: building the Fans tab moved the slider of a card whose driver
starts at 30%, the move was taken for the user's, and the card was put on a
fixed speed - saved over the one chosen before, with its curve switched off.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_CONFIG = tempfile.TemporaryDirectory()
os.environ["XDG_CONFIG_HOME"] = _CONFIG.name
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from PySide6.QtCore import QObject, QTimer, Signal
    from PySide6.QtWidgets import QApplication, QSlider
except ImportError:                                   # pragma: no cover
    QApplication = None

GPU = {"id": "nvidia:0", "label": "NVIDIA GeForce RTX 3060 Ti", "kind": "gpu",
       "control": True, "backend": "nvidia", "range": [30, 100], "percent": 47,
       "mode": "auto", "rpms": [850, 850], "temp": 40, "features": {}}
HEADER = {"id": "hwmon:nct6799:pwm2", "label": "Fan header 2", "kind": "case",
          "control": True, "backend": "hwmon", "range": [0, 100], "percent": 100,
          "mode": "full", "rpms": [1540], "temp": 50,
          "features": {"hw_curve": True, "tach": True}}


def wait(ms: int) -> None:
    QTimer.singleShot(ms, QApplication.instance().quit)
    QApplication.instance().exec()


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class OpeningChangesNothing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_fan_row_sends_nothing_by_being_built_and_updated(self):
        from fancontrol.settings import FanRow
        sent = []
        row = FanRow(GPU, "GPU", True, True)
        row.apply_speed.connect(lambda dev, value: sent.append((dev, value)))
        row.update_reading(GPU, "auto", {})
        wait(700)
        self.assertEqual(sent, [])

    def test_a_hand_on_the_slider_does_send(self):
        from fancontrol.settings import FanRow
        sent = []
        row = FanRow(GPU, "GPU", True, True)
        row.apply_speed.connect(lambda dev, value: sent.append((dev, value)))
        row.update_reading(GPU, "auto", {})
        row.slider.triggerAction(QSlider.SliderAction.SliderPageStepAdd)
        wait(700)
        self.assertEqual(sent, [("nvidia:0", "52")])

    def test_the_whole_window_sends_nothing(self):
        from fancontrol import devices
        from fancontrol.config import Config
        from fancontrol.settings import SettingsDialog

        class Monitor(QObject):
            changed = Signal(object)

            def __init__(self):
                super().__init__()
                self.snapshot = devices.Snapshot({
                    "version": "test", "devices": [GPU, HEADER], "sensors": [],
                    "curves": {"curves": {}}, "runtime": {}, "saved": {},
                    "units": {"boot": "enabled", "curve": "enabled",
                              "curve_active": "active"}})

            def poll(self):
                pass

            def retime(self):
                pass

        class Priv(QObject):
            result = Signal(bool, str)

            def __init__(self):
                super().__init__()
                self.calls = []

            def run(self, args, stdin=""):
                self.calls.append(args)
                return True

        class Checker(QObject):
            checked = Signal(bool, str)
            busy = False
            release = None
            available = False

        monitor, priv = Monitor(), Priv()
        dialog = SettingsDialog(Config(), monitor, priv, Checker())
        dialog.show()
        for tab in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(tab)
            wait(150)
        monitor.changed.emit(monitor.snapshot)
        wait(700)
        dialog.close()
        self.assertEqual(priv.calls, [])


if __name__ == "__main__":
    unittest.main()
