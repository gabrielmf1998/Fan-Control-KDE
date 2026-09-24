"""The service that keeps speeds and runs curves, against a fake sysfs.

    python3 -m unittest discover -s tests -v      (or: make test)

Nothing here touches real hardware: the helper is loaded as a module and every
path it writes to is pointed into a temporary directory first. The fake chip
is an nct6799 with two headers, which is enough to see a speed restored, kept
against something moving it, and handed back when a curve stops.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_helper():
    loader = importlib.machinery.SourceFileLoader(
        "fan_control_helper", str(ROOT / "helper" / "fan-control-helper"))
    spec = importlib.util.spec_from_loader("fan_control_helper", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeMachine(unittest.TestCase):
    """A temporary sysfs with one nct6799 and two fan headers, and the
    helper's state directories moved next to it."""

    def setUp(self):
        self.h = load_helper()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.chip = root / "sys" / "class" / "hwmon" / "hwmon0"
        self.chip.mkdir(parents=True)
        (root / "sys" / "class" / "drm").mkdir(parents=True)
        self.write("name", "nct6799")
        for ch in (1, 2):
            self.write(f"pwm{ch}", "128")
            self.write(f"pwm{ch}_enable", "5")      # Smart Fan IV, the BIOS's
            self.write(f"fan{ch}_input", "900")
        self.write("temp1_input", "45000")
        self.write("temp1_label", "CPUTIN")
        etc = root / "etc" / "fan-control-kde"
        run = root / "run" / "fan-control-kde"
        self.systemd = root / "etc" / "systemd" / "system"
        h = self.h
        h.SYSFS_HWMON = str(root / "sys" / "class" / "hwmon")
        h.SYSFS_DRM = str(root / "sys" / "class" / "drm")
        h.STATE_DIR = str(etc)
        h.STATE = str(etc / "state.json")
        h.CURVES = str(etc / "curves.json")
        h.HWBACKUP = str(etc / "firmware-curves.json")
        h.RUN_DIR = str(run)
        h.RUN_STATUS = str(run / "status.json")
        h.CALIBRATING_DIR = str(run / "calibrating")
        h.SYSTEMD_ETC = str(self.systemd)
        # No NVIDIA card, no lspci, no systemctl: this machine is the fake one.
        h.Nvml._state = False
        h.nvidia_gpus = lambda max_age=2.0: []
        self.commands = []
        h.run = self._run
        h.log = lambda msg: None
        patcher = mock.patch("os.geteuid", return_value=0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def _run(self, args, timeout=10):
        self.commands.append(list(args))
        return None

    def write(self, name, value):
        (self.chip / name).write_text(str(value))

    def read(self, name):
        return (self.chip / name).read_text().strip()

    def state(self, speeds, restore=True, set_at=None):
        self.h.write_json(self.h.STATE, {
            "version": 2, "restore_at_boot": restore, "service": True,
            "speeds": speeds, "set_at": set_at or {}})

    def daemon(self):
        d = self.h.Daemon()
        d.discover()
        d.files_changed()
        d.reload()
        return d


class Restore(FakeMachine):
    def test_saved_speeds_come_back_at_start(self):
        self.state({"hwmon:nct6799:pwm1": "100", "hwmon:nct6799:pwm2": "40"})
        self.daemon()
        self.assertEqual(self.read("pwm1_enable"), "0")        # full speed
        self.assertEqual(self.read("pwm2_enable"), "1")        # manual
        self.assertEqual(self.read("pwm2"), str(round(0.40 * 255)))

    def test_nothing_comes_back_when_that_is_switched_off(self):
        self.state({"hwmon:nct6799:pwm2": "40"}, restore=False,
                   set_at={"hwmon:nct6799:pwm2": 1.0})
        d = self.daemon()
        self.assertEqual(self.read("pwm2_enable"), "5")
        self.assertEqual(d.held, {})

    def test_a_speed_set_after_start_is_kept_even_with_restore_off(self):
        self.state({"hwmon:nct6799:pwm2": "40"}, restore=False,
                   set_at={"hwmon:nct6799:pwm2": 1.0})
        d = self.daemon()
        self.state({"hwmon:nct6799:pwm2": "60"}, restore=False,
                   set_at={"hwmon:nct6799:pwm2": time.time()})
        d.reload()
        self.assertEqual(self.read("pwm2"), str(round(0.60 * 255)))
        self.assertEqual(d.held, {"hwmon:nct6799:pwm2": "60"})


class Keep(FakeMachine):
    def test_a_speed_moved_by_something_else_is_put_back(self):
        self.state({"hwmon:nct6799:pwm2": "100"})
        d = self.daemon()
        # what the board did a few seconds after boot
        self.write("pwm2_enable", "1")
        self.write("pwm2", "77")
        report = {"fans": {}, "held": {}}
        d.keep(time.monotonic() + 10, report)
        self.assertEqual(self.read("pwm2_enable"), "0")
        self.assertEqual(report["held"]["hwmon:nct6799:pwm2"]["put_back"], 1)

    def test_a_speed_left_alone_is_not_rewritten(self):
        self.state({"hwmon:nct6799:pwm2": "40"})
        d = self.daemon()
        writes = []
        real = self.h.write_raw
        self.h.write_raw = lambda path, value: writes.append(path) or real(path, value)
        d.keep(time.monotonic() + 10, {"fans": {}, "held": {}})
        self.assertEqual(writes, [])

    def test_auto_is_applied_but_not_kept(self):
        self.write("pwm2_enable", "1")
        self.state({"hwmon:nct6799:pwm2": "auto"})
        d = self.daemon()
        self.assertEqual(self.read("pwm2_enable"), "5")
        self.assertEqual(d.held, {})

    def test_a_readback_off_by_one_is_still_the_speed(self):
        backend = self.h.HwmonChannel(str(self.chip), 2, "nct6799")
        self.write("pwm2_enable", "1")
        self.write("pwm2", str(round(0.40 * 255) - 1))
        self.assertTrue(backend.matches("40"))
        self.write("pwm2", "77")
        self.assertFalse(backend.matches("40"))


class Curves(FakeMachine):
    def curve(self, enabled=True, **extra):
        c = dict(self.h.CURVE_DEFAULTS)
        c.update({"enabled": enabled, "source": "nct6799:CPUTIN",
                  "points": [[30, 30], [60, 60]], "ramp_up": 100,
                  "ramp_down": 100, "hysteresis": 0})
        c.update(extra)
        self.h.write_json(self.h.CURVES, {"version": 1, "interval_ms": 1000,
                                          "curves": {"hwmon:nct6799:pwm2": c}})

    def tick(self, d):
        report = {"fans": {}, "held": {}}
        d.tick_curves(time.monotonic(), self.h.discover_sensors(), report)
        return report

    def test_a_curve_runs(self):
        self.curve()
        d = self.daemon()
        report = self.tick(d)
        self.assertEqual(report["fans"]["hwmon:nct6799:pwm2"]["percent"], 45)
        self.assertEqual(self.read("pwm2_enable"), "1")

    def test_stopping_a_curve_hands_the_fan_to_the_firmware(self):
        self.curve()
        d = self.daemon()
        self.tick(d)
        self.curve(enabled=False)
        d.reload()
        self.assertEqual(self.read("pwm2_enable"), "5")

    def test_stopping_a_curve_goes_back_to_the_speed_set_by_hand(self):
        self.state({"hwmon:nct6799:pwm2": "80"})
        self.curve()
        d = self.daemon()
        self.tick(d)
        self.curve(enabled=False)
        d.reload()
        self.assertEqual(self.read("pwm2"), str(round(0.80 * 255)))
        self.assertEqual(d.held, {"hwmon:nct6799:pwm2": "80"})

    def test_a_slow_ramp_checked_often_still_arrives(self):
        c = dict(self.h.CURVE_DEFAULTS)
        c.update(points=[[30, 20], [80, 100]], ramp_down=2, hysteresis=0)
        runner = self.h.CurveRunner({"label": "x"}, c, "s", interval=0.2, start=45.0)
        now = 0.0
        for _ in range(int(60 / 0.2)):
            level, _why = runner.target(40.0, now)
            now += 0.2
        self.assertEqual(round(level), 36)

    def test_a_turning_fan_is_not_kicked_when_a_curve_takes_it(self):
        c = dict(self.h.CURVE_DEFAULTS)
        c.update(points=[[30, 20], [80, 100]], hysteresis=0)
        runner = self.h.CurveRunner({"label": "x"}, c, "s", interval=1.0, start=30.0)
        _level, why = runner.target(40.0, 0.0)
        self.assertNotEqual(why, "spin-up")

    def test_a_stopped_fan_is(self):
        c = dict(self.h.CURVE_DEFAULTS)
        c.update(points=[[30, 20], [80, 100]], hysteresis=0)
        runner = self.h.CurveRunner({"label": "x"}, c, "s", interval=1.0, start=0.0)
        level, why = runner.target(40.0, 0.0)
        self.assertEqual((why, level), ("spin-up", 45.0))

    def test_setting_a_speed_by_hand_switches_the_curve_off(self):
        self.curve()
        self.assertEqual(self.h.cmd_set("hwmon:nct6799:pwm2", "70"), 0)
        store = json.loads(Path(self.h.CURVES).read_text())
        self.assertFalse(store["curves"]["hwmon:nct6799:pwm2"]["enabled"])
        state = self.h.state_load()
        self.assertEqual(state["speeds"]["hwmon:nct6799:pwm2"], "70")


class Migrate(FakeMachine):
    def link(self, target, unit):
        wants = self.systemd / target
        wants.mkdir(parents=True, exist_ok=True)
        os.symlink("/usr/lib/systemd/system/" + unit, wants / unit)
        return wants / unit

    def test_a_23_install_keeps_its_choice_and_loses_its_units(self):
        Path(self.h.STATE).parent.mkdir(parents=True)
        Path(self.h.STATE).write_text(json.dumps({"hwmon:nct6799:pwm2": "100"}))
        restore = self.link("graphical.target.wants", "fan-control-kde-restore.service")
        curve = self.link("multi-user.target.wants", "fan-control-kde-curve.service")
        self.assertEqual(self.h.cmd_migrate(), 0)
        state = self.h.state_load()
        self.assertTrue(state["restore_at_boot"])
        self.assertEqual(state["speeds"], {"hwmon:nct6799:pwm2": "100"})
        self.assertFalse(os.path.lexists(restore))
        self.assertFalse(os.path.lexists(curve))
        self.assertIn(["systemctl", "enable", self.h.DAEMON_UNIT], self.commands)

    def test_restore_stays_off_if_it_was_off(self):
        Path(self.h.STATE).parent.mkdir(parents=True)
        Path(self.h.STATE).write_text(json.dumps({"hwmon:nct6799:pwm2": "100"}))
        self.h.cmd_migrate()
        self.assertFalse(self.h.state_load()["restore_at_boot"])

    def test_a_fresh_install_puts_speeds_back(self):
        self.h.cmd_migrate()
        self.assertTrue(self.h.state_load()["restore_at_boot"])

    def test_it_is_safe_to_run_twice(self):
        self.h.cmd_migrate()
        first = Path(self.h.STATE).read_text()
        self.h.cmd_migrate()
        self.assertEqual(first, Path(self.h.STATE).read_text())

    def test_a_service_switched_off_stays_off(self):
        self.h.write_json(self.h.STATE, {"version": 2, "restore_at_boot": True,
                                         "service": False, "speeds": {}})
        self.h.cmd_migrate()
        self.assertNotIn(["systemctl", "enable", self.h.DAEMON_UNIT], self.commands)


class LegacyIds(FakeMachine):
    def test_a_graphics_card_address_is_not_a_legacy_id(self):
        self.state({"gpu:0000:0f:00.0": "60"})
        self.h.migrate_state(self.h.discover())
        self.assertEqual(self.h.state_load()["speeds"], {"gpu:0000:0f:00.0": "60"})

    def test_a_1x_id_is_mapped(self):
        self.state({"mb:nct6799": "70"})
        self.h.migrate_state(self.h.discover())
        speeds = self.h.state_load()["speeds"]
        self.assertEqual(speeds, {"hwmon:nct6799:pwm1": "70", "hwmon:nct6799:pwm2": "70"})


if __name__ == "__main__":
    unittest.main()
