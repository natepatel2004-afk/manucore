"""
ManuCore - forearm heat map widget
Static arm drawing (assets/forearm.svg) + live electrode zones drawn on top.
Each zone glows with its channel's activation. Tapping a zone or its label
emits zoneClicked(channel).
"""
import json
import os
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                         QPen, QRadialGradient)
from PyQt5.QtSvg import QGraphicsSvgItem
from PyQt5.QtWidgets import (QGraphicsEllipseItem, QGraphicsPathItem, QGraphicsScene,
                             QGraphicsSimpleTextItem, QGraphicsView)
import config as C

VIEW = QRectF(-42, 18, 404, 690)       # same coordinate system as the SVG viewBox
VIEW_COMPACT = QRectF(-42, 60, 404, 590)  # trimmed top/bottom so the arm fills a short screen
TEXT_COMPACT = 1.3                        # labels drawn larger on the small screen

STOPS = [(0, (223, 228, 234)), (40, (244, 208, 111)), (70, (232, 137, 63)), (100, (201, 58, 42))]


def heat_color(pct):
    p = max(0.0, min(100.0, float(pct)))
    for (p0, c0), (p1, c1) in zip(STOPS, STOPS[1:]):
        if p <= p1:
            t = (p - p0) / (p1 - p0)
            return QColor(*[round(a + (b - a) * t) for a, b in zip(c0, c1)])
    return QColor(*STOPS[-1][1])


def _text(scene, s, x, y_baseline, px, weight, color, anchor="start"):
    f = QFont("Inter"); f.setPixelSize(int(round(px))); f.setWeight(weight)
    it = QGraphicsSimpleTextItem(s); it.setFont(f); it.setBrush(QBrush(QColor(color)))
    fm = QFontMetricsF(f); w = fm.horizontalAdvance(s)
    dx = {"start": 0, "middle": -w / 2, "end": -w}[anchor]
    it.setPos(x + dx, y_baseline - fm.ascent())
    it.setZValue(6)
    scene.addItem(it)
    return it, f


class Zone:
    def __init__(self, scene, z, k=1.0):
        self.z = z
        x, y, r = z["x"], z["y"], z["r"]
        self.glow = QGraphicsEllipseItem(); self.glow.setPen(QPen(Qt.NoPen)); self.glow.setPos(x, y)
        self.glow.setZValue(2); scene.addItem(self.glow)
        self.core = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r); self.core.setPos(x, y)
        ring = QPen(QColor("#ffffff"), 2.2)
        if z["deep"]:
            ring.setDashPattern([1.4, 1.1])
        self.core.setPen(ring); self.core.setZValue(3); scene.addItem(self.core)
        for ex, ey in z["el"]:
            d = QGraphicsEllipseItem(ex - 3.1, ey - 3.1, 6.2, 6.2)
            d.setBrush(QBrush(QColor("#fbfcfd"))); d.setPen(QPen(QColor("#5f6b7a"), 0.9))
            d.setZValue(4); scene.addItem(d)
        # leader line + dot
        x1, y1, x2, y2 = z["leader"]
        lp = QPainterPath(QPointF(x1, y1)); lp.lineTo(x2, y2)
        lead = QGraphicsPathItem(lp); lead.setPen(QPen(QColor("#9aa5b1"), 1)); lead.setZValue(1)
        scene.addItem(lead)
        dot = QGraphicsEllipseItem(x2 - 1.8, y2 - 1.8, 3.6, 3.6)
        dot.setBrush(QBrush(QColor("#9aa5b1"))); dot.setPen(QPen(Qt.NoPen)); scene.addItem(dot)
        # muscle code
        lx, ly, anchor, code = z["lc"]
        txt = code
        self.lc, _ = _text(scene, txt, lx, ly + (k - 1) * 4, 12.5 * k, QFont.Bold, "#1f2933", anchor)
        # % pill (grown away from the muscle code when k > 1)
        px, py, pw, ph = z["pill"]
        if k != 1.0:
            nw, nh = pw * k, ph * k
            if anchor == "start":                    # code is to the right: grow leftwards
                px -= nw - pw
            py -= (nh - ph) / 2; pw, ph = nw, nh
        pp = QPainterPath(); pp.addRoundedRect(QRectF(px, py, pw, ph), ph / 2, ph / 2)
        self.pill = QGraphicsPathItem(pp); self.pill.setPen(QPen(Qt.NoPen)); self.pill.setZValue(5)
        scene.addItem(self.pill)
        self.cx_pill = px + pw / 2
        self.zp, self.zp_font = _text(scene, "0%", self.cx_pill, py + ph / 2 + 3.6 * k, 10 * k, QFont.Bold,
                                      "#1f2933", "middle")
        self.hit = self.lc.sceneBoundingRect().united(QRectF(px, py, pw, ph)).adjusted(-4, -4, 4, 4)
        self.set_level(0)

    def set_level(self, pct):
        col = heat_color(pct)
        self.core.setBrush(QBrush(col))
        self.pill.setBrush(QBrush(col))
        r = 16 + pct * 0.2
        self.glow.setRect(-r, -r, 2 * r, 2 * r)
        g = QRadialGradient(QPointF(0, 0), r)
        inner = QColor(col); inner.setAlphaF(min(1.0, (0.25 + pct / 100 * 0.75) * 0.9))
        outer = QColor(col); outer.setAlpha(0)
        g.setColorAt(0, inner); g.setColorAt(1, outer)
        self.glow.setBrush(QBrush(g))
        s = f"{int(round(pct))}%"
        self.zp.setText(s)
        w = QFontMetricsF(self.zp_font).horizontalAdvance(s)
        self.zp.setX(self.cx_pill - w / 2)


class ForearmMap(QGraphicsView):
    zoneClicked = pyqtSignal(int)

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.view = VIEW_COMPACT if compact else VIEW
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent;")
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.scene_ = QGraphicsScene(VIEW, self)
        self.setScene(self.scene_)

        arm = QGraphicsSvgItem(os.path.join(C.ASSET_DIR, "forearm.svg"))
        arm.setPos(VIEW.x(), VIEW.y()); arm.setZValue(0)
        arm.setCacheMode(QGraphicsSvgItem.DeviceCoordinateCache)
        self.scene_.addItem(arm)

        with open(os.path.join(C.ASSET_DIR, "zones.json")) as f:
            self.zones = [Zone(self.scene_, z, TEXT_COMPACT if compact else 1.0) for z in json.load(f)]

    def set_levels(self, pcts):
        for z, p in zip(self.zones, pcts):
            z.set_level(p)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fitInView(self.view, Qt.KeepAspectRatio)

    def mousePressEvent(self, e):
        p = self.mapToScene(e.pos())
        for i, z in enumerate(self.zones):              # tap on a label / pill
            if z.hit.contains(p):
                self.zoneClicked.emit(i); return
        best, bd = -1, 1e9                              # tap near an electrode
        for i, z in enumerate(self.zones):
            d = ((z.z["x"] - p.x()) ** 2 + (z.z["y"] - p.y()) ** 2) ** 0.5
            if d < bd:
                best, bd = i, d
        if bd < 26:
            self.zoneClicked.emit(best)
