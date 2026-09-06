"""What the machine's fans are doing right now, polled without blocking the GUI.

A synchronous helper call froze the event loop for about a quarter of a second
on every poll, which the animation showed as a stutter. Everything here goes
through QProcess and arrives as a signal.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from . import system


class Snapshot:
    """One reply from `fan-control-helper status`, in a shape the GUI can use."""

    def __init__(self, raw: dict | None = None, hidden=()) -> None:
        raw = raw or {}
        self.raw = raw
        # Everything the helper found, including what the user has hidden. The
        # Fans tab needs this one; nothing else should.
        self.all_devices: list[dict] = raw.get("devices") or []
        self.hidden = set(hidden or ())
        self.sensors: list[dict] = raw.get("sensors") or []
        self.curves: dict = raw.get("curves") or {}
        self.runtime: dict = raw.get("runtime") or {}
        self.saved: dict = raw.get("saved") or {}
        self.units: dict = raw.get("units") or {}
        self.helper_version: str = raw.get("version", "")

    # -- convenience -------------------------------------------------------
    @property
    def devices(self) -> list[dict]:
        """Filtered on access, not once in the constructor: hiding a fan has to
        take effect on the spot, not at whatever the next poll happens to be."""
        return [d for d in self.all_devices if d["id"] not in self.hidden]

    @property
    def ok(self) -> bool:
        return bool(self.raw)

    @property
    def controllable(self) -> list[dict]:
        return [d for d in self.devices if d.get("control")]

    def device(self, dev_id: str) -> dict | None:
        """Looked up among everything, hidden included: an icon pinned to a fan
        that was later hidden should say so rather than silently go blank."""
        return next((d for d in self.all_devices if d["id"] == dev_id), None)

    def sensor(self, sid: str) -> dict | None:
        return next((s for s in self.sensors if s["id"] == sid), None)

    def curve_for(self, dev_id: str) -> dict:
        return (self.curves.get("curves") or {}).get(dev_id) or {}

    def curve_active(self, dev_id: str) -> bool:
        """A curve counts as running only when the daemon is up as well: a
        switched-on curve and a stopped service means nothing is happening."""
        if self.units.get("curve_active") != "active":
            return False
        return bool(self.curve_for(dev_id).get("enabled"))

    def runtime_for(self, dev_id: str) -> dict:
        return (self.runtime.get("fans") or {}).get(dev_id) or {}

    def mode_of(self, dev: dict) -> str:
        if self.curve_active(dev["id"]):
            return "curve"
        mode = dev.get("mode") or "auto"
        return "curve" if mode == "hwcurve" else mode

    @property
    def hottest(self) -> float | None:
        """The hottest sensor worth believing.

        Super I/O chips wire more thermistors than boards populate, and the
        empty ones read as 15 °C or 102 °C rather than as absent - so an
        untrusted sensor must never be what makes the icon go red.
        """
        temps = [s["temp"] for s in self.sensors
                 if s.get("trusted") and s.get("temp") is not None]
        if not temps:
            temps = [d["temp"] for d in self.devices if d.get("temp") is not None]
        return max(temps) if temps else None

    @property
    def rpms(self) -> list[int]:
        return [r for d in self.devices for r in (d.get("rpms") or []) if r]

    def scope(self, only: str = "") -> list[dict]:
        """The devices one icon speaks for: all of the visible ones, or the
        single fan it was pinned to."""
        if not only or only == "all":
            return self.devices
        dev = self.device(only)
        return [dev] if dev else []

    def spin_factor(self, ceilings: dict[str, float], only: str = "") -> float:
        """0.0 when nothing turns, 1.0 at the fastest speed ever seen here.

        Driven by measured rpm rather than by the duty asked for: motherboard
        fans sit at ~500 rpm even at 0% duty, so by percentage they would look
        stopped while plainly still turning. `ceilings` is the caller's running
        record of the top speed per device, and is updated in place.
        """
        devices = self.scope(only)
        vals = []
        for dev in devices:
            group = [r for r in (dev.get("rpms") or []) if r]
            if not group:
                continue
            top = max(group)
            key = dev["id"]
            if top > ceilings.get(key, 1.0):
                ceilings[key] = float(top)
            vals.append(top / ceilings.get(key, 1.0))
        if vals:
            return max(0.0, min(1.0, sum(vals) / len(vals)))
        # No tachometer anywhere: fall back to what was asked for, so the icon
        # still moves on a machine whose fans have no sense wire.
        pcts = [d.get("percent") for d in devices
                if d.get("control") and d.get("percent") is not None]
        return max(0.0, min(1.0, max(pcts) / 100.0)) if pcts else 0.0

    def top_percent_of(self, only: str = "") -> int:
        pcts = [d.get("percent") for d in self.scope(only)
                if d.get("control") and d.get("percent") is not None]
        return max(pcts) if pcts else 0

    @property
    def top_percent(self) -> int:
        return self.top_percent_of()

    def hottest_of(self, only: str = "") -> float | None:
        """For a pinned icon, the temperature that matters is the one beside
        that fan - not the hottest thing in the machine, which may be an NVMe
        on the other side of the board."""
        if not only or only == "all":
            return self.hottest
        dev = self.device(only)
        return (dev or {}).get("temp")

    def rpms_of(self, only: str = "") -> list[int]:
        return [r for d in self.scope(only) for r in (d.get("rpms") or []) if r]

    def fingerprint(self) -> tuple:
        """What has to change before the menu is worth rebuilding."""
        return tuple(
            (d["id"], d.get("label"), d.get("control"),
             d["id"] in self.hidden,
             bool(self.curve_for(d["id"]).get("enabled")))
            for d in self.all_devices
        ) + (self.units.get("curve_active"),)


class Monitor(QObject):
    """Polls the helper and hands out snapshots."""

    changed = Signal(object)        # Snapshot
    devicesChanged = Signal(object)  # Snapshot, only when the set of fans moves

    def __init__(self, cfg, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.snapshot = Snapshot()
        self._fingerprint: tuple | None = None
        self._proc = QProcess(self)
        self._proc.finished.connect(self._ready)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        self._timer.start(max(500, int(self.cfg.get("poll_ms", 2500))))
        self.poll()

    def retime(self) -> None:
        if self._timer.isActive():
            self._timer.start(max(500, int(self.cfg.get("poll_ms", 2500))))

    def shutdown(self) -> None:
        self._timer.stop()
        if self._proc.state() != QProcess.NotRunning:
            self._proc.kill()

    def poll(self) -> None:
        """Skipped while one is still running: nvidia-settings can take seconds
        to answer, and stacking those up would fork a process per tick."""
        if self._proc.state() != QProcess.NotRunning:
            return
        self._proc.start(system.helper_path(), ["status"])

    def _ready(self) -> None:
        raw = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        self.snapshot = Snapshot(data if isinstance(data, dict) else {},
                                 self.cfg.get("device_hidden") or ())
        fingerprint = self.snapshot.fingerprint()
        if fingerprint != self._fingerprint:
            self._fingerprint = fingerprint
            self.devicesChanged.emit(self.snapshot)
        self.changed.emit(self.snapshot)
