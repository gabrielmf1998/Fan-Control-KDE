"""The fan curve, as a graph you drag.

Temperature runs left to right, fan speed bottom to top, and the points in
between are the curve. Everything the daemon will do to that curve - the floor,
the ceiling, the zero-rpm cut-off - is drawn as well, so what is on screen is
what the fan is going to do rather than a sketch of it.

The live marker is the point of the whole thing: the vertical line is the
sensor this curve follows, right now, and the dot on the curve is the duty that
temperature asks for. Watching it move while a game loads tells you more about
whether a curve is right than any amount of arithmetic.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from . import curves

TEMP_MIN = 20.0
TEMP_MAX = 100.0
GRAB_PX = 11.0          # how near the pointer has to be to catch a point
MAX_POINTS = 12
TRAIL_LEN = 90          # samples kept for the ghost trail, ~3 minutes at 2 s


class CurveEditor(QWidget):
    """Drag the points. Click the empty graph to add one, right-click to remove."""

    changed = Signal()
    pointSelected = Signal(int)     # index, or -1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.CrossCursor)

        self.curve = curves.default_curve()
        self.live_temp: float | None = None
        self.live_percent: float | None = None
        self.live_rpm: int | None = None
        self.source_label = ""
        self.warn_temp = 75.0
        self.critical_temp = 90.0
        self.trail: list[tuple[float, float]] = []

        self._drag = -1
        self._hover = -1
        self._hover_pos: QPointF | None = None

    # ----------------------------------------------------------- data in
    def set_curve(self, curve: dict) -> None:
        self.curve = curves.normalise(curve)
        self._drag = -1
        self.update()

    def points(self) -> list[list[float]]:
        return [[round(t, 1), round(v)] for t, v in self.curve["points"]]

    def set_live(self, temp: float | None, percent: float | None,
                 rpm: int | None = None, source_label: str = "") -> None:
        self.live_temp = temp
        self.live_percent = percent
        self.live_rpm = rpm
        if source_label:
            self.source_label = source_label
        if temp is not None and percent is not None:
            self.trail.append((temp, percent))
            del self.trail[:-TRAIL_LEN]
        self.update()

    def clear_trail(self) -> None:
        self.trail = []
        self.update()

    # ------------------------------------------------------- coordinates
    def plot_rect(self) -> QRectF:
        metrics = QFontMetrics(self.font())
        left = metrics.horizontalAdvance("100%") + 12
        bottom = metrics.height() + 12
        return QRectF(left, 10, max(40.0, self.width() - left - 14),
                      max(40.0, self.height() - bottom - 16))

    def to_px(self, temp: float, percent: float) -> QPointF:
        r = self.plot_rect()
        x = r.left() + (temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN) * r.width()
        y = r.bottom() - percent / 100.0 * r.height()
        return QPointF(x, y)

    def from_px(self, pos: QPointF) -> tuple[float, float]:
        r = self.plot_rect()
        temp = TEMP_MIN + (pos.x() - r.left()) / max(1.0, r.width()) * (TEMP_MAX - TEMP_MIN)
        pct = (r.bottom() - pos.y()) / max(1.0, r.height()) * 100.0
        return (max(TEMP_MIN, min(TEMP_MAX, temp)),
                max(0.0, min(100.0, pct)))

    def _nearest(self, pos: QPointF) -> int:
        best, best_d = -1, GRAB_PX
        for i, (t, v) in enumerate(self.curve["points"]):
            p = self.to_px(t, v)
            d = ((p.x() - pos.x()) ** 2 + (p.y() - pos.y()) ** 2) ** 0.5
            if d < best_d:
                best, best_d = i, d
        return best

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, event) -> None:
        pos = event.position()
        index = self._nearest(pos)
        if event.button() == Qt.RightButton:
            if index >= 0 and len(self.curve["points"]) > 2:
                del self.curve["points"][index]
                self.pointSelected.emit(-1)
                self.changed.emit()
                self.update()
            return
        if event.button() != Qt.LeftButton:
            return
        if index < 0:
            if len(self.curve["points"]) >= MAX_POINTS:
                return
            temp, pct = self.from_px(pos)
            self.curve["points"].append([round(temp), round(pct)])
            self.curve["points"].sort()
            index = next(i for i, p in enumerate(self.curve["points"])
                         if p[0] == round(temp))
            self.changed.emit()
        self._drag = index
        self.pointSelected.emit(index)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        self._hover_pos = pos
        if self._drag < 0:
            hover = self._nearest(pos)
            if hover != self._hover:
                self._hover = hover
                self.setCursor(Qt.SizeAllCursor if hover >= 0 else Qt.CrossCursor)
            self.update()
            return

        temp, pct = self.from_px(pos)
        pts = self.curve["points"]
        # Points may not swap places: a curve whose temperatures are out of
        # order is not a curve, and the firmware ones reject it outright.
        low = pts[self._drag - 1][0] + 1 if self._drag > 0 else TEMP_MIN
        high = pts[self._drag + 1][0] - 1 if self._drag < len(pts) - 1 else TEMP_MAX
        if high < low:
            high = low
        if event.modifiers() & Qt.ShiftModifier:
            temp = pts[self._drag][0]          # shift: move the duty only
        pts[self._drag] = [round(max(low, min(high, temp))), round(pct)]
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag >= 0:
            self._drag = -1
            self.curve["points"].sort()
            self.changed.emit()
            self.update()

    def leaveEvent(self, _event) -> None:
        self._hover = -1
        self._hover_pos = None
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self._hover >= 0:
            if len(self.curve["points"]) > 2:
                del self.curve["points"][self._hover]
                self._hover = -1
                self.changed.emit()
                self.update()
            return
        super().keyPressEvent(event)

    # ----------------------------------------------------------- painting
    def _palette(self) -> dict:
        pal = self.palette()
        text = pal.windowText().color()
        grid = QColor(text)
        grid.setAlphaF(0.14)
        faint = QColor(text)
        faint.setAlphaF(0.45)
        return {"text": text, "grid": grid, "faint": faint,
                "curve": QColor("#3daee9"), "live": QColor("#3fb950"),
                "warn": QColor("#f0883e"), "crit": QColor("#f85149")}

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        c = self._palette()
        r = self.plot_rect()
        metrics = QFontMetrics(self.font())

        self._paint_bands(p, r, c)
        self._paint_grid(p, r, c, metrics)
        self._paint_limits(p, r, c)
        self._paint_trail(p, c)
        self._paint_curve(p, r, c)
        self._paint_live(p, r, c, metrics)
        self._paint_points(p, c)
        self._paint_hover(p, r, c, metrics)
        p.end()

    def _paint_bands(self, p, r, c) -> None:
        """The hot end of the axis, shaded, so a curve that ignores it looks wrong."""
        for temp, color, alpha in ((self.warn_temp, c["warn"], 0.10),
                                   (self.critical_temp, c["crit"], 0.16)):
            if temp <= TEMP_MIN or temp >= TEMP_MAX:
                continue
            x = self.to_px(temp, 0).x()
            band = QColor(color)
            band.setAlphaF(alpha)
            p.fillRect(QRectF(x, r.top(), r.right() - x, r.height()), band)

    def _paint_grid(self, p, r, c, metrics) -> None:
        p.setPen(QPen(c["grid"], 1))
        for pct in range(0, 101, 20):
            y = self.to_px(TEMP_MIN, pct).y()
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        for temp in range(int(TEMP_MIN), int(TEMP_MAX) + 1, 10):
            x = self.to_px(temp, 0).x()
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

        p.setPen(QPen(c["faint"], 1))
        for pct in range(0, 101, 20):
            y = self.to_px(TEMP_MIN, pct).y()
            p.drawText(QRectF(0, y - metrics.height() / 2, r.left() - 6,
                              metrics.height()),
                       Qt.AlignRight | Qt.AlignVCenter, f"{pct}%")
        for temp in range(int(TEMP_MIN), int(TEMP_MAX) + 1, 10):
            x = self.to_px(temp, 0).x()
            p.drawText(QRectF(x - 20, r.bottom() + 3, 40, metrics.height()),
                       Qt.AlignHCenter | Qt.AlignTop, f"{temp}°")

    def _paint_limits(self, p, r, c) -> None:
        """Floor, ceiling and the zero-rpm cut-off, drawn where they will bite."""
        curve = self.curve
        pen = QPen(c["faint"], 1, Qt.DashLine)
        p.setPen(pen)
        if curve["min_percent"] > 0:
            y = self.to_px(TEMP_MIN, curve["min_percent"]).y()
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        if curve["max_percent"] < 100:
            y = self.to_px(TEMP_MIN, curve["max_percent"]).y()
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        if curve["zero_below"]:
            x = self.to_px(curve["zero_below"], 0).x()
            stop = QColor(c["faint"])
            stop.setAlphaF(0.5)
            p.setPen(QPen(stop, 1, Qt.DashLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            shade = QColor(c["text"])
            shade.setAlphaF(0.07)
            p.fillRect(QRectF(r.left(), r.top(), x - r.left(), r.height()), shade)

    def _effective(self, temp: float) -> float:
        return curves.effective_at(self.curve, temp)

    def _paint_curve(self, p, r, c) -> None:
        """The effective curve, sampled: the limits make it not a polyline."""
        steps = max(24, int(r.width() / 3))
        pts = [self.to_px(TEMP_MIN + (TEMP_MAX - TEMP_MIN) * i / steps,
                          self._effective(TEMP_MIN + (TEMP_MAX - TEMP_MIN) * i / steps))
               for i in range(steps + 1)]

        fill = QPainterPath()
        fill.addPolygon(QPolygonF([QPointF(r.left(), r.bottom())] + pts +
                                  [QPointF(r.right(), r.bottom())]))
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        top = QColor(c["curve"])
        top.setAlphaF(0.32)
        bottom = QColor(c["curve"])
        bottom.setAlphaF(0.04)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        p.fillPath(fill, grad)

        pen = QPen(c["curve"], 2.2)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))

    def _paint_trail(self, p, c) -> None:
        if len(self.trail) < 2:
            return
        for i, (temp, pct) in enumerate(self.trail):
            col = QColor(c["live"])
            col.setAlphaF(0.05 + 0.35 * (i / len(self.trail)))
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(self.to_px(temp, pct), 2.4, 2.4)

    def _paint_points(self, p, c) -> None:
        for i, (temp, pct) in enumerate(self.curve["points"]):
            centre = self.to_px(temp, pct)
            active = i in (self._drag, self._hover)
            radius = 6.5 if active else 5.0
            p.setPen(QPen(QColor("#ffffff"), 1.6))
            p.setBrush(c["curve"].lighter(120) if active else c["curve"])
            p.drawEllipse(centre, radius, radius)

    def _paint_live(self, p, r, c, metrics) -> None:
        if self.live_temp is None:
            return
        temp = max(TEMP_MIN, min(TEMP_MAX, self.live_temp))
        x = self.to_px(temp, 0).x()
        p.setPen(QPen(c["live"], 1.4, Qt.DashLine))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

        want = self._effective(temp)
        p.setPen(QPen(QColor("#ffffff"), 1.6))
        p.setBrush(c["live"])
        p.drawEllipse(self.to_px(temp, want), 5.5, 5.5)

        if self.live_percent is not None:
            actual = QColor(c["live"]).darker(140)
            p.setPen(QPen(actual, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(self.to_px(temp, self.live_percent), 8.0, 8.0)

        bits = [f"{self.live_temp:.0f}°C", f"curve {want:.0f}%"]
        if self.live_percent is not None:
            bits.append(f"now {self.live_percent:.0f}%")
        if self.live_rpm:
            bits.append(f"{self.live_rpm} rpm")
        text = "   ".join(bits)
        width = metrics.horizontalAdvance(text) + 12
        left = min(max(r.left(), x - width / 2), r.right() - width)
        box = QRectF(left, r.top() + 2, width, metrics.height() + 4)
        bg = QColor(self.palette().window().color())
        bg.setAlphaF(0.88)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QPen(c["text"]))
        p.drawText(box, Qt.AlignCenter, text)

    def _paint_hover(self, p, r, c, metrics) -> None:
        """What duty the pointer's temperature would ask for, while hovering."""
        if self._hover_pos is None or self._drag >= 0 or self._hover >= 0:
            return
        if not r.contains(self._hover_pos):
            return
        temp, _ = self.from_px(self._hover_pos)
        want = self._effective(temp)
        text = f"{temp:.0f}°C → {want:.0f}%"
        width = metrics.horizontalAdvance(text) + 10
        pos = self.to_px(temp, want)
        box = QRectF(min(pos.x() + 10, r.right() - width), pos.y() - 24,
                     width, metrics.height() + 4)
        bg = QColor(self.palette().window().color())
        bg.setAlphaF(0.85)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QPen(c["faint"]))
        p.drawText(box, Qt.AlignCenter, text)


