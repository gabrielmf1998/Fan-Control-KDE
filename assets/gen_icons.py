#!/usr/bin/env python3
"""Regenerate the application icon and the documentation sheets.

Every image the project ships comes out of the same painter the tray uses, so
the icon in the launcher, the previews in the README and the thing spinning in
the panel cannot drift apart.

    python3 assets/gen_icons.py            icon PNGs and the SVG
    python3 assets/gen_icons.py --docs     the styles / animations / states sheets
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPixmap  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402

from fancontrol import icons  # noqa: E402
from fancontrol.config import DEFAULT_ANIMATIONS, DEFAULT_COLORS, STATES  # noqa: E402

NAME = "fan-control-kde"
SIZES = (48, 64, 128, 256, 512)
BRAND = "#3daee9"

SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <title>Fan Control KDE</title>
  <g transform="translate(64 64) rotate(18)" fill="{color}">
{blades}
    <circle cx="0" cy="0" r="{hub:.2f}"/>
  </g>
</svg>
"""


def svg_text() -> str:
    """The classic three-blade rotor, in the same geometry the painter uses:
    an arc out at radius r, an arc back at the hub, swept by 58° with 34° of
    skew - which as a path is two arcs and a close, three times over."""
    import math

    r = 128 * 0.46
    hub = r * 0.20
    span, skew = 58.0, 34.0
    blades = []
    for i in range(3):
        base = i * 120.0
        a0, a1 = base - span / 2.0, base + span / 2.0
        b1, b0 = base + span / 2.0 + skew, base - span / 2.0 - skew + span
        p0 = (r * math.cos(math.radians(a0)), r * math.sin(math.radians(a0)))
        p1 = (r * math.cos(math.radians(a1)), r * math.sin(math.radians(a1)))
        p2 = (hub * math.cos(math.radians(b1)), hub * math.sin(math.radians(b1)))
        p3 = (hub * math.cos(math.radians(b0)), hub * math.sin(math.radians(b0)))
        blades.append(
            f'    <path d="M {p0[0]:.2f} {p0[1]:.2f} '
            f'A {r:.2f} {r:.2f} 0 0 1 {p1[0]:.2f} {p1[1]:.2f} '
            f'L {p2[0]:.2f} {p2[1]:.2f} '
            f'A {hub:.2f} {hub:.2f} 0 0 0 {p3[0]:.2f} {p3[1]:.2f} Z"/>')
    return SVG.format(color=BRAND, blades="\n".join(blades), hub=r * 0.22)


def write_icons() -> None:
    for size in SIZES:
        pixmap = icons.render_pixmap(size, "classic", BRAND, "none", 0.0, 18.0,
                                     icons.RenderCtx(padding=0.04))
        out = HERE / f"{NAME}-{size}.png"
        pixmap.save(str(out), "PNG")
        print("wrote", out.name)
    svg = HERE / f"{NAME}.svg"
    svg.write_text(svg_text(), encoding="utf-8")
    print("wrote", svg.name)


# --------------------------------------------------------------------------
# documentation sheets
# --------------------------------------------------------------------------
def sheet(path: Path, entries, render, columns: int, cell: int = 72,
          label_h: int = 18, title: str = "") -> None:
    rows = (len(entries) + columns - 1) // columns
    top = 26 if title else 8
    width = columns * cell + 16
    height = rows * (cell + label_h) + top + 8
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor("#1b1e24"))
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    if title:
        font = QFont()
        font.setBold(True)
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QColor("#e6edf3"))
        p.drawText(QRectF(8, 4, width - 16, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   title)

    font = QFont()
    font.setPixelSize(10)
    p.setFont(font)
    for i, (key, label) in enumerate(entries):
        col, row = i % columns, i // columns
        x = 8 + col * cell
        y = top + row * (cell + label_h)
        art = render(key)
        p.drawPixmap(int(x + (cell - art.width()) / 2),
                     int(y + (cell - art.height()) / 2), art)
        p.setPen(QColor("#9aa4b2"))
        p.drawText(QRectF(x, y + cell - 2, cell, label_h),
                   Qt.AlignHCenter | Qt.AlignTop, label)
    p.end()
    pixmap.save(str(path), "PNG")
    print("wrote", path.name)


def write_docs() -> None:
    docs = HERE.parent / "docs"
    docs.mkdir(exist_ok=True)
    ctx = icons.RenderCtx(factor=0.75, percent=68, temp=62.0, padding=0.02,
                          text="68")

    sheet(docs / "icon-styles.png", icons.ICON_STYLES,
          lambda key: icons.render_pixmap(56, key, BRAND, "none", 0.0, 22.0, ctx),
          columns=8, title="Icon styles")

    sheet(docs / "icon-styles-22px.png", icons.ICON_STYLES,
          lambda key: icons.render_pixmap(22, key, BRAND, "none", 0.0, 22.0, ctx),
          columns=8, cell=62, title="The same shapes at the size a panel draws them")

    # Animations get a mid-phase frame each: enough to tell them apart on paper.
    sheet(docs / "animations.png", icons.ANIMATIONS,
          lambda key: icons.render_pixmap(56, "classic", BRAND, key, 0.32, 40.0,
                                          ctx),
          columns=8, title="Animations, one frame each")

    sheet(docs / "states.png", STATES,
          lambda key: icons.render_pixmap(
              56, "classic", DEFAULT_COLORS[key],
              DEFAULT_ANIMATIONS.get(key, "none"), 0.32, 26.0, ctx),
          columns=9, title="States, in the default colours")


def main() -> int:
    QGuiApplication([])
    if "--docs" in sys.argv:
        write_docs()
    else:
        write_icons()
        write_docs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
