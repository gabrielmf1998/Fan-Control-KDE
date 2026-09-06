"""Every icon is painted at runtime, so any shape/colour/animation combo works.

Nothing here reads a sensor: it takes a shape, a colour, an animation phase and
a little context (how fast the fans are turning, how hot it is) and gives back a
QIcon. That is what lets the same painter draw the tray, the settings previews
and the application icon without any of them drifting apart.

Rotation is the one thing that is not free-running. The tray advances an angle
at a rate taken from the measured rpm and passes it in, so a fan that is barely
moving is drawn barely moving.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)

ICON_STYLES = [
    # ---- rotors: the fan itself, turning -----------------------------------
    ("classic",     "Classic"),
    ("triblade",    "Tri-blade"),
    ("pinwheel",    "Pinwheel"),
    ("propeller",   "Propeller"),
    ("paddle",      "Paddle blades"),
    ("axial7",      "Axial, 7 blades"),
    ("axial9",      "Axial, 9 blades"),
    ("slimfan",     "Slim, 11 blades"),
    ("sickle",      "Sickle blades"),
    ("scythe",      "Scythe blades"),
    ("maple",       "Maple blades"),
    ("helix",       "Helix"),
    ("starfan",     "Star rotor"),
    ("turbine",     "Turbine"),
    ("turbofan",    "Turbofan"),
    ("jet",         "Jet turbine"),
    ("ringfan",     "Shrouded rotor"),
    ("ducted",      "Ducted fan"),
    ("blower",      "Blower"),
    ("squirrel",    "Squirrel cage"),
    ("waterwheel",  "Water wheel"),
    ("impeller",    "Impeller"),
    ("spiral",      "Spiral"),
    ("vortex",      "Vortex"),
    ("ceiling",     "Ceiling fan"),
    ("windmill",    "Windmill"),
    ("leaf",        "Leaf blades"),
    ("snowflake",   "Snowflake"),
    ("cog",         "Cog"),
    ("orbit",       "Orbit"),
    # ---- framed: the housing stays still, the rotor turns -------------------
    ("casefan",     "Case fan"),
    ("pwmfan",      "Case fan, 4-pin"),
    ("hexfan",      "Hex frame"),
    ("roundfan",    "Round frame"),
    ("caged",       "Wire cage"),
    ("deskfan",     "Desk fan"),
    ("exhaust",     "Exhaust fan"),
    ("crossflow",   "Cross-flow drum"),
    ("bladeless",   "Bladeless"),
    ("stacked",     "Counter-rotating"),
    ("dualfan",     "Twin fans"),
    ("radiator",    "Radiator"),
    ("tower",       "Tower cooler"),
    ("heatpipe",    "Heatpipe cooler"),
    ("aio",         "AIO pump"),
    ("cpu",         "CPU with fan"),
    ("gpu",         "Graphics card"),
    # ---- meters: a reading rather than a rotation ---------------------------
    ("heatsink",    "Heatsink"),
    ("gauge",       "Dial gauge"),
    ("ring",        "Ring meter"),
    ("bars",        "Speed bars"),
    ("thermometer", "Thermometer"),
    ("number",      "Number only"),
]

# Shapes whose frame stays still while only the rotor turns.
FRAMED_STYLES = {"casefan", "pwmfan", "hexfan", "roundfan", "caged", "deskfan",
                 "exhaust", "crossflow", "bladeless", "stacked", "dualfan",
                 "radiator", "tower", "heatpipe", "aio", "cpu", "gpu"}

# Shapes that show a reading rather than a rotation; spinning them is nonsense.
METER_STYLES = {"gauge", "ring", "bars", "thermometer", "number", "heatsink"}

# Shapes that paint right up to their box, so scaling past the cell only crops.
EDGE_TO_EDGE_STYLES = {"casefan", "pwmfan", "exhaust", "crossflow", "radiator",
                       "tower", "heatpipe", "aio", "cpu", "gpu", "heatsink"}

ANIMATIONS = [
    ("none",        "None"),
    ("spin",        "Spin"),
    ("spin_reverse", "Spin (reverse)"),
    ("spin_pulse",  "Spin + pulse"),
    ("spin_glow",   "Spin + glow"),
    ("rev",         "Rev - surge and settle"),
    ("gust",        "Gusts"),
    ("stutter",     "Stutter"),
    ("pulse",       "Pulse (scale)"),
    ("breathe",     "Breathe (fade)"),
    ("throb",       "Throb"),
    ("heartbeat",   "Heartbeat"),
    ("blink",       "Blink"),
    ("flash",       "Fast strobe"),
    ("glow",        "Glow halo"),
    ("ripple",      "Ripple rings"),
    ("airflow",     "Airflow arcs"),
    ("sparkle",     "Sparkle"),
    ("shimmer",     "Shimmer sweep"),
    ("scan",        "Scan line"),
    ("wobble",      "Wobble"),
    ("tumble",      "Tumble"),
    ("bounce",      "Bounce"),
    ("drift",       "Drift"),
    ("seesaw",      "See-saw"),
    ("fade_in",     "Fade in"),
    ("rainbow",     "Rainbow hue"),
    ("hot_glow",    "Glow with the heat"),
    ("fast_spin",   "Spin, faster with the fans"),
    ("blur",        "Motion blur"),
    ("trail",       "Long blur trail"),
    ("swing",       "Swing - an oscillating fan"),
    ("oscillate",   "Oscillate side to side"),
    ("windup",      "Wind up"),
    ("winddown",    "Wind down"),
    ("brake",       "Brake and go"),
    ("dual_dir",    "Reverse every half turn"),
    ("strobe_spin", "Strobed spin"),
    ("judder",      "Judder"),
    ("flicker",     "Flicker"),
    ("zoom",        "Zoom"),
    ("elastic",     "Elastic"),
    ("pop",         "Pop"),
    ("tilt",        "Tilt"),
]

# Animations that carry the rotor round rather than shaking it in place.
ROTATING = {"spin", "spin_reverse", "spin_pulse", "spin_glow", "rev", "gust",
            "stutter", "tumble", "fast_spin", "drift", "blur", "trail",
            "swing", "windup", "winddown", "brake", "dual_dir", "strobe_spin",
            "judder", "tilt"}

# How many times a shape repeats itself in one turn.
#
# This is the number that decides whether rotation reads as rotation. A shape
# with N-fold symmetry looks *identical* every 360/N degrees, so once it turns
# more than about a third of that between two frames the eye stops seeing it
# move: first it strobes, then - past half a period - it appears to run
# backwards, which is the wagon-wheel effect from every western ever filmed.
#
# A three-blade fan gets away with a lot. An eighteen-blade jet turbine at the
# same rpm and the same frame rate is a still picture that twitches.
ROTOR_SYMMETRY = {
    "classic": 3, "triblade": 3, "pinwheel": 4, "propeller": 2, "paddle": 4,
    "axial7": 7, "axial9": 9, "slimfan": 11, "sickle": 5, "scythe": 5,
    "maple": 3, "helix": 3, "starfan": 5, "turbine": 7, "turbofan": 12,
    "jet": 18, "ringfan": 7, "ducted": 4, "blower": 14, "squirrel": 16,
    "waterwheel": 8, "impeller": 6, "spiral": 3, "vortex": 5, "ceiling": 4,
    "windmill": 4, "leaf": 3, "snowflake": 6, "cog": 10, "orbit": 6,
    # For a framed shape it is the rotor inside the housing that matters; the
    # housing does not turn at all.
    "casefan": 5, "pwmfan": 7, "hexfan": 6, "roundfan": 7, "caged": 5,
    "deskfan": 4, "exhaust": 6, "crossflow": 2, "bladeless": 3, "stacked": 7,
    "dualfan": 5, "radiator": 5, "tower": 5, "heatpipe": 7, "aio": 6,
    "cpu": 5, "gpu": 5,
}

# A third of one symmetry period: comfortably under the half that strobes, and
# still fast enough that a fan at full tilt plainly looks like it.
SMOOTH_FRACTION = 1.0 / 3.0


def max_step_degrees(style: str) -> float:
    """The most this shape may turn between two frames and still read as
    turning. Meters have no rotation, so they are given a free hand."""
    if style in METER_STYLES:
        return 360.0
    return 360.0 * SMOOTH_FRACTION / ROTOR_SYMMETRY.get(style, 3)


BADGE_STYLES = [
    ("circle", "Circle"),
    ("pill",   "Pill"),
    ("plain",  "Plain number"),
    ("dot",    "Dot only"),
]

BADGE_POSITIONS = [
    ("br", "Bottom right"),
    ("bl", "Bottom left"),
    ("tr", "Top right"),
    ("tl", "Top left"),
]


# --------------------------------------------------------------------------
# context
# --------------------------------------------------------------------------
@dataclass
class RenderCtx:
    """What a shape may want to know beyond colour and geometry."""
    factor: float = 0.0        # 0..1, how fast the fans are actually turning
    percent: int = 0           # what they were asked for
    temp: float | None = None  # hottest sensor
    warn: float = 75.0
    critical: float = 90.0
    thickness: float = 1.0
    padding: float = 0.02
    scale: float = 1.0
    badge: bool = False
    badge_text: str = ""
    badge_style: str = "circle"
    badge_position: str = "br"
    badge_color: str = "#0d1117"
    badge_text_color: str = "#ffffff"
    mode_dot: str = ""         # colour of the corner pip, "" for none
    prism: bool = False        # paint the blades through a rainbow gradient
    text: str = ""             # what the "number" shape shows


@dataclass
class AnimState:
    spin: float = 0.0          # multiplies the incoming rotation angle
    rotation: float = 0.0      # extra rotation of this animation's own
    scale: float = 1.0
    alpha: float = 1.0
    glow: float = 0.0
    dy: float = 0.0
    dx: float = 0.0
    ripple: float = -1.0
    airflow: float = -1.0
    sparkle: float = 0.0
    shimmer: float = -1.0
    scan: float = -1.0
    hue_shift: float = 0.0
    # (angle offset, alpha multiplier) drawn behind the shape, newest last.
    # This is how a fan is made to look like it is moving in a still frame:
    # the eye reads a smear of trailing copies as speed far more readily than
    # it reads a single blade at a different angle.
    ghosts: tuple = ()
    extra: dict = field(default_factory=dict)


def anim_state(animation: str, phase: float, ctx: RenderCtx) -> AnimState:
    """(animation, free-running phase in turns, context) -> drawing parameters."""
    t = phase % 1.0
    wave = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
    st = AnimState()

    if animation in ROTATING:
        st.spin = 1.0

    if animation == "spin_reverse":
        st.spin = -1.0
    elif animation == "spin_pulse":
        st.scale = 0.90 + 0.14 * wave
    elif animation == "spin_glow":
        st.glow = 0.20 + 0.60 * wave
    elif animation == "rev":
        # surges forward then settles, the way a fan ramps under load
        st.spin = 1.0 + 0.85 * max(0.0, math.sin(t * 2 * math.pi)) ** 3
    elif animation == "gust":
        st.spin = 1.0
        st.rotation = 26.0 * math.sin(t * 4 * math.pi) * (0.3 + 0.7 * wave)
    elif animation == "stutter":
        # advances in six discrete steps, like a strobed rotor
        st.spin = 1.0
        st.rotation = math.floor(t * 6.0) * 6.0
    elif animation == "pulse":
        st.scale = 0.86 + 0.24 * wave
    elif animation == "breathe":
        st.alpha = 0.42 + 0.58 * wave
        st.scale = 0.95 + 0.07 * wave
    elif animation == "throb":
        st.scale = 0.94 + 0.10 * wave
        st.glow = 0.35 * wave
    elif animation == "heartbeat":
        if t < 0.14:
            st.scale = 1.0 + 0.26 * math.sin(t / 0.14 * math.pi)
        elif t < 0.30:
            st.scale = 1.0 + 0.16 * math.sin((t - 0.14) / 0.16 * math.pi)
    elif animation == "blink":
        st.alpha = 1.0 if t < 0.5 else 0.18
    elif animation == "flash":
        st.alpha = 1.0 if (t * 4.0) % 1.0 < 0.5 else 0.15
    elif animation == "glow":
        st.glow = 0.25 + 0.75 * wave
    elif animation == "ripple":
        st.ripple = t
        st.scale = 0.94
    elif animation == "airflow":
        st.airflow = t
    elif animation == "sparkle":
        st.sparkle = wave
        st.glow = 0.30 * wave
    elif animation == "shimmer":
        st.shimmer = t
    elif animation == "scan":
        st.scan = t
    elif animation == "wobble":
        st.rotation = 20.0 * math.sin(t * 2 * math.pi)
    elif animation == "tumble":
        st.scale = 0.62 + 0.38 * abs(math.cos(t * 2 * math.pi))
    elif animation == "bounce":
        st.dy = -abs(math.sin(t * math.pi)) * 0.15
    elif animation == "drift":
        st.dx = 0.06 * math.sin(t * 2 * math.pi)
    elif animation == "seesaw":
        st.rotation = 30.0 * math.sin(t * 2 * math.pi)
        st.dy = 0.04 * math.cos(t * 2 * math.pi)
    elif animation == "fade_in":
        st.alpha = min(1.0, t * 1.8)
        st.scale = 0.72 + 0.28 * min(1.0, t * 1.4)
    elif animation == "rainbow":
        st.hue_shift = t * 360.0
    elif animation == "hot_glow":
        heat = 0.0
        if ctx.temp is not None:
            span = max(1.0, ctx.critical - 30.0)
            heat = max(0.0, min(1.0, (ctx.temp - 30.0) / span))
        st.glow = 0.15 + 0.85 * heat * (0.55 + 0.45 * wave)
    elif animation == "fast_spin":
        st.spin = 1.0 + 1.6 * ctx.factor
    elif animation == "blur":
        # Wide offsets on purpose. A few degrees of smear disappears behind the
        # solid blade in front of it; what reads as speed is a trailing edge
        # spread across a real arc.
        st.spin = 1.0
        st.ghosts = ((-16.0, 0.42), (-30.0, 0.24), (-44.0, 0.12))
    elif animation == "trail":
        st.spin = 1.0
        st.ghosts = tuple((-14.0 * (i + 1), 0.46 * (0.68 ** i)) for i in range(6))
    elif animation == "swing":
        # blades turning while the whole head sweeps, like an oscillating fan
        st.spin = 1.0
        st.dx = 0.07 * math.sin(t * 2 * math.pi)
        st.rotation = 7.0 * math.sin(t * 2 * math.pi)
    elif animation == "oscillate":
        st.dx = 0.09 * math.sin(t * 2 * math.pi)
    elif animation == "windup":
        st.spin = 0.15 + 1.85 * t
    elif animation == "winddown":
        st.spin = 2.0 - 1.85 * t
    elif animation == "brake":
        # runs, stops dead for a beat, runs again
        st.spin = 0.0 if 0.42 < t < 0.58 else 1.0 + 0.4 * math.cos(t * 2 * math.pi)
    elif animation == "dual_dir":
        st.spin = 1.0 if t < 0.5 else -1.0
    elif animation == "strobe_spin":
        st.spin = 1.0
        st.alpha = 1.0 if (t * 6.0) % 1.0 < 0.62 else 0.30
    elif animation == "judder":
        # deterministic, but with no period the eye can lock on to
        st.spin = 1.0
        st.rotation = 5.0 * math.sin(t * 61.0) * math.sin(t * 17.0)
        st.dy = 0.012 * math.sin(t * 43.0)
    elif animation == "flicker":
        st.alpha = 0.45 + 0.55 * abs(math.sin(t * 23.0) * math.sin(t * 7.0))
    elif animation == "zoom":
        st.scale = 0.68 + 0.42 * wave
    elif animation == "elastic":
        # overshoots and settles, rather than easing politely
        st.scale = 1.0 + 0.24 * math.sin(t * 6 * math.pi) * (1.0 - t) ** 1.6
    elif animation == "pop":
        st.scale = 1.0 + (0.28 * math.sin(t / 0.18 * math.pi) if t < 0.18 else 0.0)
    elif animation == "tilt":
        # squashed vertically as if seen from above, and turning
        st.spin = 1.0
        st.extra["squash"] = 0.55 + 0.45 * abs(math.cos(t * 2 * math.pi))

    return st


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _pen(color, width: float, cap=Qt.RoundCap) -> QPen:
    pen = QPen(color)
    pen.setWidthF(max(0.8, width))
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _shift_hue(color: QColor, degrees: float) -> QColor:
    if not degrees:
        return color
    h, s, v, a = color.getHsv()
    if h < 0:
        h, s = 200, max(s, 140)
    return QColor.fromHsv(int((h + degrees) % 360), s, v, a)


def hue_color(hue: float, sat: float = 0.90, val: float = 1.0) -> QColor:
    c = QColor()
    c.setHsvF(hue % 1.0, sat, val)
    return c


def _poly(cx: float, cy: float, r: float, n: int, rot: float = 0.0) -> list[QPointF]:
    return [
        QPointF(cx + r * math.cos(math.radians(rot + i * 360.0 / n)),
                cy + r * math.sin(math.radians(rot + i * 360.0 / n)))
        for i in range(n)
    ]


def _blades(p: QPainter, r: float, count: int, span: float, skew: float,
            hub: float, brush) -> None:
    """Filled blades: fat shapes, because thin strokes vanish at 22 px."""
    outer = QRectF(-r, -r, 2 * r, 2 * r)
    inner = QRectF(-hub, -hub, 2 * hub, 2 * hub)
    p.setBrush(QBrush(brush) if not isinstance(brush, QBrush) else brush)
    p.setPen(Qt.NoPen)
    for i in range(count):
        p.save()
        p.rotate(i * 360.0 / count)
        path = QPainterPath()
        path.arcMoveTo(outer, -span / 2.0)
        path.arcTo(outer, -span / 2.0, span)
        path.arcTo(inner, span / 2.0 + skew, -(span + skew))
        path.closeSubpath()
        p.drawPath(path)
        p.restore()


def _hub(p: QPainter, r: float, brush, k: float = 0.20) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(brush) if not isinstance(brush, QBrush) else brush)
    p.drawEllipse(QPointF(0, 0), r * k, r * k)


def _fmt(n) -> str:
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        return "?"
    return f"{v // 1000}k" if v >= 10000 else str(v)


# --------------------------------------------------------------------------
# rotors - drawn centred on the origin, already rotated by the caller
# --------------------------------------------------------------------------
def _rotor_classic(p, r, c, ctx):
    _blades(p, r, 3, 58, 34, r * 0.20, c)
    _hub(p, r, c, 0.22)


def _rotor_triblade(p, r, c, ctx):
    _blades(p, r, 3, 30, 58, r * 0.14, c)
    _hub(p, r, c, 0.19)


def _rotor_pinwheel(p, r, c, ctx):
    _blades(p, r, 4, 62, 46, r * 0.16, c)
    _hub(p, r, c, 0.18)


def _rotor_propeller(p, r, c, ctx):
    """Two swept paddles, the way a two-blade prop reads head-on.

    Built from the same arc pair as every other rotor rather than a bespoke
    bezier: a hand-drawn airfoil turned into an unreadable lump at 22 px, and
    two blades have nothing else on either side of them to give it away.
    """
    _blades(p, r, 2, 40, 44, r * 0.16, c)
    _hub(p, r, c, 0.24)


def _rotor_turbine(p, r, c, ctx):
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.11 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.97, r * 0.97)
    _blades(p, r * 0.84, 7, 40, 22, r * 0.24, c)
    _hub(p, r, c, 0.26)


def _rotor_jet(p, r, c, ctx):
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.09 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.98, r * 0.98)
    _blades(p, r * 0.90, 18, 13, 9, r * 0.30, c)
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.07 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.32, r * 0.32)
    _hub(p, r, c, 0.16)


def _rotor_blower(p, r, c, ctx):
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.10 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.96, r * 0.96)
    p.setPen(_pen(c, r * 0.115 * ctx.thickness))
    for i in range(14):
        p.save()
        p.rotate(i * 360.0 / 14)
        p.drawLine(QPointF(r * 0.52, 0), QPointF(r * 0.84, -r * 0.20))
        p.restore()
    _hub(p, r, c, 0.30)


def _rotor_impeller(p, r, c, ctx):
    p.setPen(_pen(c, r * 0.20 * ctx.thickness))
    p.setBrush(Qt.NoBrush)
    for i in range(6):
        p.save()
        p.rotate(i * 60.0)
        path = QPainterPath()
        path.moveTo(r * 0.24, 0)
        path.cubicTo(r * 0.60, 0, r * 0.80, -r * 0.20, r * 0.92, -r * 0.52)
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.24)


def _rotor_spiral(p, r, c, ctx):
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(3):
        p.save()
        p.rotate(i * 120.0)
        path = QPainterPath()
        path.moveTo(0, -r * 0.17)
        path.cubicTo(r * 0.55, -r * 0.44, r * 0.92, -r * 0.30, r * 0.99, r * 0.06)
        path.cubicTo(r * 0.70, -r * 0.02, r * 0.42, r * 0.14, 0, r * 0.19)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.21)


def _rotor_vortex(p, r, c, ctx):
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(5):
        p.save()
        p.rotate(i * 72.0)
        path = QPainterPath()
        path.moveTo(0, -r * 0.14)
        path.cubicTo(r * 0.45, -r * 0.40, r * 0.86, -r * 0.34, r * 1.0, 0)
        path.cubicTo(r * 0.72, -r * 0.02, r * 0.38, r * 0.10, 0, r * 0.15)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.18)


def _rotor_ceiling(p, r, c, ctx):
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(4):
        p.save()
        p.rotate(i * 90.0 + 12)
        path = QPainterPath()
        path.addRoundedRect(QRectF(r * 0.24, -r * 0.19, r * 0.76, r * 0.38),
                            r * 0.15, r * 0.15)
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.26)


def _rotor_windmill(p, r, c, ctx):
    """Four sails on thin arms - reads as motion even at one frame."""
    p.setPen(_pen(c, r * 0.09 * ctx.thickness))
    for i in range(4):
        p.save()
        p.rotate(i * 90.0)
        p.drawLine(QPointF(0, 0), QPointF(r * 0.95, 0))
        p.restore()
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(4):
        p.save()
        p.rotate(i * 90.0)
        path = QPainterPath()
        path.moveTo(r * 0.34, 0)
        path.lineTo(r * 0.92, -r * 0.06)
        path.lineTo(r * 0.92, -r * 0.42)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.16)


def _rotor_leaf(p, r, c, ctx):
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(3):
        p.save()
        p.rotate(i * 120.0)
        path = QPainterPath()
        path.moveTo(r * 0.18, 0)
        path.quadTo(r * 0.70, -r * 0.62, r * 0.99, -r * 0.04)
        path.quadTo(r * 0.66, r * 0.24, r * 0.18, 0)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.20)


def _rotor_snowflake(p, r, c, ctx):
    p.setPen(_pen(c, r * 0.13 * ctx.thickness))
    for i in range(6):
        p.save()
        p.rotate(i * 60.0)
        p.drawLine(QPointF(0, 0), QPointF(r * 0.96, 0))
        p.drawLine(QPointF(r * 0.52, 0), QPointF(r * 0.76, -r * 0.30))
        p.drawLine(QPointF(r * 0.52, 0), QPointF(r * 0.76, r * 0.30))
        p.restore()
    _hub(p, r, c, 0.17)


def _rotor_cog(p, r, c, ctx):
    teeth = 10
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    path = QPainterPath()
    for i in range(teeth * 2):
        ang = math.radians(i * 180.0 / teeth)
        rad = r if i % 2 == 0 else r * 0.78
        pt = QPointF(rad * math.cos(ang), rad * math.sin(ang))
        path.lineTo(pt) if i else path.moveTo(pt)
    path.closeSubpath()
    # the middle is punched out rather than overpainted, so it stays a hole on
    # whatever the panel puts behind the icon
    hole = QPainterPath()
    hole.addEllipse(QPointF(0, 0), r * 0.34, r * 0.34)
    p.drawPath(path.subtracted(hole))


def _rotor_orbit(p, r, c, ctx):
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.10 * ctx.thickness))
    for i in range(3):
        p.save()
        p.rotate(i * 60.0)
        p.drawEllipse(QRectF(-r * 0.98, -r * 0.38, r * 1.96, r * 0.76))
        p.restore()
    _hub(p, r, c, 0.26)



# --- more rotors ------------------------------------------------------------
def _rotor_paddle(p, r, c, ctx):
    """Four flat paddles on a hub, the way a pedestal fan looks head-on."""
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(4):
        p.save()
        p.rotate(i * 90.0 + 20)
        p.drawRoundedRect(QRectF(r * 0.22, -r * 0.30, r * 0.76, r * 0.60),
                          r * 0.16, r * 0.16)
        p.restore()
    _hub(p, r, c, 0.24)


def _rotor_axial7(p, r, c, ctx):
    _blades(p, r, 7, 44, 30, r * 0.22, c)
    _hub(p, r, c, 0.24)


def _rotor_axial9(p, r, c, ctx):
    _blades(p, r, 9, 34, 26, r * 0.24, c)
    _hub(p, r, c, 0.26)


def _rotor_slimfan(p, r, c, ctx):
    _blades(p, r, 11, 24, 20, r * 0.26, c)
    _hub(p, r, c, 0.28)


def _rotor_sickle(p, r, c, ctx):
    """Backswept sickle blades: the shape a quiet static-pressure fan uses."""
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(5):
        p.save()
        p.rotate(i * 72.0)
        path = QPainterPath()
        path.moveTo(r * 0.20, -r * 0.06)
        path.cubicTo(r * 0.62, -r * 0.34, r * 0.94, -r * 0.30, r * 0.99, r * 0.04)
        path.cubicTo(r * 0.80, r * 0.30, r * 0.46, r * 0.34, r * 0.18, r * 0.22)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.22)


def _rotor_scythe(p, r, c, ctx):
    """Five long thin blades, tapering to a point at the tip."""
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(5):
        p.save()
        p.rotate(i * 72.0)
        path = QPainterPath()
        path.moveTo(r * 0.16, -r * 0.12)
        path.cubicTo(r * 0.60, -r * 0.36, r * 0.90, -r * 0.30, r * 1.0, -r * 0.02)
        path.cubicTo(r * 0.74, r * 0.02, r * 0.44, r * 0.06, r * 0.16, r * 0.10)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.20)


def _rotor_maple(p, r, c, ctx):
    """Three samara blades - a maple seed, which is the shape nature settled
    on for the same job and reads instantly at any size."""
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(3):
        p.save()
        p.rotate(i * 120.0)
        path = QPainterPath()
        path.moveTo(r * 0.18, 0)
        path.cubicTo(r * 0.44, -r * 0.46, r * 0.86, -r * 0.50, r * 1.0, -r * 0.16)
        path.cubicTo(r * 0.86, r * 0.10, r * 0.48, r * 0.16, r * 0.18, r * 0.16)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.22)


def _rotor_helix(p, r, c, ctx):
    """Twisting ribbons: each blade is a filled band whose two edges cross, so
    it reads as a surface turning through the plane rather than a flat paddle.
    Drawn as an outline pair and filled - two separate strokes just merged into
    a blob at tray size."""
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(3):
        p.save()
        p.rotate(i * 120.0)
        path = QPainterPath()
        path.moveTo(r * 0.16, -r * 0.06)
        path.cubicTo(r * 0.44, -r * 0.46, r * 0.74, r * 0.12, r * 0.99, -r * 0.14)
        path.lineTo(r * 0.99, r * 0.12)
        path.cubicTo(r * 0.74, r * 0.38, r * 0.44, -r * 0.20, r * 0.16, r * 0.20)
        path.closeSubpath()
        p.drawPath(path)
        p.restore()
    _hub(p, r, c, 0.22)


def _rotor_starfan(p, r, c, ctx):
    points = 5
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    path = QPainterPath()
    for i in range(points * 2):
        ang = math.radians(i * 180.0 / points - 90.0)
        rad = r if i % 2 == 0 else r * 0.40
        pt = QPointF(rad * math.cos(ang), rad * math.sin(ang))
        path.lineTo(pt) if i else path.moveTo(pt)
    path.closeSubpath()
    p.drawPath(path)


def _rotor_turbofan(p, r, c, ctx):
    """A wide rim packed with short blades, like a laptop or GPU turbo fan."""
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.10 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.97, r * 0.97)
    _blades(p, r * 0.90, 12, 20, 16, r * 0.46, c)
    _hub(p, r, c, 0.34)


def _rotor_ringfan(p, r, c, ctx):
    """A shrouded rotor: the blade tips are joined by a ring, which is what
    the quiet high-pressure fans do to stop the tips shedding vortices."""
    _blades(p, r * 0.86, 7, 40, 24, r * 0.22, c)
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.11 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.93, r * 0.93)
    _hub(p, r, c, 0.24)


def _rotor_ducted(p, r, c, ctx):
    """A thick duct, three struts holding the motor, and a rotor inside.

    Three struts rather than four, and a gap between them and the blade tips:
    at 22 px four struts line up with the blades and the whole thing closes
    into a disc.
    """
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.19 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.90, r * 0.90)
    p.setPen(_pen(c, r * 0.08 * ctx.thickness))
    for i in range(3):
        p.save()
        p.rotate(i * 120.0 + 30)
        p.drawLine(QPointF(r * 0.42, 0), QPointF(r * 0.80, 0))
        p.restore()
    _blades(p, r * 0.50, 4, 56, 34, r * 0.13, c)
    _hub(p, r, c, 0.19)


def _rotor_squirrel(p, r, c, ctx):
    """A squirrel cage: many short forward-curved blades round an open middle."""
    p.setPen(_pen(c, r * 0.09 * ctx.thickness))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(0, 0), r * 0.98, r * 0.98)
    p.drawEllipse(QPointF(0, 0), r * 0.52, r * 0.52)
    p.setPen(_pen(c, r * 0.10 * ctx.thickness))
    for i in range(16):
        p.save()
        p.rotate(i * 360.0 / 16)
        path = QPainterPath()
        path.moveTo(r * 0.54, 0)
        path.quadTo(r * 0.80, -r * 0.16, r * 0.96, -r * 0.06)
        p.drawPath(path)
        p.restore()


def _rotor_waterwheel(p, r, c, ctx):
    """Flat radial blades between two rings - a paddle wheel."""
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(c, r * 0.09 * ctx.thickness))
    p.drawEllipse(QPointF(0, 0), r * 0.98, r * 0.98)
    p.drawEllipse(QPointF(0, 0), r * 0.40, r * 0.40)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for i in range(8):
        p.save()
        p.rotate(i * 45.0)
        p.drawRect(QRectF(r * 0.40, -r * 0.09, r * 0.56, r * 0.18))
        p.restore()
    _hub(p, r, c, 0.16)


ROTORS = {
    "classic": _rotor_classic, "triblade": _rotor_triblade,
    "pinwheel": _rotor_pinwheel, "propeller": _rotor_propeller,
    "turbine": _rotor_turbine, "jet": _rotor_jet, "blower": _rotor_blower,
    "impeller": _rotor_impeller, "spiral": _rotor_spiral,
    "vortex": _rotor_vortex, "ceiling": _rotor_ceiling,
    "windmill": _rotor_windmill, "leaf": _rotor_leaf,
    "snowflake": _rotor_snowflake, "cog": _rotor_cog, "orbit": _rotor_orbit,
    "paddle": _rotor_paddle, "axial7": _rotor_axial7, "axial9": _rotor_axial9,
    "slimfan": _rotor_slimfan, "sickle": _rotor_sickle, "scythe": _rotor_scythe,
    "maple": _rotor_maple, "helix": _rotor_helix, "starfan": _rotor_starfan,
    "turbofan": _rotor_turbofan, "ringfan": _rotor_ringfan,
    "ducted": _rotor_ducted, "squirrel": _rotor_squirrel,
    "waterwheel": _rotor_waterwheel,
}


# --------------------------------------------------------------------------
# framed shapes - a still frame with a turning rotor inside
# --------------------------------------------------------------------------
def _framed(p, style, r, c, ctx, angle):
    def rotor(inner_r, fn=_rotor_classic, count=5, span=50, skew=30, hub=0.18):
        p.save()
        p.rotate(angle)
        if fn is _rotor_classic:
            _blades(p, inner_r, count, span, skew, inner_r * hub, c)
            _hub(p, inner_r, c, 0.20)
        else:
            fn(p, inner_r, c, ctx)
        p.restore()

    w = r * 0.16 * ctx.thickness
    if style == "casefan":
        pen = _pen(c, w)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r, r * 2, r * 2), r * 0.24, r * 0.24)
        rotor(r * 0.72)
    elif style == "pwmfan":
        # a case fan with its 4-pin tail, which is what tells it apart from
        # every other square thing in a tray
        pen = _pen(c, w * 0.92)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r, r * 1.70, r * 1.70),
                          r * 0.20, r * 0.20)
        # the tail: a lead out of the corner into a 4-pin block, which is the
        # one detail that says "case fan" rather than "square thing"
        p.setPen(_pen(c, r * 0.10 * ctx.thickness))
        path = QPainterPath()
        path.moveTo(r * 0.70, r * 0.40)
        path.cubicTo(r * 0.96, r * 0.46, r * 0.94, r * 0.74, r * 0.78, r * 0.86)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(r * 0.40, r * 0.78, r * 0.40, r * 0.22),
                          r * 0.06, r * 0.06)
        p.save()
        p.translate(-r * 0.15, -r * 0.15)
        p.rotate(angle)
        _blades(p, r * 0.62, 7, 44, 28, r * 0.16, c)
        _hub(p, r * 0.62, c, 0.22)
        p.restore()
    elif style == "caged":
        # the wire guard: concentric rings and spokes, with the rotor behind it
        p.save()
        p.rotate(angle)
        _blades(p, r * 0.80, 5, 52, 32, r * 0.18, c)
        _hub(p, r * 0.80, c, 0.20)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(c, r * 0.07 * ctx.thickness))
        for f in (0.42, 0.70, 0.98):
            p.drawEllipse(QPointF(0, 0), r * f, r * f)
        for i in range(6):
            p.save()
            p.rotate(i * 60.0)
            p.drawLine(QPointF(r * 0.20, 0), QPointF(r * 0.98, 0))
            p.restore()
    elif style == "deskfan":
        # cage, rotor, neck and base: a desk fan seen from the front
        p.save()
        p.translate(0, -r * 0.18)
        p.save()
        p.rotate(angle)
        _blades(p, r * 0.66, 4, 58, 34, r * 0.14, c)
        _hub(p, r * 0.66, c, 0.22)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(c, r * 0.07 * ctx.thickness))
        p.drawEllipse(QPointF(0, 0), r * 0.80, r * 0.80)
        p.drawEllipse(QPointF(0, 0), r * 0.44, r * 0.44)
        p.restore()
        p.setPen(_pen(c, r * 0.11 * ctx.thickness))
        p.drawLine(QPointF(0, r * 0.62), QPointF(0, r * 0.86))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(-r * 0.52, r * 0.84, r * 1.04, r * 0.18),
                          r * 0.09, r * 0.09)
    elif style == "exhaust":
        # a wall extractor: square frame, louvre slats across the bottom half
        pen = _pen(c, w * 0.80)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r, r * 2, r * 2), r * 0.12, r * 0.12)
        p.save()
        p.rotate(angle)
        _blades(p, r * 0.62, 6, 46, 28, r * 0.14, c)
        _hub(p, r * 0.62, c, 0.22)
        p.restore()
        p.setPen(_pen(c, r * 0.07 * ctx.thickness))
        for i in range(3):
            y = r * 0.42 + i * r * 0.22
            p.drawLine(QPointF(-r * 0.84, y), QPointF(r * 0.84, y))
    elif style == "crossflow":
        # a tangential drum: long, low, and packed with blades along its length
        pen = _pen(c, r * 0.10 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r * 0.52, r * 2, r * 1.04),
                          r * 0.50, r * 0.50)
        p.setPen(_pen(c, r * 0.08 * ctx.thickness))
        for i in range(7):
            x = -r * 0.78 + i * r * 0.26
            lean = r * 0.12 * math.sin(math.radians(angle + i * 40.0))
            p.drawLine(QPointF(x - lean, -r * 0.38), QPointF(x + lean, r * 0.38))
    elif style == "bladeless":
        # the ring is the fan; only the airflow inside it moves
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(c, r * 0.20 * ctx.thickness))
        p.drawEllipse(QRectF(-r * 0.86, -r * 0.98, r * 1.72, r * 1.62))
        p.setPen(_pen(c, r * 0.07 * ctx.thickness))
        for i in range(3):
            t = ((angle / 360.0) + i / 3.0) % 1.0
            rr = r * (0.20 + 0.42 * t)
            fade = QColor(c) if isinstance(c, QColor) else QColor("#cccccc")
            fade.setAlphaF(fade.alphaF() * max(0.0, 1.0 - t))
            p.setPen(_pen(fade, r * 0.07 * ctx.thickness))
            p.drawArc(QRectF(-rr, -r * 0.18 - rr * 0.9, rr * 2, rr * 1.8),
                      200 * 16, 140 * 16)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(-r * 0.26, r * 0.56, r * 0.52, r * 0.30),
                          r * 0.10, r * 0.10)
        p.drawRoundedRect(QRectF(-r * 0.52, r * 0.86, r * 1.04, r * 0.16),
                          r * 0.08, r * 0.08)
    elif style == "stacked":
        # two rotors on one axis turning opposite ways, the way a high-pressure
        # server fan is built
        p.save()
        p.rotate(angle)
        _blades(p, r, 7, 30, 22, r * 0.62, c)
        p.restore()
        p.save()
        p.rotate(-angle)
        _blades(p, r * 0.56, 5, 48, 30, r * 0.14, c)
        _hub(p, r * 0.56, c, 0.22)
        p.restore()
    elif style == "heatpipe":
        # fin stack with the heatpipe ends showing through it, and a fan beside
        pen = _pen(c, r * 0.09 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(r * 0.10, -r * 0.86, r * 0.90, r * 1.72),
                          r * 0.09, r * 0.09)
        p.setPen(_pen(c, r * 0.055 * ctx.thickness))
        for i in range(5):
            y = -r * 0.64 + i * r * 0.32
            p.drawLine(QPointF(r * 0.14, y), QPointF(r * 0.96, y))
        # the heatpipe ends, poking out of the top of the stack
        p.setPen(_pen(c, r * 0.09 * ctx.thickness))
        for i in range(3):
            x = r * 0.28 + i * r * 0.27
            p.drawLine(QPointF(x, -r * 0.86), QPointF(x, -r * 0.98))
        p.save()
        p.translate(-r * 0.46, 0)
        p.rotate(angle)
        _blades(p, r * 0.52, 7, 44, 28, r * 0.12, c)
        _hub(p, r * 0.52, c, 0.24)
        p.restore()
    elif style == "hexfan":
        pen = _pen(c, r * 0.15 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF(_poly(0, 0, r, 6)))
        rotor(r * 0.66, count=6, span=44, skew=26)
    elif style == "roundfan":
        p.setPen(_pen(c, r * 0.13 * ctx.thickness))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r * 0.99, r * 0.99)
        for i in range(4):
            p.save()
            p.rotate(i * 90.0 + 45)
            p.drawLine(QPointF(r * 0.80, 0), QPointF(r * 0.99, 0))
            p.restore()
        rotor(r * 0.70, count=7, span=42, skew=24)
    elif style == "dualfan":
        pen = _pen(c, r * 0.11 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r * 0.56, r * 2, r * 1.12), r * 0.14, r * 0.14)
        for sign in (-1, 1):
            p.save()
            p.translate(sign * r * 0.50, 0)
            p.rotate(angle * (1 if sign > 0 else -1))
            _blades(p, r * 0.42, 5, 50, 30, r * 0.09, c)
            _hub(p, r * 0.42, c, 0.22)
            p.restore()
    elif style == "radiator":
        pen = _pen(c, r * 0.11 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r, r * 2, r * 2), r * 0.14, r * 0.14)
        p.setPen(_pen(c, r * 0.07 * ctx.thickness))
        for i in range(-2, 3):
            x = i * r * 0.38
            p.drawLine(QPointF(x, -r * 0.88), QPointF(x, r * 0.88))
        rotor(r * 0.52, count=5, span=48, skew=28)
    elif style == "tower":
        # fan on the left, fin stack on the right, the pair centred in the cell
        pen = _pen(c, r * 0.10 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r * 0.06, -r * 0.94, r * 1.04, r * 1.88),
                          r * 0.10, r * 0.10)
        p.setPen(_pen(c, r * 0.06 * ctx.thickness))
        for i in range(5):
            y = -r * 0.70 + i * r * 0.35
            p.drawLine(QPointF(r * 0.0, y), QPointF(r * 0.92, y))
        p.save()
        p.translate(-r * 0.54, 0)
        p.rotate(angle)
        _blades(p, r * 0.44, 5, 50, 30, r * 0.10, c)
        _hub(p, r * 0.44, c, 0.24)
        p.restore()
    elif style == "aio":
        p.setPen(_pen(c, r * 0.12 * ctx.thickness))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r * 0.66, -r * 0.66, r * 1.32, r * 1.32),
                          r * 0.18, r * 0.18)
        p.setPen(_pen(c, r * 0.10 * ctx.thickness))
        p.drawArc(QRectF(-r * 1.0, -r * 1.0, r * 2, r * 2), 30 * 16, 90 * 16)
        p.drawArc(QRectF(-r * 1.0, -r * 1.0, r * 2, r * 2), 210 * 16, 90 * 16)
        p.save()
        p.rotate(angle)
        _rotor_impeller(p, r * 0.46, c, ctx)
        p.restore()
    elif style == "cpu":
        pen = _pen(c, r * 0.11 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r * 0.80, -r * 0.80, r * 1.60, r * 1.60),
                          r * 0.10, r * 0.10)
        p.setPen(_pen(c, r * 0.09 * ctx.thickness))
        for i in (-1, 0, 1):
            off = i * r * 0.42
            p.drawLine(QPointF(off, -r * 1.0), QPointF(off, -r * 0.80))
            p.drawLine(QPointF(off, r * 0.80), QPointF(off, r * 1.0))
            p.drawLine(QPointF(-r * 1.0, off), QPointF(-r * 0.80, off))
            p.drawLine(QPointF(r * 0.80, off), QPointF(r * 1.0, off))
        rotor(r * 0.56, count=5, span=48, skew=28)
    elif style == "gpu":
        pen = _pen(c, r * 0.10 * ctx.thickness)
        pen.setJoinStyle(Qt.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(-r, -r * 0.62, r * 2, r * 1.24), r * 0.12, r * 0.12)
        p.setPen(_pen(c, r * 0.08 * ctx.thickness))
        p.drawLine(QPointF(-r * 0.62, r * 0.62), QPointF(-r * 0.62, r * 0.94))
        p.drawLine(QPointF(r * 0.10, r * 0.62), QPointF(r * 0.10, r * 0.94))
        for sign in (-1, 1):
            p.save()
            p.translate(sign * r * 0.48, 0)
            p.rotate(angle)
            _blades(p, r * 0.40, 5, 50, 30, r * 0.09, c)
            _hub(p, r * 0.40, c, 0.22)
            p.restore()


# --------------------------------------------------------------------------
# meters - shapes that read a value out rather than turn
# --------------------------------------------------------------------------
def _meter(p, style, r, c, ctx):
    frac = max(0.0, min(1.0, ctx.percent / 100.0))
    w = r * 0.14 * ctx.thickness

    if style == "gauge":
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(c, w * 0.7))
        p.drawArc(QRectF(-r, -r, r * 2, r * 2), 200 * 16, -220 * 16)
        p.setPen(_pen(c, w * 0.45))
        for i in range(5):
            a = math.radians(200.0 - i * 55.0)
            p.drawLine(QPointF(r * 0.74 * math.cos(a), -r * 0.74 * math.sin(a)),
                       QPointF(r * 0.96 * math.cos(a), -r * 0.96 * math.sin(a)))
        a = math.radians(200.0 - frac * 220.0)
        p.setPen(_pen(c, w))
        p.drawLine(QPointF(0, 0),
                   QPointF(r * 0.72 * math.cos(a), -r * 0.72 * math.sin(a)))
        _hub(p, r, c, 0.16)
    elif style == "ring":
        dim = QColor(c if isinstance(c, QColor) else QColor("#888888"))
        dim.setAlphaF(dim.alphaF() * 0.25)
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(dim, w))
        p.drawEllipse(QRectF(-r * 0.86, -r * 0.86, r * 1.72, r * 1.72))
        p.setPen(_pen(c, w))
        p.drawArc(QRectF(-r * 0.86, -r * 0.86, r * 1.72, r * 1.72),
                  90 * 16, -int(360 * frac) * 16)
        _hub(p, r, c, 0.16)
    elif style == "bars":
        n = 5
        gap = r * 0.10
        bw = (r * 2 - gap * (n - 1)) / n
        lit = int(round(frac * n))
        p.setPen(Qt.NoPen)
        for i in range(n):
            h = r * (0.42 + 0.34 * i)
            col = QColor(c) if isinstance(c, QColor) else QColor("#cccccc")
            if i >= max(1, lit):
                col.setAlphaF(col.alphaF() * 0.22)
            p.setBrush(col)
            p.drawRoundedRect(
                QRectF(-r + i * (bw + gap), r - h, bw, h), bw * 0.30, bw * 0.30)
    elif style == "thermometer":
        heat = 0.0
        if ctx.temp is not None:
            span = max(1.0, ctx.critical - 25.0)
            heat = max(0.0, min(1.0, (ctx.temp - 25.0) / span))
        stem = QRectF(-r * 0.22, -r * 0.94, r * 0.44, r * 1.30)
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(c, w * 0.62))
        p.drawRoundedRect(stem, r * 0.22, r * 0.22)
        p.drawEllipse(QPointF(0, r * 0.60), r * 0.36, r * 0.36)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawEllipse(QPointF(0, r * 0.60), r * 0.26, r * 0.26)
        fill_h = (stem.height() - r * 0.12) * heat
        p.drawRoundedRect(
            QRectF(-r * 0.11, stem.bottom() - fill_h, r * 0.22, fill_h + r * 0.20),
            r * 0.11, r * 0.11)
    elif style == "heatsink":
        # a solid base with fins standing on it, and the heat coming off them
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(-r, r * 0.52, r * 2, r * 0.34), r * 0.08, r * 0.08)
        p.setPen(_pen(c, w * 0.62, cap=Qt.FlatCap))
        p.setBrush(Qt.NoBrush)
        for i in range(-3, 4):
            x = i * r * 0.29
            p.drawLine(QPointF(x, -r * 0.30), QPointF(x, r * 0.52))
        p.setPen(_pen(c, w * 0.44))
        for i in (-1, 0, 1):
            base = i * r * 0.52
            path = QPainterPath()
            path.moveTo(base, -r * 0.44)
            path.cubicTo(base + r * 0.20, -r * 0.64, base - r * 0.20, -r * 0.78,
                         base, -r * 0.98)
            p.drawPath(path)


def _draw_number(p, rect, c, ctx):
    text = ctx.text or (f"{ctx.percent}" if ctx.percent is not None else "--")
    f = QFont()
    f.setBold(True)
    size = rect.height() * (0.86 if len(text) <= 2 else 0.62 if len(text) == 3 else 0.48)
    f.setPixelSize(max(6, int(size)))
    p.setFont(f)
    p.setPen(QPen(c if isinstance(c, QColor) else QColor("#cccccc")))
    p.drawText(rect, Qt.AlignCenter, text)


# --------------------------------------------------------------------------
# badge and mode pip
# --------------------------------------------------------------------------
def _paint_badge(p: QPainter, size: int, ctx: RenderCtx, state_color: QColor) -> None:
    if not ctx.badge or not ctx.badge_text:
        return
    text = ctx.badge_text
    bs = ctx.badge_style
    d = size * (0.46 if bs != "dot" else 0.30)
    wide = bs in ("pill", "plain") and len(text) > 1
    bw = d * (1.75 if wide else 1.0)

    pos = ctx.badge_position
    x = size - bw if pos in ("br", "tr") else 0.0
    y = size - d if pos in ("br", "bl") else 0.0
    box = QRectF(x, y, bw, d)

    if bs == "dot":
        p.setPen(Qt.NoPen)
        p.setBrush(state_color)
        p.drawEllipse(box)
        return

    if bs != "plain":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ctx.badge_color))
        p.drawRoundedRect(box, d / 2, d / 2)
        ring = QPen(state_color)
        ring.setWidthF(max(1.0, size * 0.035))
        p.setPen(ring)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, d / 2, d / 2)

    f = QFont()
    f.setBold(True)
    f.setPixelSize(max(7, int(d * (0.68 if len(text) < 3 else 0.50))))
    p.setFont(f)
    p.setPen(QColor(ctx.badge_text_color) if bs != "plain" else state_color)
    p.drawText(box, Qt.AlignCenter, text)


def _paint_mode_dot(p: QPainter, size: int, color: str) -> None:
    """A corner pip saying who is driving the fans."""
    if not color:
        return
    d = size * 0.30
    box = QRectF(0.0, size - d, d, d)
    ring = QColor("#0d1117")
    ring.setAlphaF(0.70)
    p.setPen(Qt.NoPen)
    p.setBrush(ring)
    p.drawEllipse(box)
    p.setBrush(QColor(color))
    p.drawEllipse(box.adjusted(d * 0.18, d * 0.18, -d * 0.18, -d * 0.18))


# --------------------------------------------------------------------------
# the renderer
# --------------------------------------------------------------------------
def render_pixmap(size: int, style: str, color, animation: str, phase: float,
                  angle: float = 0.0, ctx: RenderCtx | None = None) -> QPixmap:
    """`angle` is the rotor's own position, advanced by the caller from rpm."""
    ctx = ctx or RenderCtx()
    st = anim_state(animation, phase, ctx)

    base = QColor(color)
    base = _shift_hue(base, st.hue_shift)
    base.setAlphaF(max(0.0, min(1.0, base.alphaF() * st.alpha)))

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    cx = cy = size / 2.0
    pad = size * max(0.0, min(0.30, ctx.padding))
    r = (size / 2.0 - pad) * 0.92

    # glow halo, underneath everything
    if st.glow > 0.01:
        halo = QRadialGradient(QPointF(cx, cy), size / 2.0)
        g = QColor(base)
        g.setAlphaF(0.55 * st.glow)
        halo.setColorAt(0.0, g)
        g2 = QColor(base)
        g2.setAlphaF(0.0)
        halo.setColorAt(1.0, g2)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QRectF(0, 0, size, size))

    if st.ripple >= 0.0:
        rc = QColor(base)
        rc.setAlphaF(base.alphaF() * max(0.0, 1.0 - st.ripple))
        p.setPen(_pen(rc, max(1.0, size * 0.05)))
        p.setBrush(Qt.NoBrush)
        rr = (size / 2.0) * (0.35 + 0.65 * st.ripple)
        p.drawEllipse(QPointF(cx, cy), rr, rr)

    # brush: either the flat colour, or a rainbow swept round the hub
    brush = base
    if ctx.prism:
        grad = QConicalGradient(0, 0, -angle)
        for i in range(7):
            grad.setColorAt(i / 6.0, hue_color(i / 6.0))
        brush = QBrush(grad)

    rotor_angle = angle * st.spin + st.rotation
    fill = max(0.3, min(2.0, ctx.scale))
    if style in EDGE_TO_EDGE_STYLES:
        fill = min(fill, 1.0)
    squash = float(st.extra.get("squash", 1.0))

    def paint(at_angle: float, paint_brush, alpha: float = 1.0) -> None:
        p.save()
        p.translate(cx + st.dx * size, cy + st.dy * size)
        p.scale(st.scale * fill, st.scale * fill * squash)
        if alpha < 1.0:
            p.setOpacity(alpha)
        if style == "number":
            p.restore()
            p.save()
            p.setOpacity(alpha)
            _draw_number(p, QRectF(pad, pad, size - 2 * pad, size - 2 * pad),
                         base, ctx)
        elif style in METER_STYLES:
            _meter(p, style, r, paint_brush if ctx.prism else base, ctx)
        elif style in FRAMED_STYLES:
            _framed(p, style, r, paint_brush, ctx, at_angle)
        else:
            p.rotate(at_angle)
            ROTORS.get(style, _rotor_classic)(p, r, paint_brush, ctx)
        p.restore()

    # Ghosts first, furthest back first, so the leading edge sits on top.
    for offset, ghost_alpha in reversed(st.ghosts):
        paint(rotor_angle + offset, brush, base.alphaF() * ghost_alpha)
    paint(rotor_angle, brush)

    # airflow: arcs sweeping off the tips, so a still shape still says "moving"
    if st.airflow >= 0.0:
        ac = QColor(base)
        for i in range(3):
            t = (st.airflow + i / 3.0) % 1.0
            ac.setAlphaF(base.alphaF() * (1.0 - t) * 0.7)
            p.setPen(_pen(ac, max(1.0, size * 0.035)))
            p.setBrush(Qt.NoBrush)
            rr = (size / 2.0) * (0.55 + 0.45 * t)
            p.drawArc(QRectF(cx - rr, cy - rr, rr * 2, rr * 2), 40 * 16, 110 * 16)

    if st.sparkle > 0.02:
        sc = QColor(255, 255, 255)
        sc.setAlphaF(0.85 * st.sparkle)
        p.setPen(Qt.NoPen)
        p.setBrush(sc)
        for i in range(3):
            a = math.radians(i * 120.0 - 60.0 + angle * 0.3)
            rr = size * 0.34
            p.drawEllipse(QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a)),
                          size * 0.045 * st.sparkle, size * 0.045 * st.sparkle)

    if st.shimmer >= 0.0:
        p.save()
        p.setClipRect(QRectF(0, 0, size, size))
        sc = QColor(255, 255, 255)
        sc.setAlphaF(0.30)
        p.setPen(Qt.NoPen)
        p.setBrush(sc)
        p.translate(-size * 0.4 + st.shimmer * size * 1.8, 0)
        p.rotate(20)
        p.drawRect(QRectF(0, -size * 0.3, size * 0.16, size * 1.6))
        p.restore()

    if st.scan >= 0.0:
        sc = QColor(base)
        sc.setAlphaF(0.75)
        p.setPen(_pen(sc, max(1.0, size * 0.055)))
        y = size * st.scan
        p.drawLine(QPointF(0, y), QPointF(size, y))

    _paint_badge(p, size, ctx, base)
    if ctx.mode_dot and not (ctx.badge and ctx.badge_position == "bl"):
        _paint_mode_dot(p, size, ctx.mode_dot)
    p.end()
    return pm


# Hand the tray a pixmap at every size it may ask for, so it never has to
# downscale a big one into a 22 px cell and blur it.
TRAY_SIZES = (22, 24, 32, 48, 64)


def render_icon(style: str, color, animation: str, phase: float,
                angle: float = 0.0, ctx: RenderCtx | None = None,
                sizes=TRAY_SIZES) -> QIcon:
    icon = QIcon()
    for s in sizes:
        icon.addPixmap(render_pixmap(s, style, color, animation, phase, angle, ctx))
    return icon


def app_icon(size: int = 128) -> QIcon:
    """The window and desktop icon: a still fan, no badge, no pip."""
    return QIcon(render_pixmap(size, "classic", "#3daee9", "none", 0.0, 18.0,
                               RenderCtx(padding=0.04, scale=1.0)))
