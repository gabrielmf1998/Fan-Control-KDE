"""The tray icons: menu, tooltip, animation loop and notifications.

There can be more than one. An icon is either pinned to a single fan or set to
"all", and a machine with a CPU header and a graphics card is usually clearer as
two icons than as one icon arguing with itself about which of them to show.

Everything shared - the privileged helper, the update check, the settings
window, the animation clock and the notifications - lives once, in FanTray. An
icon owns only what is genuinely its own: where it points, what angle its rotor
is at, and what it last said.
"""

from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from . import __version__, autostart, icons, settings as settings_ui, system, updates
from .config import (
    APP_NAME,
    BADGE_SOURCES,
    COLOR_MODES,
    DYNAMIC_COLOR_MODES,
    ICON_APPEARANCE_KEYS,
    MODE_COLORS,
    IconView,
    dominant_mode,
    resolve_state,
)

MODE_TEXT = {
    "auto": "firmware",
    "manual": "set by hand",
    "curve": "fan curve",
    "full": "uncontrolled",
    "hwcurve": "firmware curve",
}


def fmt_device(dev: dict, name: str, mode: str, show_detail: bool) -> str:
    percent = dev.get("percent")
    head = f"{name}   {percent}%" if percent is not None else name
    if not show_detail:
        return head
    bits = []
    rpms = [r for r in (dev.get("rpms") or []) if r]
    if rpms:
        bits.append(" / ".join(f"{r} rpm" for r in rpms))
    if dev.get("temp") is not None:
        bits.append(f"{dev['temp']:.0f} °C")
    bits.append(MODE_TEXT.get(mode, mode))
    return head + "   ·   " + "   ·   ".join(bits)


class SpeedMenu:
    """A submenu of speeds for one fan.

    No checkmarks on the levels: Qt's DBusMenu exporter propagates a tick to the
    panel but not an untick, so plasmashell accumulates them and several entries
    end up looking selected at once. The submenu title carries the current value
    instead, and setTitle triggers a layout update the panel always honours.
    """

    def __init__(self, tray, parent_menu: QMenu, dev: dict, curve_on: bool,
                 title: str) -> None:
        self.tray = tray
        self.dev_id = dev["id"]
        self.menu = parent_menu.addMenu(title)
        percent = dev.get("percent")

        step = int(tray.cfg.get("nudge_step", 5))
        lo = int((dev.get("range") or [0, 100])[0])
        hi = int((dev.get("range") or [0, 100])[1])
        current = percent if percent is not None else lo

        up = QAction(f"Increase {step}%", self.menu)
        up.triggered.connect(
            lambda: tray.set_speed(self.dev_id, str(min(hi, current + step))))
        self.menu.addAction(up)
        down = QAction(f"Decrease {step}%", self.menu)
        down.triggered.connect(
            lambda: tray.set_speed(self.dev_id, str(max(lo, current - step))))
        self.menu.addAction(down)
        self.menu.addSeparator()

        auto = QAction("Auto — hand it back to the firmware", self.menu)
        auto.triggered.connect(lambda: tray.set_speed(self.dev_id, "auto"))
        self.menu.addAction(auto)
        full = QAction("Full speed", self.menu)
        full.triggered.connect(lambda: tray.set_speed(self.dev_id, "full"))
        self.menu.addAction(full)

        curve = QAction("Run its fan curve", self.menu, checkable=True)
        curve.setChecked(curve_on)
        curve.triggered.connect(
            lambda checked: tray.toggle_curve(self.dev_id, checked))
        self.menu.addAction(curve)
        edit = QAction("Edit the curve…", self.menu)
        edit.triggered.connect(lambda: tray.open_settings(tab=3,
                                                          device=self.dev_id))
        self.menu.addAction(edit)
        self.menu.addSeparator()

        for value in tray.cfg.get("menu_levels") or []:
            value = int(value)
            if value < lo or value > hi:
                continue
            action = QAction(f"{value}%", self.menu)
            action.triggered.connect(
                lambda _c=False, v=value: tray.set_speed(self.dev_id, str(v)))
            self.menu.addAction(action)

        self.menu.addSeparator()
        hide = QAction("Hide this fan", self.menu)
        hide.setToolTip("Leave it out of the menu, the tooltip and the icon. "
                        "The Fans tab brings it back.")
        hide.triggered.connect(lambda: tray.hide_device(self.dev_id))
        self.menu.addAction(hide)


