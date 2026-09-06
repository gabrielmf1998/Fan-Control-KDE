"""Everything the user can choose, and where it is kept.

One JSON file under ~/.config. Nothing here needs root: the settings that do -
speeds, curves, the boot service - live on the other side of the helper, in
/etc/fan-control-kde, and are read back from there rather than duplicated.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

APP_NAME = "Fan Control"
APP_ID = "fan-control-kde"
GITHUB_REPO = "gabrielmf1998/fan-control-kde"
GITLAB_REPO = "gabriel17166/fan-control-kde"
PROJECT_URL = f"https://github.com/{GITHUB_REPO}"
GITLAB_URL = f"https://gitlab.com/{GITLAB_REPO}"

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_ID
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / f"{APP_ID}.log"

# System side, written by the helper and only read here.
SYSTEM_DIR = Path("/etc/fan-control-kde")
CURVES_FILE = SYSTEM_DIR / "curves.json"
RUNTIME_STATUS = Path("/run/fan-control-kde/status.json")


# ---------------------------------------------------------------------------
# states
# ---------------------------------------------------------------------------
# What the icon can be showing. Resolved in this order, first match wins, so a
# machine that is on fire says so even while its fans sit at 40%.
STATES = [
    ("error",    "No fan controller"),
    ("critical", "Critically hot"),
    ("warning",  "Running hot"),
    ("stopped",  "Fans stopped"),
    ("idle",     "Idle (under 25%)"),
    ("low",      "Low (25-50%)"),
    ("medium",   "Medium (50-75%)"),
    ("high",     "High (75-100%)"),
    ("max",      "Full speed"),
]

STATE_KEYS = [k for k, _ in STATES]

# The mode a fan is being driven in, shown as a corner pip rather than a state:
# a fan can be at 60% under a curve, under the BIOS, or because someone said so,
# and that is a different question from how fast it is going.
MODES = [
    ("auto",   "Firmware / driver"),
    ("manual", "Set by hand"),
    ("curve",  "Fan curve"),
    ("full",   "Uncontrolled (full speed)"),
]

MODE_COLORS = {
    "auto": "#58a6ff",
    "manual": "#e3b341",
    "curve": "#3fb950",
    "full": "#f0883e",
}


# ---------------------------------------------------------------------------
# colours
# ---------------------------------------------------------------------------
COLOR_PRESETS: dict[str, dict[str, str]] = {
    "Heat map (default)": {
        "error": "#f85149", "critical": "#ff1744", "warning": "#f0883e",
        "stopped": "#8b949e", "idle": "#58a6ff", "low": "#3fb950",
        "medium": "#e3b341", "high": "#f0883e", "max": "#ff7b72",
    },
    "Breeze": {
        "error": "#da4453", "critical": "#ed1515", "warning": "#f67400",
        "stopped": "#7f8c8d", "idle": "#3daee9", "low": "#27ae60",
        "medium": "#f6d32d", "high": "#e67e22", "max": "#c0392b",
    },
    "Traffic light": {
        "error": "#f85149", "critical": "#f85149", "warning": "#e3b341",
        "stopped": "#8b949e", "idle": "#3fb950", "low": "#3fb950",
        "medium": "#e3b341", "high": "#f0883e", "max": "#f85149",
    },
    "Ice to fire": {
        "error": "#ff4d4d", "critical": "#ff2400", "warning": "#ff8c00",
        "stopped": "#5b7c99", "idle": "#7fe7ff", "low": "#59d1ff",
        "medium": "#ffd166", "high": "#ff9f45", "max": "#ff5f45",
    },
    "Neon": {
        "error": "#ff1744", "critical": "#ff0055", "warning": "#ff9500",
        "stopped": "#3a3a4a", "idle": "#00e5ff", "low": "#39ff14",
        "medium": "#ffcc00", "high": "#ff7b00", "max": "#ff00d4",
    },
    "Mono light": {k: "#c9d1d9" for k in STATE_KEYS},
    "Mono dark": {k: "#2b2f36" for k in STATE_KEYS},
    "High contrast": {
        "error": "#ff0000", "critical": "#ff0000", "warning": "#ffff00",
        "stopped": "#808080", "idle": "#00ffff", "low": "#00ff00",
        "medium": "#ffff00", "high": "#ff8800", "max": "#ff0000",
    },
}

DEFAULT_COLORS = dict(COLOR_PRESETS["Heat map (default)"])

DEFAULT_ANIMATIONS = {
    "error": "blink",
    "critical": "flash",
    "warning": "pulse",
    "stopped": "none",
    "idle": "spin",
    "low": "spin",
    "medium": "spin",
    "high": "spin",
    "max": "spin",
}

# Colour modes that ignore the per-state table and compute a colour every frame.
COLOR_MODES = [
    ("state",    "One colour per state"),
    ("theme",    "Follow the panel's own colour"),
    ("mono",     "A single colour"),
    ("heat",     "Heat - from the hottest sensor"),
    ("velocity", "Velocity - from how fast the fans turn"),
    ("rainbow",  "Rainbow"),
    ("spinbow",  "Rainbow, hued by rotation"),
    ("prism",    "Prism - a different hue per blade"),
]

DYNAMIC_COLOR_MODES = {"heat", "velocity", "rainbow", "spinbow", "prism"}

BADGE_SOURCES = [
    ("percent", "Fan speed, %"),
    ("rpm",     "Fastest fan, rpm"),
    ("temp",    "Hottest sensor, °C"),
    ("fans",    "How many fans are turning"),
]


# ---------------------------------------------------------------------------
# defaults
# ---------------------------------------------------------------------------
DEFAULTS: dict = {
    # ------------------------------------------------ appearance
    "icon_style": "classic",
    "color_mode": "state",
    "colors": DEFAULT_COLORS,
    "mono_color": "#c9d1d9",
    "animations": DEFAULT_ANIMATIONS,
    "animation_fps": 22,             # 5 .. 60
    "animation_speed": 1.0,          # 0.25 .. 3.0, multiplies every animation
    "animate_when_idle": True,       # keep moving when the fans are stopped
    "icon_size": 48,                 # pixmap pushed over D-Bus; the panel scales
    "icon_scale": 1.0,               # 0.6 .. 1.6, how much of the cell to fill
    "icon_thickness": 1.0,           # 0.4 .. 2.5, stroke weight multiplier
    "icon_padding": 0.02,            # 0.0 .. 0.30, margin inside the icon
    "mode_dot": True,                # corner pip: auto / manual / curve

    # rotation is in degrees per second, so the visual speed does not change
    # when the frame rate does
    "spin_source": "rpm",            # rpm | percent | fixed
    "spin_min_dps": 36.0,
    "spin_max_dps": 444.0,

    # ------------------------------------------------ badge
    "show_badge": False,
    "badge_source": "percent",
    "badge_style": "circle",         # circle | pill | plain | dot
    "badge_position": "br",
    "badge_color": "#0d1117",
    "badge_text_color": "#ffffff",

    # ------------------------------------------------ thresholds
    "warn_temp": 75,
    "critical_temp": 90,

    # ------------------------------------------------ behaviour
    "click_action": "menu",          # menu | settings | auto | nothing
    "menu_show_sensors": True,
    "menu_show_rpm": True,
    "menu_levels": [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0],
    "nudge_step": 5,
    "tooltip_details": True,
    "confirm_zero": True,            # ask before stopping a fan outright
    "start_with_system": False,      # written through autostart.py, mirrored here
    # What each fan is called here. A motherboard header has no name in sysfs -
    # the guess is "CPU fan" for pwm1 and "Fan header N" for the rest - so the
    # one person who knows which header the top exhaust is plugged into gets to
    # say so.
    "device_names": {},

    # ------------------------------------------------ notifications
    "notifications_enabled": True,
    "notify_on_change": True,        # a speed was applied
    "notify_on_warning": True,       # crossed the warning temperature
    "notify_on_critical": True,
    "notify_on_stall": True,         # a fan that was turning has stopped
    "notify_on_curve": False,        # the daemon moved a fan

    # ------------------------------------------------ polling
    "poll_ms": 2500,

    # ------------------------------------------------ updates
    "check_updates_on_start": False,
    "update_channel": "both",        # github | gitlab | both
}


def _merge(base: dict, incoming: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = {**out[key], **value}
        else:
            out[key] = value
    return out


class Config:
    def __init__(self) -> None:
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    # -- dict-ish access ---------------------------------------------------
    def __getitem__(self, key: str):
        return self._data.get(key, DEFAULTS.get(key))

    def __setitem__(self, key: str, value) -> None:
        self._data[key] = value

    def get(self, key: str, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def update(self, values: dict) -> None:
        self._data = _merge(self._data, values)

    def as_dict(self) -> dict:
        return copy.deepcopy(self._data)

    def reset(self) -> None:
        self._data = copy.deepcopy(DEFAULTS)

    # -- per-state ---------------------------------------------------------
    def color_for(self, state: str) -> str:
        colors = self._data.get("colors") or {}
        return colors.get(state) or DEFAULT_COLORS.get(state, "#c9d1d9")

    def animation_for(self, state: str) -> str:
        anims = self._data.get("animations") or {}
        return anims.get(state) or DEFAULT_ANIMATIONS.get(state, "none")

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            self._data = _merge(DEFAULTS, raw)

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
            tmp.replace(CONFIG_FILE)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# state resolution
# ---------------------------------------------------------------------------
def resolve_state(devices: list[dict], hottest: float | None,
                  warn: float, critical: float) -> str:
    """The one state the icon is in, from everything we know this poll."""
    if not devices:
        return "error"
    if hottest is not None:
        if hottest >= critical:
            return "critical"
        if hottest >= warn:
            return "warning"

    # The helper only reports an rpm it actually measured, so a stopped fan
    # contributes nothing to this list rather than a zero. "Everything has
    # stopped" therefore has to be asked as "something can be measured, and
    # none of it is moving".
    turning = [r for d in devices for r in (d.get("rpms") or []) if r]
    measurable = any(d.get("rpms") or (d.get("features") or {}).get("tach")
                     for d in devices)
    if measurable and not turning:
        return "stopped"

    percents = [d.get("percent") for d in devices
                if d.get("control") and d.get("percent") is not None]
    if not percents:
        # monitor-only machine: say something from the tachometers instead
        return "idle" if turning else "stopped"

    top = max(percents)
    if top >= 100:
        return "max"
    if top >= 75:
        return "high"
    if top >= 50:
        return "medium"
    if top >= 25:
        return "low"
    return "idle"


def dominant_mode(devices: list[dict]) -> str:
    """One word for how the machine's fans are being driven right now."""
    modes = [d.get("mode") for d in devices if d.get("control")]
    for candidate in ("curve", "manual", "full", "auto"):
        if candidate in modes:
            return candidate
    return "auto"