class CalibrationPlot(QWidget):
    """The measured sweep: duty across, rpm up, with the point it started at."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.rows: list[dict] = []
        self.start_percent: int | None = None

    def set_result(self, result: dict) -> None:
        self.rows = result.get("table") or []
        self.start_percent = result.get("start_percent")
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        pal = self.palette()
        text = pal.windowText().color()
        faint = QColor(text)
        faint.setAlphaF(0.45)
        metrics = QFontMetrics(self.font())

        if not self.rows:
            p.setPen(QPen(faint))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No measurement yet — run a calibration.")
            p.end()
            return

        left = metrics.horizontalAdvance("9999") + 10
        bottom = metrics.height() + 8
        r = QRectF(left, 8, max(30.0, self.width() - left - 12),
                   max(30.0, self.height() - bottom - 12))
        top_rpm = max(1, max((row.get("rpm") or 0) for row in self.rows))

        grid = QColor(text)
        grid.setAlphaF(0.14)
        p.setPen(QPen(grid, 1))
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(QPen(faint))
        for i in range(5):
            y = r.bottom() - r.height() * i / 4
            p.drawText(QRectF(0, y - metrics.height() / 2, left - 6, metrics.height()),
                       Qt.AlignRight | Qt.AlignVCenter, str(int(top_rpm * i / 4)))

        pts = []
        for row in self.rows:
            x = r.left() + r.width() * row["percent"] / 100.0
            y = r.bottom() - r.height() * (row.get("rpm") or 0) / top_rpm
            pts.append(QPointF(x, y))

        p.setPen(QPen(QColor("#3daee9"), 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawPolyline(QPolygonF(pts))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3daee9"))
        for point in pts:
            p.drawEllipse(point, 3.0, 3.0)

        if self.start_percent is not None:
            x = r.left() + r.width() * self.start_percent / 100.0
            p.setPen(QPen(QColor("#f0883e"), 1.4, Qt.DashLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            label = f"starts at {self.start_percent}%"
            font = QFont(self.font())
            font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
            p.setFont(font)
            p.setPen(QPen(QColor("#f0883e")))
            p.drawText(QRectF(x + 4, r.top(), 120, metrics.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, label)

        p.setPen(QPen(faint))
        p.drawText(QRectF(r.left(), r.bottom() + 2, r.width(), metrics.height()),
                   Qt.AlignHCenter, "duty 0% → 100%")
        p.end()