class FanIcon(QObject):
    """One tray icon, pointed either at everything or at a single fan."""

    def __init__(self, manager, scope: str, parent=None) -> None:
        super().__init__(parent)
        self.manager = manager
        self.cfg = manager.cfg
        self.scope = scope or "all"
        # Everything this icon draws itself with is read through here, so it
        # never has to know whether it has an appearance of its own.
        self.look = IconView(self.cfg, self.scope)

        self.state = "error"
        self.mode = "auto"
        self.phase = 0.0
        self.angle = 0.0
        self.factor = 0.0
        self.deg_per_sec = 0.0
        self.max_step = 360.0
        self.alive = False
        self._ceilings: dict[str, float] = {}
        self._keep: list = []

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(icons.app_icon())
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._activated)

        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.rebuild_menu)
        self.tray.setContextMenu(self.menu)
        self.rebuild_menu()

    # ------------------------------------------------------------- lifetime
    def show(self) -> None:
        self.tray.show()

    def dispose(self) -> None:
        self.tray.hide()
        self.menu.clear()
        self.tray.setContextMenu(None)
        self.deleteLater()

    # ---------------------------------------------------------------- scope
    @property
    def pinned(self) -> bool:
        return self.scope != "all"

    def devices(self, snapshot) -> list[dict]:
        return snapshot.scope(self.scope)

    def title(self, snapshot) -> str:
        if not self.pinned:
            return APP_NAME
        dev = snapshot.device(self.scope)
        if not dev:
            return f"{APP_NAME} — that fan is gone"
        names = self.cfg.get("device_names") or {}
        return names.get(dev["id"], dev["label"])

    # ------------------------------------------------------------ animation
    def resync(self, snapshot) -> None:
        """Recompute what this icon shows and how fast its rotor should turn."""
        warn = float(self.cfg.get("warn_temp", 75))
        critical = float(self.cfg.get("critical_temp", 90))
        devices = self.devices(snapshot)
        hottest = snapshot.hottest_of(self.scope)

        self.factor = snapshot.spin_factor(self._ceilings, self.scope)
        self.state = resolve_state(devices, hottest, warn, critical)
        self.mode = dominant_mode([dict(d, mode=snapshot.mode_of(d))
                                   for d in devices])

        animation = self.look.animation_for(self.state)
        dynamic = self.look.get("color_mode") in DYNAMIC_COLOR_MODES
        moving = animation != "none" and (
            self.factor > 0.0 or self.look.get("animate_when_idle", True)
            or animation not in icons.ROTATING)
        self.alive = bool(dynamic or moving)

        source = self.look.get("spin_source", "rpm")
        if source == "fixed":
            drive = 1.0
        elif source == "percent":
            drive = snapshot.top_percent_of(self.scope) / 100.0
        else:
            drive = self.factor
        lo = float(self.look.get("spin_min_dps", 36.0))
        hi = float(self.look.get("spin_max_dps", 444.0))
        speed = float(self.look.get("animation_speed", 1.0))
        if drive > 0:
            self.deg_per_sec = (lo + drive * (hi - lo)) * speed
        elif animation in icons.ROTATING and self.look.get("animate_when_idle", True):
            # Nothing is turning, but the user asked for movement anyway: give
            # it the slow end of the range rather than freezing the icon.
            self.deg_per_sec = lo * speed
        else:
            self.deg_per_sec = 0.0

        self.max_step = (icons.max_step_degrees(self.look.get("icon_style", "classic"))
                         if self.look.get("smooth_rotation", True) else 360.0)

        if not self.alive:
            self.angle = 0.0
        self.update_tooltip(snapshot)
        self.refresh(snapshot)

    def tick(self, delta: float, snapshot) -> None:
        if not self.alive:
            return
        self.phase += delta * float(self.look.get("animation_speed", 1.0))
        # Whatever the clock says, never turn far enough in one frame to strobe.
        self.angle = (self.angle
                      + min(self.deg_per_sec * delta, self.max_step)) % 360.0
        self.refresh(snapshot)

    # ---------------------------------------------------------------- icon
    def _context(self, snapshot) -> icons.RenderCtx:
        look = self.look
        text = ""
        if look.get("show_badge"):
            source = look.get("badge_source", "percent")
            if source == "percent":
                text = str(snapshot.top_percent_of(self.scope))
            elif source == "rpm":
                rpms = snapshot.rpms_of(self.scope)
                top = max(rpms) if rpms else 0
                text = f"{top // 1000}k" if top >= 10000 else str(top)
            elif source == "temp":
                hottest = snapshot.hottest_of(self.scope)
                text = f"{hottest:.0f}" if hottest is not None else "—"
            else:
                text = str(len(snapshot.rpms_of(self.scope)))
        return icons.RenderCtx(
            factor=self.factor,
            percent=snapshot.top_percent_of(self.scope),
            temp=snapshot.hottest_of(self.scope),
            warn=float(self.cfg.get("warn_temp", 75)),
            critical=float(self.cfg.get("critical_temp", 90)),
            thickness=float(look.get("icon_thickness", 1.0)),
            padding=float(look.get("icon_padding", 0.02)),
            scale=float(look.get("icon_scale", 1.0)),
            badge=bool(look.get("show_badge")),
            badge_text=text,
            badge_style=look.get("badge_style", "circle"),
            badge_position=look.get("badge_position", "br"),
            badge_color=look.get("badge_color", "#0d1117"),
            badge_text_color=look.get("badge_text_color", "#ffffff"),
            mode_dot=MODE_COLORS.get(self.mode, "") if look.get("mode_dot") else "",
            prism=look.get("color_mode") == "prism",
            text=text or str(snapshot.top_percent_of(self.scope)),
        )

    def _color(self, snapshot) -> str:
        mode = self.look.get("color_mode", "state")
        if mode == "mono":
            return self.look.get("mono_color", "#c9d1d9")
        if mode == "theme":
            return QApplication.palette().windowText().color().name()
        if mode == "rainbow":
            return icons.hue_color(self.phase * 0.35).name()
        if mode == "spinbow":
            return icons.hue_color(self.angle / 360.0).name()
        if mode == "prism":
            return self.look.color_for(self.state)
        if mode == "heat":
            hottest = snapshot.hottest_of(self.scope)
            if hottest is None:
                return self.look.color_for(self.state)
            critical = float(self.cfg.get("critical_temp", 90))
            span = max(1.0, critical - 30.0)
            t = max(0.0, min(1.0, (hottest - 30.0) / span))
            return icons.hue_color(0.55 * (1.0 - t)).name()
        if mode == "velocity":
            return icons.hue_color(0.58 * (1.0 - self.factor)).name()
        return self.look.color_for(self.state)

    def refresh(self, snapshot) -> None:
        """One pixmap, not four.

        Every frame of this crosses D-Bus and is decoded by the panel on the
        other side. Handing it a whole QIcon of sizes meant four images per
        frame for a cell that draws one of them, and the panel answered by
        quietly coalescing frames.
        """
        size = int(self.look.get("icon_size", 48))
        self.tray.setIcon(QIcon(icons.render_pixmap(
            size, self.look.get("icon_style", "classic"), self._color(snapshot),
            self.look.animation_for(self.state), self.phase, self.angle,
            self._context(snapshot))))

    def update_tooltip(self, snapshot) -> None:
        if not snapshot.ok:
            self.tray.setToolTip(f"{APP_NAME} — the helper is not answering")
            return
        names = self.cfg.get("device_names") or {}
        devices = self.devices(snapshot)
        if not devices:
            self.tray.setToolTip(
                f"{APP_NAME} — that fan is no longer there" if self.pinned
                else f"{APP_NAME} — no fan controller found")
            return

        lines = [self.title(snapshot)]
        for dev in devices:
            line = fmt_device(dev, names.get(dev["id"], dev["label"]),
                              snapshot.mode_of(dev), True)
            # A pinned icon's title is already the fan's name; repeating it on
            # the line under it is the sort of noise this whole feature exists
            # to get rid of.
            if self.pinned:
                line = line.split("   ", 1)[-1] if "   " in line else line
            lines.append(line)
        if self.cfg.get("tooltip_details", True):
            hottest = snapshot.hottest
            if hottest is not None and not self.pinned:
                lines.append(f"hottest sensor   {hottest:.0f} °C")
        self.tray.setToolTip("\n".join(lines))

    # ---------------------------------------------------------------- menu
    def rebuild_menu(self) -> None:
        """Rebuilt every time it is about to be shown.

        Cheap, and it sidesteps the DBusMenu tick that never gets cleared: every
        action is new, so nothing stale can accumulate in the panel's copy.
        """
        manager = self.manager
        snapshot = manager.monitor.snapshot
        names = self.cfg.get("device_names") or {}
        menu = self.menu
        menu.clear()
        self._keep = []                    # Qt does not own these; we must

        devices = self.devices(snapshot)
        if not snapshot.ok:
            self._disabled(menu, "The helper is not answering")
        elif not devices:
            if self.pinned:
                self._disabled(menu, "The fan this icon follows is gone")
            else:
                self._disabled(menu, "No fan controller found")
                self._disabled(menu, "  try  sudo sensors-detect")

        # The reading goes in the submenu's own title rather than on a disabled
        # line above it: a machine with six headers would otherwise spend twelve
        # menu entries saying everything twice.
        for dev in devices:
            name = names.get(dev["id"], dev["label"])
            mode = snapshot.mode_of(dev)
            title = fmt_device(dev, name, mode,
                               self.cfg.get("menu_show_rpm", True))
            if dev.get("control"):
                self._keep.append(SpeedMenu(
                    manager, menu, dev,
                    snapshot.curve_for(dev["id"]).get("enabled", False), title))
            else:
                self._disabled(menu, title)
                self._disabled(menu, "  " + (dev.get("reason") or "monitoring only"))
        if devices:
            menu.addSeparator()

        follows = menu.addMenu("This icon follows   %s" % (
            "everything" if not self.pinned else self.title(snapshot)))
        group = QActionGroup(follows)
        group.setExclusive(True)
        for key, label in [("all", "Everything")] + [
                (d["id"], names.get(d["id"], d["label"]))
                for d in snapshot.devices]:
            action = QAction(label, follows, checkable=True)
            action.setChecked(key == self.scope)
            action.triggered.connect(
                lambda _c=False, k=key: manager.set_icon_scope(self, k))
            group.addAction(action)
            follows.addAction(action)
        self._keep.append(group)
        add = QAction("Add another icon for…", follows)
        follows.addSeparator()
        follows.addAction(add)
        add.triggered.connect(lambda: manager.open_settings(tab=2))

        if self.cfg.get("menu_show_sensors", True) and snapshot.sensors:
            temps = menu.addMenu("Temperatures")
            for sensor in snapshot.sensors:
                mark = "" if sensor.get("trusted") else "   (unpopulated?)"
                self._disabled(
                    temps, f"{sensor['label']}   {sensor['temp']:.0f} °C{mark}")

        look = menu.addMenu("Appearance" + ("   (this icon only)"
                                           if self.look.has_own_look else ""))
        own = QAction("Give this icon a look of its own", look, checkable=True)
        own.setChecked(self.look.has_own_look)
        own.setToolTip("Ticked, everything below changes only this icon. "
                       "Unticked, it follows the shared appearance again.")
        own.triggered.connect(
            lambda checked: manager.set_own_look(self, checked))
        look.addAction(own)
        look.addSeparator()
        self._quick(look, "Icon", icons.ICON_STYLES,
                    self.look.get("icon_style"), "icon_style")
        self._quick(look, "Colour", COLOR_MODES,
                    self.look.get("color_mode"), "color_mode")
        self._quick(look, "Motion", icons.ANIMATIONS,
                    self.look.animation_for(self.state), "_animation_all")
        self._quick(look, "Frame rate",
                    [(str(v), f"{v} fps") for v in (12, 18, 22, 30, 45, 60)],
                    str(self.cfg.get("animation_fps")), "animation_fps")
        self._quick(look, "Badge", [("", "None")] + list(BADGE_SOURCES),
                    self.look.get("badge_source") if self.look.get("show_badge")
                    else "", "_badge")

        settings_action = QAction("Settings…", menu)
        settings_action.triggered.connect(lambda: manager.open_settings())
        menu.addAction(settings_action)
        menu.addSeparator()

        start = QAction("Start with the system", menu, checkable=True)
        start.setChecked(autostart.is_enabled())
        start.triggered.connect(manager.toggle_autostart)
        menu.addAction(start)

        units = snapshot.units
        if units.get("boot", "") not in ("", "not-found"):
            boot = QAction("Keep speeds after a reboot", menu, checkable=True)
            boot.setChecked(units.get("boot") == "enabled")
            boot.triggered.connect(
                lambda checked: manager.priv.run(
                    ["boot", "on" if checked else "off"]))
            menu.addAction(boot)
        if units.get("curve", "") not in ("", "not-found"):
            daemon = QAction("Run fan curves", menu, checkable=True)
            daemon.setChecked(units.get("curve_active") == "active")
            daemon.triggered.connect(
                lambda checked: manager.priv.run(
                    ["daemon", "on" if checked else "off"]))
            menu.addAction(daemon)

        menu.addSeparator()
        check = QAction("Check for updates", menu)
        check.setEnabled(not manager.updates.busy)
        check.triggered.connect(manager.check_updates)
        menu.addAction(check)
        self._disabled(menu, f"{APP_NAME} KDE {__version__}")

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_action)

    @staticmethod
    def _disabled(menu: QMenu, text: str) -> None:
        action = QAction(text, menu)
        action.setEnabled(False)
        menu.addAction(action)

    def _quick(self, parent: QMenu, title: str, items, current, key: str) -> None:
        """A quick-pick submenu whose title carries the current value."""
        label = dict(items).get(current, "")
        sub = parent.addMenu(f"{title}   {label}" if label else title)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for item_key, item_label in items:
            action = QAction(item_label, sub, checkable=True)
            action.setChecked(item_key == current)
            action.triggered.connect(
                lambda _c=False, k=item_key: self.manager.quick_set(key, k, self))
            group.addAction(action)
            sub.addAction(action)
        self._keep.append(group)

    def _activated(self, reason) -> None:
        if reason != QSystemTrayIcon.Trigger:
            return
        action = self.cfg.get("click_action", "menu")
        if action == "settings":
            self.manager.open_settings()
        elif action == "auto":
            for dev in self.devices(self.manager.monitor.snapshot):
                if dev.get("control"):
                    self.manager.priv.run(["set", dev["id"], "auto"])
        elif action == "menu":
            self.rebuild_menu()
            self.menu.popup(self.tray.geometry().center())


