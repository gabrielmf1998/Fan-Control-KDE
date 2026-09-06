"""The settings window: everything the tray can do, without touching a terminal."""

from __future__ import annotations

import json

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from . import __version__, autostart, curves, curveeditor, icons, system, updates
from .config import (
    APP_NAME,
    BADGE_SOURCES,
    COLOR_MODES,
    COLOR_PRESETS,
    CONFIG_FILE,
    GITLAB_URL,
    MODE_COLORS,
    PROJECT_URL,
    STATES,
)

PREVIEW_PX = 40
TILE_PX = 40
TILE_W = 88


def _set_data(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    combo.blockSignals(True)
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)


def _scroll(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setWidget(inner)
    return area


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: palette(mid);")
    return label


class ColorButton(QPushButton):
    """A swatch that opens a colour picker."""

    changed = Signal(str)

    def __init__(self, color: str, parent=None) -> None:
        super().__init__(parent)
        self._color = color
        self.setFixedSize(46, 24)
        self.clicked.connect(self._pick)
        self._refresh()

    def color(self) -> str:
        return self._color

    def set_color(self, color: str) -> None:
        self._color = color
        self._refresh()

    def _refresh(self) -> None:
        c = QColor(self._color)
        text = "#000000" if c.lightnessF() > 0.55 else "#ffffff"
        self.setStyleSheet(
            f"background-color:{self._color}; color:{text};"
            "border:1px solid rgba(128,128,128,0.6); border-radius:4px;"
            "font-size:10px; font-family:monospace;")
        self.setText(self._color.lstrip("#").upper())

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Pick a colour")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(self._color)


class StatePreview(QLabel):
    """One animated swatch showing exactly what the tray will look like."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(PREVIEW_PX + 6, PREVIEW_PX + 6)
        self.setAlignment(Qt.AlignCenter)
        self.style_key = "classic"
        self.color = "#3daee9"
        self.animation = "spin"
        self.ctx = icons.RenderCtx()

    def paint(self, phase: float, angle: float) -> None:
        self.setPixmap(icons.render_pixmap(PREVIEW_PX, self.style_key, self.color,
                                           self.animation, phase, angle, self.ctx))


class GalleryTile(QToolButton):
    """One clickable, live-rendered option."""

    def __init__(self, key: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setToolTip(label)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setIconSize(QSize(TILE_PX, TILE_PX))
        self.setFixedWidth(TILE_W)
        font = self.font()
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.0))
        self.setFont(font)
        self.setText(QFontMetrics(font).elidedText(label, Qt.ElideRight, TILE_W - 8))


class Gallery(QWidget):
    """A grid of options you pick by looking at them rather than by name."""

    picked = Signal(str)

    def __init__(self, entries, columns: int, parent=None) -> None:
        super().__init__(parent)
        self.tiles: dict[str, GalleryTile] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        grid = QGridLayout(self)
        grid.setSpacing(2)
        grid.setContentsMargins(0, 0, 0, 0)
        for i, (key, label) in enumerate(entries):
            tile = GalleryTile(key, label)
            tile.clicked.connect(lambda _c=False, k=key: self.picked.emit(k))
            self._group.addButton(tile)
            self.tiles[key] = tile
            grid.addWidget(tile, i // columns, i % columns)

    def current(self) -> str:
        for key, tile in self.tiles.items():
            if tile.isChecked():
                return key
        return next(iter(self.tiles), "")

    def set_current(self, key: str | None) -> None:
        """An exclusive QButtonGroup refuses to let its last checked button go,
        so clearing has to happen with exclusivity off."""
        self._group.setExclusive(False)
        for candidate, tile in self.tiles.items():
            tile.setChecked(candidate == key)
        self._group.setExclusive(True)

    def repaint_tiles(self, render) -> None:
        for key, tile in self.tiles.items():
            tile.setIcon(QIcon(render(key)))


class StateStrip(QWidget):
    """Every state at once, drawn exactly the way the tray draws it."""

    def __init__(self, dialog, parent=None) -> None:
        super().__init__(parent)
        self.dialog = dialog
        self.phase = 0.0
        self.angle = 0.0
        self.setMinimumHeight(78)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        size = 44
        step = self.width() / max(1, len(STATES))
        metrics = QFontMetrics(self.font())
        for i, (key, label) in enumerate(STATES):
            pixmap = self.dialog.render_state(key, size, self.phase, self.angle)
            painter.drawPixmap(int(step * i + step / 2 - size / 2), 4, pixmap)
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(
                QRectF(step * i, size + 8, step, 20),
                Qt.AlignHCenter | Qt.AlignTop,
                metrics.elidedText(label, Qt.ElideRight, int(step) - 4))
        painter.end()


class FanRow(QGroupBox):
    """One fan: what it is doing, and the controls that change it."""

    apply_speed = Signal(str, str)      # device id, value
    calibrate = Signal(str)
    rename = Signal(str, str)

    def __init__(self, dev: dict, name: str, parent=None) -> None:
        super().__init__(parent)
        self.dev_id = dev["id"]
        self.controllable = bool(dev.get("control"))
        self._settling = False

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        self.name_edit = QLineEdit(name)
        self.name_edit.setMaximumWidth(220)
        self.name_edit.setToolTip("What this fan is called in the menu and here.")
        self.name_edit.editingFinished.connect(
            lambda: self.rename.emit(self.dev_id, self.name_edit.text().strip()))
        head.addWidget(self.name_edit)
        self.detail = QLabel(dev.get("detail", ""))
        self.detail.setStyleSheet("color: palette(mid);")
        head.addWidget(self.detail, 1)
        self.reading = QLabel("—")
        self.reading.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.reading)
        lay.addLayout(head)

        if not self.controllable:
            lay.addWidget(_hint(dev.get("reason") or "This device can only be read."))
            self.slider = None
            return

        # A drag commits on release; a groove click or an arrow key never
        # produces one, so those settle through a short debounce instead.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._commit)

        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setPageStep(5)
        self.slider.setTracking(True)
        self.slider.valueChanged.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._released)
        row.addWidget(self.slider, 1)

        self.spin = QSpinBox()
        self.spin.setRange(0, 100)
        self.spin.setSuffix(" %")
        self.spin.editingFinished.connect(self._commit)
        row.addWidget(self.spin)

        for label, value, tip in (
                ("Auto", "auto", "Hand this fan back to the firmware or driver."),
                ("Max", "100", "Full speed."),
                ("Calibrate", "", "Sweep this fan and measure what it really does.")):
            button = QPushButton(label)
            button.setToolTip(tip)
            if value:
                button.clicked.connect(
                    lambda _c=False, v=value: self.apply_speed.emit(self.dev_id, v))
            else:
                button.clicked.connect(lambda: self.calibrate.emit(self.dev_id))
            row.addWidget(button)
        lay.addLayout(row)

        rng = dev.get("range") or [0, 100]
        if rng[0] > 0:
            lay.addWidget(_hint(
                f"This device only accepts {rng[0]}–{rng[1]}%; anything lower is "
                "clamped by its driver."))
            self.slider.setMinimum(int(rng[0]))
            self.spin.setMinimum(int(rng[0]))

    def _slider_moved(self, value: int) -> None:
        if self._settling:
            return
        self.spin.blockSignals(True)
        self.spin.setValue(value)
        self.spin.blockSignals(False)
        if not self.slider.isSliderDown():
            self._debounce.start(350)

    def _released(self) -> None:
        self._debounce.stop()
        self._commit()

    def _commit(self) -> None:
        if self.slider is None or self._settling:
            return
        self._debounce.stop()
        value = self.spin.value() if self.spin.hasFocus() else self.slider.value()
        self.apply_speed.emit(self.dev_id, str(value))

    def update_reading(self, dev: dict, mode: str, runtime: dict) -> None:
        bits = []
        rpms = [r for r in (dev.get("rpms") or []) if r]
        if rpms:
            bits.append(" / ".join(f"{r} rpm" for r in rpms))
        elif dev.get("control"):
            bits.append("no tachometer")
        if dev.get("temp") is not None:
            bits.append(f"{dev['temp']:.0f} °C")
        bits.append({"auto": "firmware", "manual": "set by hand",
                     "curve": "fan curve", "full": "uncontrolled"}.get(mode, mode))
        if runtime.get("why") and runtime["why"] not in ("curve",):
            bits.append(runtime["why"])
        percent = dev.get("percent")
        head = f"{percent}%" if percent is not None else "—"
        self.reading.setText(f"<b>{head}</b>  ·  " + "  ·  ".join(bits))

        if self.slider is not None and percent is not None:
            if not self.slider.isSliderDown() and not self.spin.hasFocus():
                self._settling = True
                self.slider.setValue(int(percent))
                self.spin.setValue(int(percent))
                self._settling = False


class SettingsDialog(QDialog):
    applied = Signal()

    def __init__(self, cfg, monitor, priv, checker, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.monitor = monitor
        self.priv = priv
        self.updates = checker
        self.downloader = updates.Downloader(self)
        self.setWindowTitle(f"{APP_NAME} settings")
        self.setWindowIcon(icons.app_icon())
        self.resize(940, 780)

        self._phase = 0.0
        self._angle = 0.0
        self._previews: dict[str, StatePreview] = {}
        self._color_buttons: dict[str, ColorButton] = {}
        self._anim_combos: dict[str, QComboBox] = {}
        self._fan_rows: dict[str, FanRow] = {}
        self._fan_fingerprint: tuple | None = None
        self._curve_device = ""
        self._curve_dirty = False
        self._pending_package = ""

        self.strip = StateStrip(self)
        self.tabs = tabs = QTabWidget(self)
        tabs.addTab(self._build_appearance(), "Appearance")
        tabs.addTab(self._build_states(), "States")
        tabs.addTab(self._build_fans(), "Fans")
        tabs.addTab(self._build_curves(), "Curves")
        tabs.addTab(self._build_behaviour(), "Behaviour")
        tabs.addTab(self._build_updates(), "Updates")

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid);")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Apply |
            QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._restore)

        root = QVBoxLayout(self)
        root.addWidget(self.strip)
        root.addWidget(tabs, 1)
        root.addWidget(self.status)
        root.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(45)

        monitor.changed.connect(self._on_snapshot)
        priv.result.connect(self._on_priv)
        self.updates.checked.connect(self._on_update_check)
        self.downloader.progress.connect(self._on_download_progress)
        self.downloader.finished.connect(self._on_download_done)

        self.load_from_config()
        self._on_snapshot(monitor.snapshot)

    # ==================================================== appearance
    def _build_appearance(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        shape = QGroupBox("Icon")
        shape_lay = QVBoxLayout(shape)
        self.style_gallery = Gallery(icons.ICON_STYLES, columns=8)
        self.style_gallery.picked.connect(lambda _k: self._sync_previews())
        shape_lay.addWidget(self.style_gallery)
        shape_lay.addWidget(_hint(
            "Every shape, drawn by the painter the tray uses, at the colour of "
            "the Medium state. The framed ones keep their frame still and turn "
            "only the rotor; the last few show a reading instead of spinning."))
        lay.addWidget(shape)

        motion = QGroupBox("Motion")
        motion_lay = QVBoxLayout(motion)
        self.anim_gallery = Gallery(icons.ANIMATIONS, columns=8)
        self.anim_gallery.picked.connect(self._pick_animation_for_all)
        motion_lay.addWidget(self.anim_gallery)
        motion_lay.addWidget(_hint(
            "These are moving right now, in the shape you picked. Clicking one "
            "gives it to <b>every</b> state — the States tab sets them one by "
            "one, which is where a different animation per state is worth it."))
        lay.addWidget(motion)

        size = QGroupBox("Size and weight")
        form = QFormLayout(size)
        self.icon_size = QComboBox()
        for value in (22, 32, 48, 64, 96):
            self.icon_size.addItem(f"{value} px", value)
        self.icon_size.currentIndexChanged.connect(self._sync_previews)
        form.addRow("Rendered at", self.icon_size)
        form.addRow("", _hint(
            "The panel draws the icon at about 22 px whatever this says. A "
            "bigger pixmap is sharper on a scaled display and costs more to "
            "push across D-Bus on every frame; 48 is the sensible middle."))

        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.6, 1.6)
        self.scale.setSingleStep(0.02)
        self.scale.valueChanged.connect(self._sync_previews)
        form.addRow("Fill of the tray cell", self.scale)

        self.thickness = QDoubleSpinBox()
        self.thickness.setRange(0.4, 2.5)
        self.thickness.setSingleStep(0.05)
        self.thickness.valueChanged.connect(self._sync_previews)
        form.addRow("Stroke weight", self.thickness)

        self.padding = QDoubleSpinBox()
        self.padding.setRange(0.0, 0.30)
        self.padding.setSingleStep(0.01)
        self.padding.valueChanged.connect(self._sync_previews)
        form.addRow("Inner margin", self.padding)
        lay.addWidget(size)

        speed = QGroupBox("Frame rate and rotation")
        sform = QFormLayout(speed)
        self.fps = QSpinBox()
        self.fps.setRange(5, 60)
        self.fps.setSuffix(" fps")
        sform.addRow("Redraw rate", self.fps)

        self.anim_speed = QDoubleSpinBox()
        self.anim_speed.setRange(0.25, 3.0)
        self.anim_speed.setSingleStep(0.05)
        sform.addRow("Animation speed", self.anim_speed)

        self.spin_source = QComboBox()
        self.spin_source.addItem("Measured rpm", "rpm")
        self.spin_source.addItem("Requested duty", "percent")
        self.spin_source.addItem("A fixed speed", "fixed")
        sform.addRow("Rotation follows", self.spin_source)
        sform.addRow("", _hint(
            "Measured rpm is the honest one: motherboard fans sit near 500 rpm "
            "even at 0% duty, so by duty they would look stopped while plainly "
            "still turning."))

        self.spin_min = QDoubleSpinBox()
        self.spin_min.setRange(0.0, 720.0)
        self.spin_min.setSuffix(" °/s")
        self.spin_min.setSingleStep(6.0)
        sform.addRow("Slowest rotation", self.spin_min)

        self.spin_max = QDoubleSpinBox()
        self.spin_max.setRange(12.0, 1440.0)
        self.spin_max.setSuffix(" °/s")
        self.spin_max.setSingleStep(12.0)
        sform.addRow("Fastest rotation", self.spin_max)

        self.animate_idle = QCheckBox("Keep animating while the fans are stopped")
        sform.addRow("", self.animate_idle)
        lay.addWidget(speed)

        colour = QGroupBox("Colour")
        cform = QFormLayout(colour)
        self.color_mode = QComboBox()
        for key, label in COLOR_MODES:
            self.color_mode.addItem(label, key)
        self.color_mode.currentIndexChanged.connect(self._sync_previews)
        cform.addRow("Where the colour comes from", self.color_mode)
        self.mono_color = ColorButton("#c9d1d9")
        self.mono_color.changed.connect(lambda _c: self._sync_previews())
        cform.addRow("The single colour", self.mono_color)
        self.mode_dot = QCheckBox(
            "Corner pip for who is driving the fans (firmware, hand, curve)")
        self.mode_dot.toggled.connect(self._sync_previews)
        cform.addRow("", self.mode_dot)
        lay.addWidget(colour)

        badge = QGroupBox("Number on the icon")
        bform = QFormLayout(badge)
        self.show_badge = QCheckBox("Show one")
        self.show_badge.toggled.connect(self._sync_previews)
        bform.addRow("", self.show_badge)
        self.badge_source = QComboBox()
        for key, label in BADGE_SOURCES:
            self.badge_source.addItem(label, key)
        self.badge_source.currentIndexChanged.connect(self._sync_previews)
        bform.addRow("Showing", self.badge_source)
        self.badge_style = QComboBox()
        for key, label in icons.BADGE_STYLES:
            self.badge_style.addItem(label, key)
        self.badge_style.currentIndexChanged.connect(self._sync_previews)
        bform.addRow("Shape", self.badge_style)
        self.badge_position = QComboBox()
        for key, label in icons.BADGE_POSITIONS:
            self.badge_position.addItem(label, key)
        self.badge_position.currentIndexChanged.connect(self._sync_previews)
        bform.addRow("Corner", self.badge_position)
        self.badge_color = ColorButton("#0d1117")
        self.badge_color.changed.connect(lambda _c: self._sync_previews())
        bform.addRow("Background", self.badge_color)
        self.badge_text_color = ColorButton("#ffffff")
        self.badge_text_color.changed.connect(lambda _c: self._sync_previews())
        bform.addRow("Text", self.badge_text_color)
        lay.addWidget(badge)

        lay.addStretch(1)
        return _scroll(page)

    def _pick_animation_for_all(self, key: str) -> None:
        for combo in self._anim_combos.values():
            _set_data(combo, key)
        self._sync_previews()

    # ======================================================== states
    def _build_states(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(_hint(
            "A colour and an animation for every state the icon can be in. The "
            "swatch beside each row is the real renderer, at tray size. States "
            "are resolved top to bottom: a machine that is too hot says so even "
            "while its fans sit at 40%."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Colour preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("(keep my colours)", "")
        for name in COLOR_PRESETS:
            self.preset_combo.addItem(name, name)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        row.addWidget(self.preset_combo, 1)
        row.addWidget(QLabel("Set every animation to"))
        self.bulk_anim = QComboBox()
        self.bulk_anim.addItem("(leave them alone)", "")
        for key, label in icons.ANIMATIONS:
            self.bulk_anim.addItem(label, key)
        self.bulk_anim.currentIndexChanged.connect(self._bulk_animation)
        row.addWidget(self.bulk_anim, 1)
        lay.addLayout(row)

        box = QGroupBox("Per state")
        grid = QGridLayout(box)
        grid.addWidget(QLabel("<b>State</b>"), 0, 0)
        grid.addWidget(QLabel("<b>Colour</b>"), 0, 1)
        grid.addWidget(QLabel("<b>Animation</b>"), 0, 2)
        grid.addWidget(QLabel("<b>Preview</b>"), 0, 3)
        for line, (key, label) in enumerate(STATES, start=1):
            grid.addWidget(QLabel(label), line, 0)
            button = ColorButton(self.cfg.color_for(key))
            button.changed.connect(lambda _c, k=key: self._sync_previews())
            self._color_buttons[key] = button
            grid.addWidget(button, line, 1)
            combo = QComboBox()
            for akey, alabel in icons.ANIMATIONS:
                combo.addItem(alabel, akey)
            combo.currentIndexChanged.connect(lambda _i: self._sync_previews())
            self._anim_combos[key] = combo
            grid.addWidget(combo, line, 2)
            preview = StatePreview()
            self._previews[key] = preview
            grid.addWidget(preview, line, 3)
        grid.setColumnStretch(2, 1)
        lay.addWidget(box)

        temps = QGroupBox("When to call it hot")
        tform = QFormLayout(temps)
        self.warn_temp = QSpinBox()
        self.warn_temp.setRange(40, 110)
        self.warn_temp.setSuffix(" °C")
        tform.addRow("Warning above", self.warn_temp)
        self.critical_temp = QSpinBox()
        self.critical_temp.setRange(45, 120)
        self.critical_temp.setSuffix(" °C")
        tform.addRow("Critical above", self.critical_temp)
        tform.addRow("", _hint(
            "Measured against the hottest sensor the helper trusts. Super I/O "
            "chips wire more thermistor inputs than any board populates and the "
            "empty ones read as 15 °C or 102 °C rather than as absent, so those "
            "are never what turns the icon red."))
        lay.addWidget(temps)
        lay.addStretch(1)
        return _scroll(page)

    def _bulk_animation(self) -> None:
        key = self.bulk_anim.currentData()
        if not key:
            return
        for combo in self._anim_combos.values():
            _set_data(combo, key)
        self.bulk_anim.blockSignals(True)
        self.bulk_anim.setCurrentIndex(0)
        self.bulk_anim.blockSignals(False)
        self._sync_previews()

    def _apply_preset(self, _index: int) -> None:
        name = self.preset_combo.currentData()
        if not name:
            return
        for key, value in COLOR_PRESETS[name].items():
            if key in self._color_buttons:
                self._color_buttons[key].set_color(value)
        self._sync_previews()

    # ========================================================== fans
    def _build_fans(self) -> QWidget:
        page = QWidget()
        self._fans_layout = QVBoxLayout(page)
        self._fans_layout.addWidget(_hint(
            "Every fan the machine will admit to having, one row each. A "
            "motherboard header is its own fan here — ganging them all together "
            "is exactly the control worth having back."))
        self._fans_empty = _hint("Looking for fan controllers…")
        self._fans_layout.addWidget(self._fans_empty)
        self._fans_layout.addStretch(1)
        return _scroll(page)

    def _rebuild_fans(self, snapshot) -> None:
        names = self.cfg.get("device_names") or {}
        for row in self._fan_rows.values():
            row.setParent(None)
            row.deleteLater()
        self._fan_rows = {}
        self._fans_empty.setVisible(not snapshot.devices)
        if not snapshot.devices:
            self._fans_empty.setText(
                "No fan controller found. On a desktop this usually means the "
                "Super I/O driver is not loaded — try <tt>sudo sensors-detect</tt>, "
                "or add <tt>acpi_enforce_resources=lax</tt> to the kernel command "
                "line if the chip is there but the driver refuses it.")
            return
        for dev in snapshot.devices:
            row = FanRow(dev, names.get(dev["id"], dev["label"]))
            row.apply_speed.connect(self._set_speed)
            row.calibrate.connect(self._calibrate)
            row.rename.connect(self._rename_device)
            self._fan_rows[dev["id"]] = row
            self._fans_layout.insertWidget(self._fans_layout.count() - 1, row)

    def _rename_device(self, dev_id: str, name: str) -> None:
        names = dict(self.cfg.get("device_names") or {})
        if name:
            names[dev_id] = name
        else:
            names.pop(dev_id, None)
        self.cfg["device_names"] = names
        self.cfg.save()
        self.applied.emit()

    def _set_speed(self, dev_id: str, value: str) -> None:
        if value == "0" and self.cfg.get("confirm_zero", True):
            answer = QMessageBox.question(
                self, "Stop this fan?",
                "Setting a fan to 0% stops it. On a CPU header that is only safe "
                "if something else is moving air over the cooler.\n\nStop it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self._on_snapshot(self.monitor.snapshot)
                return
        self._say(f"Applying {value}…")
        self.priv.run(["set", dev_id, value])

    def _calibrate(self, dev_id: str) -> None:
        answer = QMessageBox.question(
            self, "Calibrate this fan?",
            "This sweeps the fan from 0% to 100% in steps, waiting for it to "
            "settle at each one, and writes down the rpm it reaches.\n\n"
            "It takes about a minute, the fan will be loud, and it will stop "
            "entirely at the bottom of the sweep. The speed you had is put back "
            "afterwards.\n\nGo ahead?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._calibrating = dev_id
        self._say("Calibrating — this takes about a minute…")
        self.priv.run(["calibrate", dev_id])

    # ======================================================== curves
    def _build_curves(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        top = QHBoxLayout()
        top.addWidget(QLabel("Fan"))
        self.curve_device = QComboBox()
        self.curve_device.currentIndexChanged.connect(self._curve_device_changed)
        top.addWidget(self.curve_device, 1)
        self.curve_enabled = QCheckBox("Run a curve on this fan")
        self.curve_enabled.toggled.connect(lambda _v: self._mark_curve_dirty())
        top.addWidget(self.curve_enabled)
        lay.addLayout(top)

        source = QHBoxLayout()
        source.addWidget(QLabel("Follows"))
        self.curve_source = QComboBox()
        self.curve_source.currentIndexChanged.connect(self._curve_source_changed)
        source.addWidget(self.curve_source, 1)
        source.addWidget(QLabel("Start from"))
        self.curve_preset = QComboBox()
        self.curve_preset.addItem("(keep this curve)", "")
        for name in curves.PRESETS:
            self.curve_preset.addItem(name, name)
        self.curve_preset.currentIndexChanged.connect(self._apply_curve_preset)
        source.addWidget(self.curve_preset, 1)
        lay.addLayout(source)

        self.editor = curveeditor.CurveEditor()
        self.editor.changed.connect(self._mark_curve_dirty)
        lay.addWidget(self.editor, 1)
        lay.addWidget(_hint(
            "Drag a point to move it. Click the empty graph to add one, "
            "right-click a point to remove it, hold Shift while dragging to "
            "change only the duty. The dashed green line is the sensor this "
            "curve follows right now; the filled dot is what the curve asks for "
            "at that temperature and the hollow ring is what the fan is actually "
            "doing."))

        params = QGroupBox("How it responds")
        grid = QGridLayout(params)

        self.curve_hysteresis = QDoubleSpinBox()
        self.curve_hysteresis.setRange(0.0, 20.0)
        self.curve_hysteresis.setSingleStep(0.5)
        self.curve_hysteresis.setSuffix(" °C")
        self.curve_hysteresis.valueChanged.connect(self._mark_curve_dirty)
        grid.addWidget(QLabel("Hysteresis"), 0, 0)
        grid.addWidget(self.curve_hysteresis, 0, 1)

        self.curve_min = QSpinBox()
        self.curve_min.setRange(0, 100)
        self.curve_min.setSuffix(" %")
        self.curve_min.valueChanged.connect(self._curve_limits_changed)
        grid.addWidget(QLabel("Never below"), 0, 2)
        grid.addWidget(self.curve_min, 0, 3)

        self.curve_max = QSpinBox()
        self.curve_max.setRange(0, 100)
        self.curve_max.setSuffix(" %")
        self.curve_max.valueChanged.connect(self._curve_limits_changed)
        grid.addWidget(QLabel("Never above"), 0, 4)
        grid.addWidget(self.curve_max, 0, 5)

        self.curve_ramp_up = QDoubleSpinBox()
        self.curve_ramp_up.setRange(1.0, 100.0)
        self.curve_ramp_up.setSuffix(" %/s")
        self.curve_ramp_up.valueChanged.connect(self._mark_curve_dirty)
        grid.addWidget(QLabel("Speeds up at"), 1, 0)
        grid.addWidget(self.curve_ramp_up, 1, 1)

        self.curve_ramp_down = QDoubleSpinBox()
        self.curve_ramp_down.setRange(1.0, 100.0)
        self.curve_ramp_down.setSuffix(" %/s")
        self.curve_ramp_down.valueChanged.connect(self._mark_curve_dirty)
        grid.addWidget(QLabel("Slows down at"), 1, 2)
        grid.addWidget(self.curve_ramp_down, 1, 3)

        self.curve_zero = QSpinBox()
        self.curve_zero.setRange(0, 90)
        self.curve_zero.setSuffix(" °C")
        self.curve_zero.setSpecialValueText("never stop")
        self.curve_zero.valueChanged.connect(self._curve_limits_changed)
        grid.addWidget(QLabel("Stop the fan below"), 1, 4)
        grid.addWidget(self.curve_zero, 1, 5)

        self.curve_spinup = QSpinBox()
        self.curve_spinup.setRange(0, 100)
        self.curve_spinup.setSuffix(" %")
        self.curve_spinup.valueChanged.connect(self._mark_curve_dirty)
        grid.addWidget(QLabel("Kick to start at"), 2, 0)
        grid.addWidget(self.curve_spinup, 2, 1)

        self.curve_spinup_ms = QSpinBox()
        self.curve_spinup_ms.setRange(0, 5000)
        self.curve_spinup_ms.setSingleStep(100)
        self.curve_spinup_ms.setSuffix(" ms")
        self.curve_spinup_ms.valueChanged.connect(self._mark_curve_dirty)
        grid.addWidget(QLabel("for"), 2, 2)
        grid.addWidget(self.curve_spinup_ms, 2, 3)

        self.curve_interval = QSpinBox()
        self.curve_interval.setRange(200, 10000)
        self.curve_interval.setSingleStep(100)
        self.curve_interval.setSuffix(" ms")
        self.curve_interval.valueChanged.connect(self._mark_curve_dirty)
        grid.addWidget(QLabel("Checked every"), 2, 4)
        grid.addWidget(self.curve_interval, 2, 5)
        lay.addWidget(params)
        lay.addWidget(_hint(
            "Hysteresis is how far the temperature has to fall before the fan "
            "eases off, and it is what stops a fan hunting up and down at a "
            "steady load. A stopped fan needs a kick before it will take a low "
            "duty, which is what the two spin-up settings are for."))

        service = QGroupBox("Where the curve runs")
        sform = QVBoxLayout(service)
        self.curve_service = QCheckBox(
            "Run curves in the background, as a system service")
        self.curve_service.toggled.connect(self._toggle_curve_service)
        sform.addWidget(self.curve_service)
        self.curve_service_state = _hint("")
        sform.addWidget(self.curve_service_state)
        sform.addWidget(_hint(
            "The service applies curves whether or not anyone is logged in, and "
            "hands every fan it touched back to the firmware when it stops — a "
            "curve daemon that dies must not leave a fan at 20% while the CPU "
            "cooks."))

        row = QHBoxLayout()
        self.curve_apply = QPushButton("Apply curve")
        self.curve_apply.clicked.connect(self._save_curve)
        row.addWidget(self.curve_apply)
        self.curve_hw = QPushButton("Write it into the firmware")
        self.curve_hw.clicked.connect(self._write_hw_curve)
        row.addWidget(self.curve_hw)
        self.curve_hw_reset = QPushButton("Undo that")
        self.curve_hw_reset.clicked.connect(self._reset_hw_curve)
        row.addWidget(self.curve_hw_reset)
        row.addStretch(1)
        sform.addLayout(row)
        self.curve_hw_note = _hint("")
        sform.addWidget(self.curve_hw_note)
        lay.addWidget(service)
        return _scroll(page)

    def _mark_curve_dirty(self) -> None:
        self._curve_dirty = True
        self.curve_apply.setText("Apply curve  •")

    def _curve_limits_changed(self) -> None:
        if self.curve_max.value() < self.curve_min.value():
            self.curve_max.setValue(self.curve_min.value())
        self.editor.curve.update(self._collect_curve(points=False))
        self.editor.update()
        self._mark_curve_dirty()

    def _curve_source_changed(self) -> None:
        self.editor.source_label = self.curve_source.currentText()
        self.editor.clear_trail()
        self._mark_curve_dirty()

    def _apply_curve_preset(self) -> None:
        name = self.curve_preset.currentData()
        if not name:
            return
        curve = curves.with_preset(name, self._collect_curve())
        self._load_curve_widgets(curve)
        self.curve_preset.blockSignals(True)
        self.curve_preset.setCurrentIndex(0)
        self.curve_preset.blockSignals(False)
        self._mark_curve_dirty()

    def _curve_device_changed(self) -> None:
        dev_id = self.curve_device.currentData()
        if not dev_id or dev_id == self._curve_device:
            return
        self._curve_device = dev_id
        snapshot = self.monitor.snapshot
        self._load_curve_widgets(curves.normalise(snapshot.curve_for(dev_id)))
        self.editor.clear_trail()
        self._sync_curve_buttons(snapshot)

    def _load_curve_widgets(self, curve: dict) -> None:
        for widget in (self.curve_enabled, self.curve_hysteresis, self.curve_min,
                       self.curve_max, self.curve_ramp_up, self.curve_ramp_down,
                       self.curve_zero, self.curve_spinup, self.curve_spinup_ms,
                       self.curve_source):
            widget.blockSignals(True)
        self.curve_enabled.setChecked(bool(curve.get("enabled")))
        self.curve_hysteresis.setValue(float(curve["hysteresis"]))
        self.curve_min.setValue(int(curve["min_percent"]))
        self.curve_max.setValue(int(curve["max_percent"]))
        self.curve_ramp_up.setValue(float(curve["ramp_up"]))
        self.curve_ramp_down.setValue(float(curve["ramp_down"]))
        self.curve_zero.setValue(int(curve["zero_below"]))
        self.curve_spinup.setValue(int(curve["spinup_percent"]))
        self.curve_spinup_ms.setValue(int(curve["spinup_ms"]))
        _set_data(self.curve_source, curve.get("source") or "")
        for widget in (self.curve_enabled, self.curve_hysteresis, self.curve_min,
                       self.curve_max, self.curve_ramp_up, self.curve_ramp_down,
                       self.curve_zero, self.curve_spinup, self.curve_spinup_ms,
                       self.curve_source):
            widget.blockSignals(False)
        self.editor.set_curve(curve)
        self._curve_dirty = False
        self.curve_apply.setText("Apply curve")

    def _collect_curve(self, points: bool = True) -> dict:
        curve = curves.default_curve()
        curve.update({
            "enabled": self.curve_enabled.isChecked(),
            "source": self.curve_source.currentData() or "",
            "hysteresis": self.curve_hysteresis.value(),
            "min_percent": self.curve_min.value(),
            "max_percent": self.curve_max.value(),
            "ramp_up": self.curve_ramp_up.value(),
            "ramp_down": self.curve_ramp_down.value(),
            "zero_below": self.curve_zero.value(),
            "spinup_percent": self.curve_spinup.value(),
            "spinup_ms": self.curve_spinup_ms.value(),
        })
        if points:
            curve["points"] = self.editor.points()
        return curve

    def _save_curve(self) -> None:
        dev_id = self.curve_device.currentData()
        if not dev_id:
            return
        store = self.monitor.snapshot.curves or {}
        payload = {
            "version": 1,
            "interval_ms": self.curve_interval.value(),
            "curves": dict(store.get("curves") or {}),
        }
        payload["curves"][dev_id] = self._collect_curve()
        self._say("Saving the curve…")
        self.priv.run(["curve", "set"], json.dumps(payload))
        self._curve_dirty = False
        self.curve_apply.setText("Apply curve")
        if self.curve_enabled.isChecked() and not self.curve_service.isChecked():
            self.curve_service.setChecked(True)

    def _toggle_curve_service(self, on: bool) -> None:
        if self.monitor.snapshot.units.get("curve", "") in ("", "not-found"):
            if on:
                self._say("The curve service is not installed — this only works "
                          "from a package or from install.sh.")
                self.curve_service.blockSignals(True)
                self.curve_service.setChecked(False)
                self.curve_service.blockSignals(False)
            return
        active = self.monitor.snapshot.units.get("curve_active") == "active"
        if on == active:
            return
        self._say("Starting the curve service…" if on else "Stopping it…")
        self.priv.run(["daemon", "on" if on else "off"])

    def _write_hw_curve(self) -> None:
        dev_id = self.curve_device.currentData()
        if not dev_id:
            return
        answer = QMessageBox.question(
            self, "Write this curve into the firmware?",
            "The chip will then run this curve on its own, with no service and "
            "no login — including while this machine is booting, and in any "
            "other operating system on it.\n\n"
            "It is resampled to the five anchor points the firmware has, and "
            "the top one is pinned at full speed so a machine that walks off "
            "the end of the curve still gets every fan it owns.\n\nGo ahead?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        if self._curve_dirty:
            self._save_curve()
        self._say("Writing the curve into the firmware…")
        self.priv.run(["hwcurve", dev_id])

    def _reset_hw_curve(self) -> None:
        dev_id = self.curve_device.currentData()
        if dev_id:
            self._say("Handing the fan back to the firmware's own curve…")
            self.priv.run(["hwcurve", dev_id, "reset"])

    # ===================================================== behaviour
    def _build_behaviour(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        start = QGroupBox("Starting")
        sform = QFormLayout(start)
        self.start_with_system = QCheckBox("Start this tray when I log in")
        sform.addRow("", self.start_with_system)
        self.boot_restore = QCheckBox(
            "Put the speeds I set back after a reboot")
        self.boot_restore.toggled.connect(self._toggle_boot)
        sform.addRow("", self.boot_restore)
        self.boot_state = _hint("")
        sform.addRow("", self.boot_state)
        sform.addRow("", _hint(
            "The first is this icon, and it is yours alone. The second is a "
            "system service that runs before anyone logs in, so it needs the "
            "password once."))
        lay.addWidget(start)

        menu = QGroupBox("Menu and clicking")
        mform = QFormLayout(menu)
        self.click_action = QComboBox()
        self.click_action.addItem("Open the menu", "menu")
        self.click_action.addItem("Open settings", "settings")
        self.click_action.addItem("Hand every fan back to the firmware", "auto")
        self.click_action.addItem("Do nothing", "nothing")
        mform.addRow("Left click", self.click_action)
        self.menu_show_rpm = QCheckBox("Show rpm and temperature in the menu")
        mform.addRow("", self.menu_show_rpm)
        self.menu_show_sensors = QCheckBox("List every temperature sensor too")
        mform.addRow("", self.menu_show_sensors)
        self.tooltip_details = QCheckBox("Put everything in the tooltip as well")
        mform.addRow("", self.tooltip_details)
        self.nudge_step = QSpinBox()
        self.nudge_step.setRange(1, 25)
        self.nudge_step.setSuffix(" %")
        mform.addRow("Increase / decrease step", self.nudge_step)
        self.confirm_zero = QCheckBox("Ask before stopping a fan outright")
        mform.addRow("", self.confirm_zero)
        lay.addWidget(menu)

        notify = QGroupBox("Notifications")
        nform = QFormLayout(notify)
        self.notifications_enabled = QCheckBox("Show notifications at all")
        self.notifications_enabled.toggled.connect(self._sync_notifications)
        nform.addRow("", self.notifications_enabled)
        self.notify_on_change = QCheckBox("When a speed is applied")
        nform.addRow("", self.notify_on_change)
        self.notify_on_warning = QCheckBox("When something gets hot")
        nform.addRow("", self.notify_on_warning)
        self.notify_on_critical = QCheckBox("When something gets critically hot")
        nform.addRow("", self.notify_on_critical)
        self.notify_on_stall = QCheckBox("When a fan that was turning stops")
        nform.addRow("", self.notify_on_stall)
        self.notify_on_curve = QCheckBox("Every time a curve moves a fan")
        nform.addRow("", self.notify_on_curve)
        lay.addWidget(notify)

        poll = QGroupBox("Polling")
        pform = QFormLayout(poll)
        self.poll_ms = QSpinBox()
        self.poll_ms.setRange(500, 30000)
        self.poll_ms.setSingleStep(250)
        self.poll_ms.setSuffix(" ms")
        pform.addRow("Ask the helper every", self.poll_ms)
        pform.addRow("", _hint(
            "Reading is cheap on a motherboard chip and slow on an NVIDIA card, "
            "where every poll is several nvidia-settings calls. If the machine "
            "has one, do not go below about two seconds."))
        lay.addWidget(poll)

        where = QGroupBox("Where things are kept")
        wform = QFormLayout(where)
        wform.addRow("These settings", self._copyable(str(CONFIG_FILE)))
        wform.addRow("Speeds and curves", self._copyable("/etc/fan-control-kde/"))
        lay.addWidget(where)
        lay.addStretch(1)
        return _scroll(page)

    def _copyable(self, text: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        label = QLabel(f"<tt>{text}</tt>")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(label, 1)
        button = QPushButton("Copy")
        button.setFixedWidth(60)
        button.clicked.connect(
            lambda: QApplication.clipboard().setText(text))
        lay.addWidget(button)
        return row

    def _sync_notifications(self) -> None:
        on = self.notifications_enabled.isChecked()
        for box in (self.notify_on_change, self.notify_on_warning,
                    self.notify_on_critical, self.notify_on_stall,
                    self.notify_on_curve):
            box.setEnabled(on)

    def _toggle_boot(self, on: bool) -> None:
        units = self.monitor.snapshot.units
        if units.get("boot", "") in ("", "not-found"):
            if on:
                self._say("The boot service is not installed — this only works "
                          "from a package or from install.sh.")
                self.boot_restore.blockSignals(True)
                self.boot_restore.setChecked(False)
                self.boot_restore.blockSignals(False)
            return
        if (units.get("boot") == "enabled") == on:
            return
        self.priv.run(["boot", "on" if on else "off"])

    # ======================================================= updates
    def _build_updates(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        version = QGroupBox("Version")
        vform = QFormLayout(version)
        vform.addRow("Installed", QLabel(f"<b>{__version__}</b>"))
        self.helper_version = QLabel("—")
        vform.addRow("Helper", self.helper_version)
        self.latest_label = QLabel("Not checked yet.")
        self.latest_label.setWordWrap(True)
        vform.addRow("Latest", self.latest_label)

        row = QHBoxLayout()
        self.check_button = QPushButton("Check for updates")
        self.check_button.clicked.connect(self._check_updates)
        row.addWidget(self.check_button)
        self.install_button = QPushButton("Download and install it")
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._install_update)
        row.addWidget(self.install_button)
        self.release_button = QPushButton("Open the release page")
        self.release_button.setEnabled(False)
        self.release_button.clicked.connect(self._open_release)
        row.addWidget(self.release_button)
        row.addStretch(1)
        vform.addRow("", row)

        self.download_bar = QProgressBar()
        self.download_bar.setVisible(False)
        vform.addRow("", self.download_bar)

        self.check_on_start = QCheckBox("Look for one every time the tray starts")
        vform.addRow("", self.check_on_start)
        self.update_channel = QComboBox()
        self.update_channel.addItem("GitHub and GitLab", "both")
        self.update_channel.addItem("GitHub only", "github")
        self.update_channel.addItem("GitLab only", "gitlab")
        vform.addRow("Ask", self.update_channel)
        vform.addRow("", _hint(
            "The check is one unauthenticated request to a public releases "
            "endpoint, and nothing about this machine goes with it. Installing "
            "downloads the package for this distribution, checks it against the "
            "SHA256SUMS published beside it, and hands it to your package "
            "manager — which asks for the password separately, every time."))
        lay.addWidget(version)

        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(140)
        self.notes.setPlaceholderText("Release notes appear here after a check.")
        notes_box = QGroupBox("What changed")
        notes_lay = QVBoxLayout(notes_box)
        notes_lay.addWidget(self.notes)
        lay.addWidget(notes_box, 1)

        curl = QGroupBox("Install or update from a terminal")
        cform = QFormLayout(curl)
        cform.addRow("From GitHub", self._copyable(updates.INSTALL_COMMAND))
        cform.addRow("From GitLab", self._copyable(updates.INSTALL_COMMAND_GITLAB))
        cform.addRow("", _hint(
            "The same script the project's front page hands out. It works out "
            "which package your distribution wants, downloads it from the latest "
            "release, checks it and installs it."))
        lay.addWidget(curl)

        about = QGroupBox("About")
        aform = QFormLayout(about)
        aform.addRow("Project", self._link(PROJECT_URL))
        aform.addRow("Mirror", self._link(GITLAB_URL))
        aform.addRow("", _hint(
            "Fan Control KDE drives motherboard headers through the kernel's own "
            "hwmon interface, AMD cards through amdgpu and its overdrive fan "
            "curve, and NVIDIA cards through nvidia-settings. It is not "
            "affiliated with AMD, NVIDIA, Intel or KDE."))
        lay.addWidget(about)
        return _scroll(page)

    def _link(self, url: str) -> QLabel:
        label = QLabel(f'<a href="{url}">{url}</a>')
        label.setOpenExternalLinks(True)
        return label

    def _check_updates(self) -> None:
        if not self.updates.check(self.update_channel.currentData() or "both"):
            return
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking…")
        self.latest_label.setText("Asking…")

    def _on_update_check(self, ok: bool, message: str) -> None:
        self.check_button.setEnabled(True)
        self.check_button.setText("Check for updates")
        self.latest_label.setText(message)
        release = self.updates.release
        if not ok or not release:
            self.install_button.setEnabled(False)
            self.release_button.setEnabled(False)
            return
        self.release_button.setEnabled(True)
        self.notes.setMarkdown(release.notes or "_No release notes._")
        family = system.distro_family()
        suffix = system.PACKAGE_SUFFIX.get(family)
        if self.updates.available and suffix and release.asset_for(suffix):
            self.install_button.setEnabled(True)
            self.install_button.setText(
                f"Download and install {release.tag}")
        elif self.updates.available:
            self.install_button.setEnabled(False)
            self.install_button.setText("No package for this distribution")

    def _open_release(self) -> None:
        if self.updates.release:
            QDesktopServices.openUrl(QUrl(self.updates.release.page))

    def _install_update(self) -> None:
        release = self.updates.release
        if not release:
            return
        family = system.distro_family()
        answer = QMessageBox.question(
            self, "Install this update?",
            f"Version {release.tag} will be downloaded from {release.source}, "
            "checked against the SHA256SUMS published beside it, and installed "
            "with your system package manager.\n\n"
            "That last step asks for the administrator password on its own — "
            "installing a package is not something the fan permission covers."
            "\n\nGo ahead?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.install_button.setEnabled(False)
        self.download_bar.setVisible(True)
        self.download_bar.setRange(0, 0)
        self._say(f"Downloading {release.tag}…")
        self.downloader.fetch(release, family)

    def _on_download_progress(self, got: int, total: int) -> None:
        if total > 0:
            self.download_bar.setRange(0, total)
            self.download_bar.setValue(got)
        else:
            self.download_bar.setRange(0, 0)

    def _on_download_done(self, ok: bool, payload: str) -> None:
        self.download_bar.setVisible(False)
        self.install_button.setEnabled(True)
        if not ok:
            self._say(payload)
            QMessageBox.warning(self, "Update", payload)
            return
        self._pending_package = payload
        self._say("Installing — your package manager will ask for the password.")
        job = system.AsyncRun("pkexec", [system.installer_path(), payload], self)
        job._proc.setProcessEnvironment(system.qt_env())
        job.done.connect(self._on_install_done)
        job.start(600000)

    def _on_install_done(self, code: int, out: str, err: str) -> None:
        if code == 0:
            self._say("Installed. Restart the tray to run the new version.")
            QMessageBox.information(
                self, "Update",
                "Installed.\n\nQuit and start the tray again to run it.")
        elif code == 126:
            self._say("The password prompt was dismissed; nothing was installed.")
        else:
            self._say(err or out or f"The installer exited with {code}.")
            QMessageBox.warning(self, "Update",
                                err or out or f"The installer exited with {code}.")

    # ================================================== load and save
    def load_from_config(self) -> None:
        cfg = self.cfg
        self.style_gallery.set_current(cfg["icon_style"])
        _set_data(self.icon_size, int(cfg["icon_size"]))
        self.scale.setValue(float(cfg["icon_scale"]))
        self.thickness.setValue(float(cfg["icon_thickness"]))
        self.padding.setValue(float(cfg["icon_padding"]))
        self.fps.setValue(int(cfg["animation_fps"]))
        self.anim_speed.setValue(float(cfg["animation_speed"]))
        _set_data(self.spin_source, cfg["spin_source"])
        self.spin_min.setValue(float(cfg["spin_min_dps"]))
        self.spin_max.setValue(float(cfg["spin_max_dps"]))
        self.animate_idle.setChecked(bool(cfg["animate_when_idle"]))
        _set_data(self.color_mode, cfg["color_mode"])
        self.mono_color.set_color(cfg["mono_color"])
        self.mode_dot.setChecked(bool(cfg["mode_dot"]))

        self.show_badge.setChecked(bool(cfg["show_badge"]))
        _set_data(self.badge_source, cfg["badge_source"])
        _set_data(self.badge_style, cfg["badge_style"])
        _set_data(self.badge_position, cfg["badge_position"])
        self.badge_color.set_color(cfg["badge_color"])
        self.badge_text_color.set_color(cfg["badge_text_color"])

        for key, button in self._color_buttons.items():
            button.set_color(cfg.color_for(key))
        for key, combo in self._anim_combos.items():
            _set_data(combo, cfg.animation_for(key))
        self.warn_temp.setValue(int(cfg["warn_temp"]))
        self.critical_temp.setValue(int(cfg["critical_temp"]))

        self.start_with_system.setChecked(autostart.is_enabled())
        _set_data(self.click_action, cfg["click_action"])
        self.menu_show_rpm.setChecked(bool(cfg["menu_show_rpm"]))
        self.menu_show_sensors.setChecked(bool(cfg["menu_show_sensors"]))
        self.tooltip_details.setChecked(bool(cfg["tooltip_details"]))
        self.nudge_step.setValue(int(cfg["nudge_step"]))
        self.confirm_zero.setChecked(bool(cfg["confirm_zero"]))

        self.notifications_enabled.setChecked(bool(cfg["notifications_enabled"]))
        self.notify_on_change.setChecked(bool(cfg["notify_on_change"]))
        self.notify_on_warning.setChecked(bool(cfg["notify_on_warning"]))
        self.notify_on_critical.setChecked(bool(cfg["notify_on_critical"]))
        self.notify_on_stall.setChecked(bool(cfg["notify_on_stall"]))
        self.notify_on_curve.setChecked(bool(cfg["notify_on_curve"]))
        self._sync_notifications()

        self.poll_ms.setValue(int(cfg["poll_ms"]))
        self.check_on_start.setChecked(bool(cfg["check_updates_on_start"]))
        _set_data(self.update_channel, cfg["update_channel"])
        self._sync_previews()

    def _collect(self) -> dict:
        return {
            "icon_style": self.style_gallery.current(),
            "icon_size": self.icon_size.currentData(),
            "icon_scale": self.scale.value(),
            "icon_thickness": self.thickness.value(),
            "icon_padding": self.padding.value(),
            "animation_fps": self.fps.value(),
            "animation_speed": self.anim_speed.value(),
            "animate_when_idle": self.animate_idle.isChecked(),
            "spin_source": self.spin_source.currentData(),
            "spin_min_dps": self.spin_min.value(),
            "spin_max_dps": self.spin_max.value(),
            "color_mode": self.color_mode.currentData(),
            "mono_color": self.mono_color.color(),
            "mode_dot": self.mode_dot.isChecked(),
            "colors": {k: b.color() for k, b in self._color_buttons.items()},
            "animations": {k: c.currentData()
                           for k, c in self._anim_combos.items()},
            "show_badge": self.show_badge.isChecked(),
            "badge_source": self.badge_source.currentData(),
            "badge_style": self.badge_style.currentData(),
            "badge_position": self.badge_position.currentData(),
            "badge_color": self.badge_color.color(),
            "badge_text_color": self.badge_text_color.color(),
            "warn_temp": self.warn_temp.value(),
            "critical_temp": self.critical_temp.value(),
            "click_action": self.click_action.currentData(),
            "menu_show_rpm": self.menu_show_rpm.isChecked(),
            "menu_show_sensors": self.menu_show_sensors.isChecked(),
            "tooltip_details": self.tooltip_details.isChecked(),
            "nudge_step": self.nudge_step.value(),
            "confirm_zero": self.confirm_zero.isChecked(),
            "notifications_enabled": self.notifications_enabled.isChecked(),
            "notify_on_change": self.notify_on_change.isChecked(),
            "notify_on_warning": self.notify_on_warning.isChecked(),
            "notify_on_critical": self.notify_on_critical.isChecked(),
            "notify_on_stall": self.notify_on_stall.isChecked(),
            "notify_on_curve": self.notify_on_curve.isChecked(),
            "poll_ms": self.poll_ms.value(),
            "check_updates_on_start": self.check_on_start.isChecked(),
            "update_channel": self.update_channel.currentData(),
            "start_with_system": self.start_with_system.isChecked(),
        }

    def _apply(self) -> bool:
        values = self._collect()
        if values["critical_temp"] <= values["warn_temp"]:
            QMessageBox.warning(
                self, "Temperatures",
                "The critical temperature has to be above the warning one.")
            return False
        autostart.set_enabled(values["start_with_system"])
        self.cfg.update(values)
        self.cfg.save()
        self.monitor.retime()
        self.applied.emit()
        self._say("Saved.")
        return True

    def _ok(self) -> None:
        if self._curve_dirty:
            answer = QMessageBox.question(
                self, "Unsaved curve",
                "The curve on the Curves tab has changes that have not been "
                "applied. Apply it as well?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Yes:
                self._save_curve()
        if self._apply():
            self.accept()

    def _restore(self) -> None:
        answer = QMessageBox.question(
            self, "Back to the defaults?",
            "Every appearance and behaviour setting goes back to how it "
            "shipped. Fan speeds and curves are not touched.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.cfg.reset()
        self.load_from_config()
        self.applied.emit()

    # ============================================== live, every tick
    def _animate(self) -> None:
        self._phase += 0.045 * self.anim_speed.value()
        self._angle = (self._angle + 4.0 * self.anim_speed.value()) % 360.0
        self.strip.phase = self._phase
        self.strip.angle = self._angle
        self.strip.update()
        for key, preview in self._previews.items():
            preview.paint(self._phase, self._angle)
        current = self.tabs.currentIndex()
        if current == 0:
            self.style_gallery.repaint_tiles(
                lambda key: icons.render_pixmap(
                    TILE_PX, key, self._preview_color("medium"),
                    "none", self._phase, self._angle, self._base_ctx()))
            self.anim_gallery.repaint_tiles(
                lambda key: icons.render_pixmap(
                    TILE_PX, self.style_gallery.current(),
                    self._preview_color("medium"), key, self._phase,
                    self._angle, self._base_ctx()))

    def _base_ctx(self) -> icons.RenderCtx:
        snapshot = self.monitor.snapshot
        return icons.RenderCtx(
            factor=0.6, percent=snapshot.top_percent or 60,
            temp=snapshot.hottest, warn=self.warn_temp.value(),
            critical=self.critical_temp.value(),
            thickness=self.thickness.value(), padding=self.padding.value(),
            scale=self.scale.value(),
            badge=self.show_badge.isChecked(), badge_text="60",
            badge_style=self.badge_style.currentData() or "circle",
            badge_position=self.badge_position.currentData() or "br",
            badge_color=self.badge_color.color(),
            badge_text_color=self.badge_text_color.color(),
            mode_dot=MODE_COLORS["curve"] if self.mode_dot.isChecked() else "",
            prism=self.color_mode.currentData() == "prism",
            text="60")

    def _preview_color(self, state: str) -> str:
        mode = self.color_mode.currentData()
        if mode == "mono":
            return self.mono_color.color()
        if mode == "theme":
            return self.palette().windowText().color().name()
        if mode in ("rainbow", "spinbow", "prism", "heat", "velocity"):
            return icons.hue_color((self._phase * 0.2) % 1.0).name()
        button = self._color_buttons.get(state)
        return button.color() if button else "#3daee9"

    def render_state(self, state: str, size: int, phase: float, angle: float):
        combo = self._anim_combos.get(state)
        return icons.render_pixmap(
            size, self.style_gallery.current(), self._preview_color(state),
            combo.currentData() if combo else "none", phase, angle,
            self._base_ctx())

    def _sync_previews(self) -> None:
        ctx = self._base_ctx()
        for key, preview in self._previews.items():
            preview.style_key = self.style_gallery.current()
            preview.color = self._preview_color(key)
            combo = self._anim_combos.get(key)
            preview.animation = combo.currentData() if combo else "none"
            preview.ctx = ctx
        self.mono_color.setEnabled(self.color_mode.currentData() == "mono")
        for widget in (self.badge_source, self.badge_style, self.badge_position,
                       self.badge_color, self.badge_text_color):
            widget.setEnabled(self.show_badge.isChecked())
        self.editor.warn_temp = self.warn_temp.value()
        self.editor.critical_temp = self.critical_temp.value()

    # ============================================ new data from the helper
    _NO_HELPER = "The helper is not answering. Is it installed?"

    def _on_snapshot(self, snapshot) -> None:
        if not snapshot.ok:
            self._say(self._NO_HELPER)
            return
        if self.status.text() == self._NO_HELPER:
            # The first snapshot is always empty - the poll has not come back
            # yet - so that complaint has to be taken back once it does.
            self._say("")
        self.helper_version.setText(snapshot.helper_version or "—")

        fingerprint = snapshot.fingerprint()
        if fingerprint != self._fan_fingerprint:
            self._fan_fingerprint = fingerprint
            self._rebuild_fans(snapshot)
            # An unapplied curve is the user's work in progress; re-reading the
            # stored one over the top of it would throw that away.
            self._rebuild_curve_lists(snapshot, keep_editor=self._curve_dirty)

        for dev in snapshot.devices:
            row = self._fan_rows.get(dev["id"])
            if row:
                row.update_reading(dev, snapshot.mode_of(dev),
                                   snapshot.runtime_for(dev["id"]))

        units = snapshot.units
        installed = units.get("boot", "") not in ("", "not-found")
        self.boot_restore.blockSignals(True)
        self.boot_restore.setChecked(units.get("boot") == "enabled")
        self.boot_restore.setEnabled(installed)
        self.boot_restore.blockSignals(False)
        self.boot_state.setText(
            "" if installed else
            "Not installed — this needs the packaged service, not a source run.")

        curve_installed = units.get("curve", "") not in ("", "not-found")
        active = units.get("curve_active") == "active"
        self.curve_service.blockSignals(True)
        self.curve_service.setChecked(active)
        self.curve_service.setEnabled(curve_installed)
        self.curve_service.blockSignals(False)
        enabled_curves = sum(1 for c in (snapshot.curves.get("curves") or {}).values()
                             if c.get("enabled"))
        if not curve_installed:
            self.curve_service_state.setText(
                "Not installed — this needs the packaged service.")
        elif active:
            self.curve_service_state.setText(
                f"Running, {enabled_curves} curve(s) switched on.")
        else:
            self.curve_service_state.setText(
                f"Stopped. {enabled_curves} curve(s) are switched on and will "
                "start with it.")

        self._update_curve_live(snapshot)
        self._sync_curve_buttons(snapshot)

    def _rebuild_curve_lists(self, snapshot, keep_editor: bool = False) -> None:
        names = self.cfg.get("device_names") or {}
        wanted = self.curve_device.currentData()
        self.curve_device.blockSignals(True)
        self.curve_device.clear()
        for dev in snapshot.controllable:
            self.curve_device.addItem(names.get(dev["id"], dev["label"]), dev["id"])
        self.curve_device.blockSignals(False)

        self.curve_source.blockSignals(True)
        self.curve_source.clear()
        self.curve_source.addItem("whatever this fan sits next to", "")
        for sensor in snapshot.sensors:
            mark = "" if sensor.get("trusted") else "  (unpopulated?)"
            self.curve_source.addItem(
                f"{sensor['label']}  —  {sensor['temp']:.0f} °C{mark}",
                sensor["id"])
        self.curve_source.blockSignals(False)

        if self.curve_device.count() and not keep_editor:
            index = self.curve_device.findData(wanted)
            self.curve_device.setCurrentIndex(max(0, index))
            self._curve_device = ""
            self._curve_device_changed()
        self.curve_interval.blockSignals(True)
        self.curve_interval.setValue(
            int((snapshot.curves or {}).get("interval_ms", 1000)))
        self.curve_interval.blockSignals(False)

    def _update_curve_live(self, snapshot) -> None:
        dev_id = self.curve_device.currentData()
        if not dev_id:
            return
        dev = snapshot.device(dev_id)
        if not dev:
            return
        source = self.curve_source.currentData() or ""
        if source:
            sensor = snapshot.sensor(source)
            temp = sensor["temp"] if sensor else None
            label = sensor["label"] if sensor else ""
        else:
            temp = dev.get("temp")
            hint = dev.get("temp_source")
            sensor = snapshot.sensor(hint) if hint else None
            label = sensor["label"] if sensor else "this fan's own sensor"
        rpms = [r for r in (dev.get("rpms") or []) if r]
        self.editor.set_live(temp, dev.get("percent"),
                             rpms[0] if rpms else None, label)

    def _sync_curve_buttons(self, snapshot) -> None:
        dev_id = self.curve_device.currentData()
        dev = snapshot.device(dev_id) if dev_id else None
        has_hw = bool((dev or {}).get("features", {}).get("hw_curve"))
        self.curve_hw.setEnabled(has_hw)
        self.curve_hw_reset.setEnabled(has_hw)
        if not dev:
            self.curve_hw_note.setText("")
        elif has_hw:
            written = dev.get("hw_curve") or {}
            points = written.get("points") or []
            shown = ", ".join(f"{int(t)}°C→{int(v)}%" for t, v in points[:5])
            self.curve_hw_note.setText(
                f"This device has a firmware curve. It currently holds: {shown}"
                if shown else "This device has a firmware curve.")
        elif dev.get("backend") == "nvidia":
            self.curve_hw_note.setText(
                "NVIDIA exposes no firmware curve to Linux, so a curve on this "
                "card needs the background service running.")
        else:
            self.curve_hw_note.setText(
                "This device has no firmware curve, so a curve on it needs the "
                "background service running.")

    def _on_priv(self, ok: bool, message: str) -> None:
        if not ok and not message:
            self._say("Cancelled.")
            return
        pending = getattr(self, "_calibrating", "")
        if pending and ok and message.strip().startswith("{"):
            self._calibrating = ""
            try:
                result = json.loads(message)
            except ValueError:
                self._say("The calibration came back unreadable.")
                return
            self._show_calibration(result)
            return
        self._say(message or ("Done." if ok else "That did not work."))
        self.monitor.poll()

    def _show_calibration(self, result: dict) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Calibration — {result.get('label', '')}")
        dialog.resize(560, 420)
        lay = QVBoxLayout(dialog)
        plot = curveeditor.CalibrationPlot()
        plot.set_result(result)
        lay.addWidget(plot, 1)

        lines = []
        if result.get("start_percent") is not None:
            lines.append(f"Starts turning at <b>{result['start_percent']}%</b>.")
        if result.get("max_rpm"):
            lines.append(f"Tops out at <b>{result['max_rpm']} rpm</b>.")
        if result.get("min_rpm"):
            lines.append(f"Slowest it will hold is <b>{result['min_rpm']} rpm</b>.")
        if result.get("note"):
            lines.append(result["note"])
        summary = QLabel("<br>".join(lines) or "Nothing measurable came back.")
        summary.setWordWrap(True)
        lay.addWidget(summary)

        row = QHBoxLayout()
        row.addWidget(QLabel("Build a curve from this:"))
        style = QComboBox()
        for name in curves.PRESETS:
            style.addItem(name, name)
        style.setCurrentText("Balanced")
        row.addWidget(style)
        build = QPushButton("Use it")
        row.addWidget(build)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        row.addWidget(close)
        lay.addLayout(row)

        def use_it():
            curve = curves.from_calibration(result, style.currentData())
            index = self.curve_device.findData(result.get("device"))
            if index >= 0:
                self.curve_device.setCurrentIndex(index)
                self._curve_device = result.get("device", "")
            curve["enabled"] = True
            self._load_curve_widgets(curve)
            self._mark_curve_dirty()
            self.tabs.setCurrentIndex(3)
            dialog.accept()

        build.clicked.connect(use_it)
        dialog.exec()

    def _say(self, text: str) -> None:
        self.status.setText(text)
