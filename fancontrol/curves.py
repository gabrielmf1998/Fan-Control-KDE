"""The curve model, on the GUI side.

The helper owns the file and the control loop; this is the same maths again so
the editor can draw what the daemon is going to do without asking it, and a set
of starting points so nobody has to invent a curve from nothing.
"""

from __future__ import annotations

import copy

# Mirrors CURVE_DEFAULTS in the helper. Kept as a plain dict rather than
# imported, because the helper is a standalone script that runs as root and is
# not on this process's import path.
DEFAULTS = {
    "enabled": False,
    "source": "",
    "points": [[30, 25], [50, 40], [65, 65], [80, 100]],
    "hysteresis": 3.0,
    "min_percent": 0,
    "max_percent": 100,
    "spinup_percent": 45,
    "spinup_ms": 900,
    "zero_below": 0,
    "ramp_up": 40,
    "ramp_down": 8,
}

# Starting points. Each is a whole curve, not just the points, because the
# quiet ones only work with a slow ramp and the loud ones only with a fast one.
PRESETS: dict[str, dict] = {
    "Silent": {
        "points": [[30, 0], [50, 20], [65, 35], [78, 60], [88, 100]],
        "hysteresis": 5.0, "ramp_up": 15, "ramp_down": 4,
        "zero_below": 45, "spinup_percent": 45,
    },
    "Quiet": {
        "points": [[30, 20], [50, 28], [62, 42], [75, 70], [85, 100]],
        "hysteresis": 4.0, "ramp_up": 20, "ramp_down": 5, "zero_below": 0,
    },
    "Balanced": {
        "points": [[30, 25], [50, 40], [65, 65], [80, 100]],
        "hysteresis": 3.0, "ramp_up": 40, "ramp_down": 8, "zero_below": 0,
    },
    "Performance": {
        "points": [[30, 40], [45, 55], [60, 80], [72, 100]],
        "hysteresis": 2.0, "ramp_up": 60, "ramp_down": 15, "zero_below": 0,
    },
    "Aggressive": {
        "points": [[30, 55], [40, 70], [55, 90], [65, 100]],
        "hysteresis": 1.0, "ramp_up": 100, "ramp_down": 25, "zero_below": 0,
    },
    "Linear": {
        "points": [[25, 0], [95, 100]],
        "hysteresis": 2.0, "ramp_up": 40, "ramp_down": 10, "zero_below": 0,
    },
    "Stepped": {
        "points": [[40, 30], [50, 30], [51, 50], [65, 50], [66, 75],
                   [78, 75], [79, 100]],
        "hysteresis": 4.0, "ramp_up": 100, "ramp_down": 100, "zero_below": 0,
    },
    "Zero RPM": {
        "points": [[50, 0], [55, 30], [70, 55], [82, 100]],
        "hysteresis": 6.0, "ramp_up": 25, "ramp_down": 5,
        "zero_below": 52, "spinup_percent": 55, "spinup_ms": 1200,
    },
    "Full blast": {
        "points": [[20, 100], [100, 100]],
        "hysteresis": 0.0, "ramp_up": 100, "ramp_down": 100, "zero_below": 0,
    },
}


def default_curve() -> dict:
    return copy.deepcopy(DEFAULTS)


def with_preset(name: str, base: dict | None = None) -> dict:
    """A preset applied over an existing curve, keeping its source and switch."""
    curve = copy.deepcopy(base) if base else default_curve()
    preset = PRESETS.get(name)
    if not preset:
        return curve
    for key in DEFAULTS:
        if key in preset:
            curve[key] = copy.deepcopy(preset[key])
    return curve


def normalise(curve: dict) -> dict:
    """Fill in anything missing and put the points in order."""
    out = default_curve()
    out.update({k: v for k, v in (curve or {}).items() if k in DEFAULTS})
    points = []
    for pair in out["points"]:
        try:
            points.append([float(pair[0]), float(pair[1])])
        except (TypeError, ValueError, IndexError):
            continue
    out["points"] = sorted(points) or copy.deepcopy(DEFAULTS["points"])
    return out


def value_at(points, temp: float) -> float:
    """Linear interpolation between the points, flat outside them. The daemon
    does exactly this, so the graph and the fan agree."""
    pts = sorted((float(t), float(v)) for t, v in points)
    if not pts:
        return 0.0
    if temp <= pts[0][0]:
        return pts[0][1]
    if temp >= pts[-1][0]:
        return pts[-1][1]
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if t0 <= temp <= t1:
            return v1 if t1 == t0 else v0 + (v1 - v0) * (temp - t0) / (t1 - t0)
    return pts[-1][1]


def effective_at(curve: dict, temp: float) -> float:
    """What the fan is actually asked for at this temperature: the curve, then
    the floor, the ceiling and the zero-rpm cut-off."""
    c = normalise(curve)
    if c["zero_below"] and temp < c["zero_below"]:
        return 0.0
    return max(c["min_percent"], min(c["max_percent"], value_at(c["points"], temp)))


def describe(curve: dict) -> str:
    """One line for a menu or a tooltip."""
    c = normalise(curve)
    pts = " → ".join("%d°C %d%%" % (int(t), int(v)) for t, v in c["points"])
    extra = []
    if c["zero_below"]:
        extra.append("stops below %d°C" % c["zero_below"])
    if c["min_percent"]:
        extra.append("never under %d%%" % c["min_percent"])
    if c["max_percent"] < 100:
        extra.append("never over %d%%" % c["max_percent"])
    return pts + ("  ·  " + ", ".join(extra) if extra else "")


def from_calibration(result: dict, style: str = "Balanced") -> dict:
    """Turn a measured sweep into a curve that respects what the fan can do.

    The one thing a calibration knows that a preset cannot is the duty this
    particular fan needs before it turns at all. A curve that dips below that
    does not run the fan quietly, it stops it.
    """
    curve = with_preset(style)
    start = result.get("start_percent")
    if start:
        floor = min(95, int(start) + 5)
        curve["min_percent"] = max(curve["min_percent"], floor if floor > 5 else 0)
        curve["spinup_percent"] = max(curve["spinup_percent"], floor)
        curve["points"] = [[t, max(v, floor) if v > 0 else 0]
                           for t, v in curve["points"]]
    return curve