class FanTray(QObject):
    """Owns the icons and everything they share."""

    def __init__(self, cfg, monitor, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.monitor = monitor
        self.priv = system.Privileged(self)
        self.updates = updates.UpdateChecker(self)
        self.dialog: settings_ui.SettingsDialog | None = None

        self.icons: list[FanIcon] = []
        self._last_state = ""
        self._last_spinning: dict[str, bool] = {}
        self._last_curve: dict[str, int] = {}
        self._tray_timer: QTimer | None = None
        self._tray_waited = 0
        self._shown = False

        # Motion is driven by the clock, not by the tick count. A tick-based
        # animation runs slow whenever a frame is late and stalls whenever one
        # is dropped, and the panel drops plenty: the icon crosses D-Bus on
        # every frame and plasmashell decodes it on the other side.
        self._clock = QElapsedTimer()
        self._clock.start()
        self._last_frame = 0
        self._running = False
        self.anim = QTimer(self)
        # Qt coarsens any interval of 20 ms or more by default and lets the
        # kernel coalesce it with other timers, which is exactly the irregular
        # stutter an animation must not have.
        self.anim.setTimerType(Qt.PreciseTimer)
        self.anim.timeout.connect(self._tick)

        monitor.changed.connect(self._on_snapshot)
        self.priv.result.connect(self._on_priv)
        self.updates.checked.connect(self._on_update_check)

        self.rebuild_icons()

    # ------------------------------------------------------------- lifetime
    @property
    def interval_ms(self) -> int:
        return int(round(1000.0 / max(5, int(self.cfg.get("animation_fps", 22)))))

    def scopes(self) -> list[str]:
        """What the config asks for, made safe: never empty, never duplicated."""
        wanted = self.cfg.get("tray_icons") or ["all"]
        seen, out = set(), []
        for scope in wanted:
            scope = str(scope)
            if scope and scope not in seen:
                seen.add(scope)
                out.append(scope)
        return out or ["all"]

    def rebuild_icons(self) -> None:
        wanted = self.scopes()
        if [i.scope for i in self.icons] == wanted:
            return
        for icon in self.icons:
            icon.dispose()
        self.icons = [FanIcon(self, scope, self) for scope in wanted]
        if self._shown:
            for icon in self.icons:
                icon.show()
        self._on_snapshot(self.monitor.snapshot)

    def show(self) -> None:
        self._shown = True
        for icon in self.icons:
            icon.show()

    def wait_for_tray(self) -> None:
        """Keep trying until somewhere to put the icons turns up.

        Qt answers isSystemTrayAvailable() from whatever is on the session bus
        at that instant, and an app started from autostart routinely wins the
        race against the panel registering its watcher. Refusing to run is the
        wrong answer; wait for it.
        """
        self._tray_waited = 0
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self._tray_timer = QTimer(self)
        self._tray_timer.timeout.connect(self._poll_for_tray)
        self._tray_timer.start(1000)

    def _poll_for_tray(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_timer.stop()
            QApplication.instance().setQuitOnLastWindowClosed(False)
            self.show()
            self.monitor.poll()
            return
        self._tray_waited += 1
        if self._tray_waited == 25:
            QMessageBox.warning(
                None, APP_NAME,
                "There is no system tray on this desktop yet, so the icon has "
                "nowhere to go. It will appear on its own if a panel turns up.")

    # ------------------------------------------------------------ animation
    def apply_settings(self) -> None:
        self.monitor.retime()
        self.rebuild_icons()
        self._on_snapshot(self.monitor.snapshot)

    def _retime_animation(self) -> None:
        alive = any(icon.alive for icon in self.icons)
        if alive:
            # Only ever started when it is not already running. Calling start()
            # on a live QTimer throws away the pending timeout, and this runs on
            # every poll - which cost exactly one dropped frame every 2.5
            # seconds, forever.
            if not self._running:
                self._last_frame = self._clock.elapsed()
                self.anim.start(self.interval_ms)
                self._running = True
            elif self.anim.interval() != self.interval_ms:
                self.anim.setInterval(self.interval_ms)
        elif self._running:
            self.anim.stop()
            self._running = False

    def _tick(self) -> None:
        now = self._clock.elapsed()
        # Capped: after a suspend, or a session frozen behind a modal password
        # prompt, the gap is enormous, and neither the phase nor the angle
        # should leap across it.
        delta = min(max(now - self._last_frame, 0), 250) / 1000.0
        self._last_frame = now
        snapshot = self.monitor.snapshot
        for icon in self.icons:
            icon.tick(delta, snapshot)

    # ------------------------------------------------------------- polling
    def _on_snapshot(self, snapshot) -> None:
        for icon in self.icons:
            icon.resync(snapshot)
        self._retime_animation()
        self._notify_changes(snapshot)

    def _notify_changes(self, snapshot) -> None:
        """Once for the machine, not once per icon: two icons watching the same
        overheating CPU should not say so twice."""
        if not self.cfg.get("notifications_enabled", True):
            return
        warn = float(self.cfg.get("warn_temp", 75))
        critical = float(self.cfg.get("critical_temp", 90))
        state = resolve_state(snapshot.devices, snapshot.hottest, warn, critical)
        if state != self._last_state:
            hottest = snapshot.hottest
            if state == "critical" and self.cfg.get("notify_on_critical", True):
                self.notify("Critically hot",
                            f"The hottest sensor reads {hottest:.0f} °C."
                            if hottest is not None else "Something is very hot.",
                            QSystemTrayIcon.Critical)
            elif state == "warning" and self.cfg.get("notify_on_warning", True):
                self.notify("Running hot",
                            f"The hottest sensor reads {hottest:.0f} °C."
                            if hottest is not None else "Something is hot.",
                            QSystemTrayIcon.Warning)
            self._last_state = state

        names = self.cfg.get("device_names") or {}
        for dev in snapshot.devices:
            rpms = [r for r in (dev.get("rpms") or []) if r]
            turning = bool(rpms)
            was = self._last_spinning.get(dev["id"])
            if (was and not turning and self.cfg.get("notify_on_stall", True)
                    and dev.get("percent")):
                self.notify(
                    "A fan stopped",
                    f"{names.get(dev['id'], dev['label'])} reads 0 rpm while "
                    f"still being asked for {dev['percent']}%.",
                    QSystemTrayIcon.Warning)
            self._last_spinning[dev["id"]] = turning

        if self.cfg.get("notify_on_curve", False):
            for dev_id, info in (snapshot.runtime.get("fans") or {}).items():
                percent = info.get("percent")
                if percent is None or self._last_curve.get(dev_id) == percent:
                    continue
                self._last_curve[dev_id] = percent
                self.notify("Fan curve",
                            f"{info.get('label', dev_id)} → {percent}% "
                            f"({info.get('temp', '?')} °C)")

    def notify(self, title: str, message: str,
               kind=QSystemTrayIcon.Information, ms: int = 5000) -> None:
        if not self.cfg.get("notifications_enabled", True) or not self.icons:
            return
        self.icons[0].tray.showMessage(title, message, kind, ms)

    # ------------------------------------------------------------- actions
    def set_icon_scope(self, icon: FanIcon, scope: str) -> None:
        scopes = self.scopes()
        try:
            index = self.icons.index(icon)
        except ValueError:
            return
        if index >= len(scopes) or scopes[index] == scope:
            return
        if scope in scopes:                 # already shown by another icon
            self.notify(APP_NAME, "Another icon is already following that fan.")
            return
        scopes[index] = scope
        self.cfg["tray_icons"] = scopes
        self.cfg.save()
        self.rebuild_icons()
        if self.dialog is not None:
            self.dialog.load_from_config()

    def hide_device(self, dev_id: str) -> None:
        hidden = list(self.cfg.get("device_hidden") or [])
        if dev_id in hidden:
            return
        hidden.append(dev_id)
        self.cfg["device_hidden"] = hidden
        # An icon pinned to a fan that has just been hidden has nothing to show,
        # so it goes back to speaking for the machine rather than going blank.
        scopes = ["all" if s == dev_id else s for s in self.scopes()]
        self.cfg["tray_icons"] = scopes
        self.cfg.save()
        self.monitor.snapshot.hidden = set(hidden)
        self.rebuild_icons()
        self.monitor.poll()
        if self.dialog is not None:
            self.dialog.load_from_config()
        self.notify(APP_NAME, "Hidden. The Fans tab in Settings brings it back.")

    def set_own_look(self, icon: FanIcon, on: bool) -> None:
        """Give one icon its own appearance, or hand it back to the shared one.

        Seeded from whatever is shared right now, so ticking it changes nothing
        visible - it only decides where the next change lands.
        """
        self.cfg.set_icon_look(icon.scope,
                               self.cfg.shared_look() if on else None)
        self.cfg.save()
        self.apply_settings()
        if self.dialog is not None:
            self.dialog.load_from_config()

    def quick_set(self, key: str, value, icon: FanIcon | None = None) -> None:
        """Applied to the icon that asked, if it has an appearance of its own.

        Picking a shape from an icon's own menu and having every other icon
        change with it would make per-icon looks useless the moment you touched
        the menu.
        """
        # A pinned icon's own menu edits that icon, the same way naming it in
        # the settings window does. The whole-machine icon is the machine, so
        # its menu edits the shared look unless it has been given one of its own.
        own = icon is not None and (icon.pinned or icon.look.has_own_look)
        if own and self.cfg.icon_look(icon.scope) is None:
            self.cfg.set_icon_look(icon.scope, self.cfg.shared_look())
        look = dict(self.cfg.icon_look(icon.scope)) if own else None

        def put(k, v):
            if look is not None and k in ICON_APPEARANCE_KEYS:
                look[k] = v
            else:
                self.cfg[k] = v

        if key == "_animation_all":
            base = (look or {}).get("animations") or self.cfg["animations"]
            put("animations", {state: value for state in base})
        elif key == "_badge":
            put("show_badge", bool(value))
            if value:
                put("badge_source", value)
        elif key == "animation_fps":
            # One timer drives every icon, so the frame rate is always shared.
            self.cfg[key] = int(value)
        else:
            put(key, value)

        if look is not None:
            self.cfg.set_icon_look(icon.scope, look)
        self.cfg.save()
        self.apply_settings()
        if self.dialog is not None:
            self.dialog.load_from_config()

    def toggle_autostart(self, checked: bool) -> None:
        if autostart.set_enabled(checked):
            self.cfg["start_with_system"] = checked
            self.cfg.save()
            self.notify(APP_NAME, "This tray will start when you log in."
                        if checked else "It will not start on its own any more.")
        else:
            self.notify(APP_NAME, "Could not write the autostart entry.",
                        QSystemTrayIcon.Warning)

    def set_speed(self, dev_id: str, value: str) -> None:
        if value == "0" and self.cfg.get("confirm_zero", True):
            answer = QMessageBox.question(
                None, "Stop this fan?",
                "Setting a fan to 0% stops it. On a CPU header that is only "
                "safe if something else is moving air over the cooler.\n\n"
                "Stop it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self.priv.run(["set", dev_id, value])

    def toggle_curve(self, dev_id: str, on: bool) -> None:
        snapshot = self.monitor.snapshot
        if on and not snapshot.curve_for(dev_id):
            self.notify(APP_NAME,
                        "There is no curve for this fan yet — draw one in "
                        "Settings, on the Curves tab.")
            self.open_settings(tab=3, device=dev_id)
            return
        self.priv.run(["curve", "enable", dev_id, "on" if on else "off"])
        if on and snapshot.units.get("curve_active") != "active":
            self.priv.run(["daemon", "on"])

    def _on_priv(self, ok: bool, message: str) -> None:
        if ok:
            # A calibration answers with its whole measurement as JSON, which
            # the settings window renders; a notification bubble full of it
            # would be nonsense.
            if (message and self.cfg.get("notify_on_change", True)
                    and not message.lstrip().startswith("{")):
                self.notify(APP_NAME, message)
        elif message:
            self.notify(APP_NAME, message, QSystemTrayIcon.Warning)
        self.monitor.poll()

    # ------------------------------------------------------------- updates
    def check_updates(self) -> None:
        if self.updates.check(self.cfg.get("update_channel", "both")):
            self.notify(APP_NAME, "Looking for a newer release…", ms=2500)

    def _on_update_check(self, ok: bool, message: str) -> None:
        if not ok:
            self.notify(APP_NAME, message, QSystemTrayIcon.Warning)
            return
        if self.updates.available:
            self.notify(APP_NAME,
                        f"{message}\nOpen Settings → Updates to install it, or "
                        f"run:\n{updates.INSTALL_COMMAND}",
                        QSystemTrayIcon.Information, 9000)
        else:
            self.notify(APP_NAME, message)

    # ------------------------------------------------------------ settings
    def open_settings(self, tab: int | None = None, device: str = "") -> None:
        if self.dialog is None:
            self.dialog = settings_ui.SettingsDialog(
                self.cfg, self.monitor, self.priv, self.updates)
            self.dialog.applied.connect(self.apply_settings)
            self.dialog.finished.connect(self._settings_closed)
        if device:
            index = self.dialog.curve_device.findData(device)
            if index >= 0:
                self.dialog.curve_device.setCurrentIndex(index)
        if tab is not None:
            self.dialog.tabs.setCurrentIndex(tab)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def _settings_closed(self, _result) -> None:
        if self.dialog is not None:
            self.dialog.deleteLater()
            self.dialog = None
