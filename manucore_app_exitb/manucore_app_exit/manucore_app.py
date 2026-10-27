"""
ManuCore display box app (PyQt5 + pyqtgraph)

    python manucore_app.py                 # simulator, grip cycle, windowed 1280x720
    python manucore_app.py --demo hold     # simulator, sustained grip (fatigue)
    python manucore_app.py --source ble    # live ESP32 data over Bluetooth
    python manucore_app.py --fullscreen    # kiosk mode (Raspberry Pi display)
    python manucore_app.py --compact       # 800x480 layout (small 7" screens); automatic
                                           # in full screen when the screen is under 600 px tall

Esc exits full screen; tap Exit (or press Ctrl+C in the terminal) to quit.
"""
import os
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PyQt5")   # keep pyqtgraph on PyQt5 (Pi OS may also have PyQt6)

import argparse
import csv
import datetime as dt
import signal
import sys
import time

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRectF
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen, QBrush, QLinearGradient
from PyQt5.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

import config as C
import emg_dsp as D
from emg_sources import BleSource, SimSource
from forearm_map import ForearmMap, heat_color

BLUE, TEXT, MUTED, FAINT = "#2F80ED", "#1A2230", "#6B7685", "#9AA4B2"
STATE_COLORS = {"ok": "#16A34A", "warn": "#E8A23B", "bad": "#E5484D", "muted": MUTED}

QSS = """
QWidget { font-family: Inter, "Segoe UI", Roboto, sans-serif; color: #1A2230; }
QMainWindow, #root { background: #F3F5F8; }
#header { background: #FFFFFF; border-bottom: 1px solid #E6E9EE; }
#brand { font-size: 16px; font-weight: 700; }
#sub { font-size: 12px; color: #6B7685; }
#chip { background: #F3F5F8; border-radius: 18px; padding: 0 14px; font-size: 13px; font-weight: 600; color: #6B7685; }
#chipTimer { background: #F3F5F8; border-radius: 18px; padding: 0 14px; font-size: 13px; font-weight: 600; }
QPushButton { border: none; border-radius: 12px; font-weight: 600; font-size: 14px; padding: 0 20px; min-height: 44px; }
QPushButton#start { background: #2F80ED; color: white; }
QPushButton#start:pressed { background: #1C64C8; }
QPushButton#start[rec="true"] { background: #E5484D; }
QPushButton#back { background: transparent; color: #2F80ED; padding: 0 10px; }
QPushButton#back:pressed { background: #EAF2FE; }
QPushButton#exit { background: #F3F5F8; color: #1A2230; border: 1px solid #E6E9EE; }
QPushButton#exit:pressed { background: #E6E9EE; }
#card, #tile { background: #FFFFFF; border: 1px solid #E6E9EE; border-radius: 14px; }
#tile:hover { border: 1px solid #BFD5F7; }
#cardTitle { font-size: 13px; font-weight: 700; }
#code { font-size: 13px; font-weight: 700; }
#chn { font-size: 11px; color: #9AA4B2; }
#pct { font-size: 14px; font-weight: 700; }
#name { font-size: 11px; color: #6B7685; }
#big { font-size: 40px; font-weight: 700; }
#k { font-size: 12px; color: #6B7685; }
#v { font-size: 15px; font-weight: 700; }
#status { font-size: 11px; color: #9AA4B2; }
#legend { font-size: 10px; color: #9AA4B2; }
"""

# Overrides for the compact 800x480 layout
QSS_COMPACT = """
#brand { font-size: 14px; }
#sub { font-size: 10px; }
#chip, #chipTimer { border-radius: 14px; padding: 0 10px; font-size: 11px; }
QPushButton { font-size: 12px; padding: 0 12px; min-height: 32px; border-radius: 10px; }
#card, #tile { border-radius: 10px; }
#cardTitle { font-size: 11px; }
#code { font-size: 12px; }
#chn { font-size: 9px; }
#pct { font-size: 12px; }
#name { font-size: 9px; }
#big { font-size: 30px; }
#k { font-size: 11px; }
#v { font-size: 13px; }
#status { font-size: 9px; }
#legend { font-size: 9px; }
"""


# ---------------------------------------------------------------- small widgets
class LevelBar(QWidget):
    def __init__(self, h=6, w=None):
        super().__init__()
        self.v, self.col = 0, QColor(BLUE)
        self.setFixedHeight(h)
        if w: self.setFixedWidth(w)

    def set(self, pct):
        self.v, self.col = pct, heat_color(pct); self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); r = self.rect()
        rad = r.height() / 2
        p.setPen(Qt.NoPen); p.setBrush(QColor("#EEF1F5")); p.drawRoundedRect(r, rad, rad)
        w = r.width() * max(0, min(100, self.v)) / 100
        if w > 1:
            p.setBrush(self.col); p.drawRoundedRect(QRectF(0, 0, w, r.height()), rad, rad)


class HeatLegend(QWidget):
    def __init__(self, h=8):
        super().__init__(); self.setFixedHeight(h)

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), 0)
        for pos, pct in ((0, 0), (.4, 40), (.7, 70), (1, 100)):
            g.setColorAt(pos, heat_color(pct))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawRoundedRect(self.rect(), 4, 4)


class Dot(QWidget):
    def __init__(self, color):
        super().__init__(); self.setFixedSize(10, 10); self.c = QColor(color)

    def set(self, color):
        self.c = QColor(color); self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
        p.setBrush(self.c); p.drawEllipse(1, 1, 8, 8)


class Logo(QWidget):
    def __init__(self, size=38):
        super().__init__(); self.setFixedSize(size, size); self.k = size / 38

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing); p.scale(self.k, self.k)
        g = QLinearGradient(0, 0, 38, 38); g.setColorAt(0, QColor("#3B8BF5")); g.setColorAt(1, QColor("#1C64C8"))
        p.setPen(Qt.NoPen); p.setBrush(QBrush(g)); p.drawRoundedRect(0, 0, 38, 38, 11, 11)
        path = QPainterPath(); pts = [(7, 19), (12, 19), (15, 12), (20, 26), (23, 15), (25, 19), (31, 19)]
        path.moveTo(*pts[0]); [path.lineTo(*q) for q in pts[1:]]
        p.setPen(QPen(QColor("white"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def card():
    f = QFrame(); f.setObjectName("card"); return f


def lab(text, name=None):
    l = QLabel(text)
    if name: l.setObjectName(name)
    return l


def quiet_plot(show_axes=False):
    w = pg.PlotWidget(background=None)
    w.setMenuEnabled(False); w.setMouseEnabled(False, False); w.hideButtons()
    pi = w.getPlotItem()
    if not show_axes:
        pi.hideAxis("left"); pi.hideAxis("bottom")
    pi.getViewBox().setDefaultPadding(0)
    w.setAttribute(Qt.WA_TransparentForMouseEvents)
    w.setStyleSheet("background: transparent;")
    w.setMinimumSize(10, 10)                       # let small screens shrink the plots
    return w


# ---------------------------------------------------------------- channel tile
class Tile(QFrame):
    clicked = pyqtSignal(int)

    def __init__(self, i, compact=False):
        super().__init__(); self.i = i; self.setObjectName("tile"); self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self); v.setSpacing(1 if compact else 2)
        v.setContentsMargins(*((8, 5, 8, 5) if compact else (12, 9, 12, 9)))
        h = QHBoxLayout(); h.setSpacing(6)
        h.addWidget(lab(C.CHANNELS[i][0], "code")); h.addWidget(lab(f"Ch {i+1}", "chn")); h.addStretch()
        self.pct = lab("0%", "pct"); h.addWidget(self.pct); v.addLayout(h)
        self.plot = quiet_plot()
        self.plot.setYRange(-C.WAVE_RANGE_MV, C.WAVE_RANGE_MV, padding=0)
        self.plot.setXRange(0, 399, padding=0)
        self.curve = self.plot.plot(pen=pg.mkPen(BLUE, width=1.6))
        v.addWidget(self.plot, 1)
        f = QHBoxLayout(); f.addWidget(lab(C.CHANNELS[i][1], "name")); f.addStretch()
        self.bar = LevelBar(5 if compact else 6, 40 if compact else 56); f.addWidget(self.bar, 0, Qt.AlignVCenter); v.addLayout(f)

    def mousePressEvent(self, _):
        self.clicked.emit(self.i)


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, source, compact=False):
        super().__init__()
        self.src = source
        self.compact = compact
        self.base_size = (800, 480) if compact else (1280, 720)
        self.ring = D.RingBuffer()
        self.fat = D.FatigueTracker()
        self.pct = np.zeros(C.NCH)
        self.rms_mv = np.zeros(C.NCH)
        self.mdf_raw = np.full(C.NCH, np.nan)
        self.psd_disp = None
        self.pmax = 1e-12
        self.sel = 0
        self.last_seq = None
        self.lost = 0
        self.stream_t = 0.0                       # seconds of data received
        self.rate_hist = []
        self.recording = False
        self.csv_file = None
        self.csv = None
        self.sess_samples = 0
        self.t_session = 0.0
        self.last_rms = self.last_fft = 0.0

        self.setWindowTitle("ManuCore")
        root = QWidget(); root.setObjectName("root"); self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self._header())
        self.stack = QStackedWidget(); outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._home()); self.stack.addWidget(self._detail())
        outer.addWidget(self._statusbar())
        self.show_home()

        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(33)
        self.src.start()

    # ---------- layout pieces
    def _header(self):
        c = self.compact
        chip_h = 28 if c else 36
        hdr = QFrame(); hdr.setObjectName("header"); hdr.setFixedHeight(46 if c else 64)
        h = QHBoxLayout(hdr); h.setSpacing(8 if c else 12)
        h.setContentsMargins(*((10, 6, 10, 6) if c else (18, 10, 18, 10)))
        self.back = QPushButton("‹  Back"); self.back.setObjectName("back"); self.back.clicked.connect(self.show_home)
        h.addWidget(self.back)
        h.addWidget(Logo(28 if c else 38))
        t = QVBoxLayout(); t.setSpacing(0); t.addWidget(lab("ManuCore", "brand"))
        self.sub = lab("", "sub"); t.addWidget(self.sub); h.addLayout(t)
        h.addStretch()
        chip = QFrame(); chip.setObjectName("chip"); chip.setFixedHeight(chip_h)
        ch = QHBoxLayout(chip); ch.setContentsMargins(*((10, 0, 10, 0) if c else (14, 0, 14, 0))); ch.setSpacing(6 if c else 8)
        self.dot = Dot("#16A34A"); ch.addWidget(self.dot)
        self.conn = lab("…"); self.conn.setStyleSheet(f"font-size:{11 if c else 13}px;font-weight:600;color:#6B7685;background:transparent")
        ch.addWidget(self.conn); h.addWidget(chip)
        self.timer_lbl = lab("00:00", "chipTimer"); self.timer_lbl.setFixedHeight(chip_h); h.addWidget(self.timer_lbl)
        self.start_btn = QPushButton(self._btn_text(False)); self.start_btn.setObjectName("start")
        self.start_btn.setMinimumWidth(96 if c else 170); self.start_btn.clicked.connect(self.toggle_session)
        h.addWidget(self.start_btn)
        self.exit_btn = QPushButton("✕  Exit"); self.exit_btn.setObjectName("exit")
        self.exit_btn.setMinimumWidth(72 if c else 100); self.exit_btn.clicked.connect(self.ask_exit)
        h.addWidget(self.exit_btn)
        return hdr

    def _btn_text(self, rec):
        if self.compact:
            return "■  Stop" if rec else "▶  Start"
        return "■  Stop session" if rec else "▶  Start session"

    def _home(self):
        c = self.compact
        w = QWidget(); h = QHBoxLayout(w); h.setSpacing(8 if c else 12)
        h.setContentsMargins(*((8, 6, 8, 2) if c else (18, 16, 18, 6)))
        grid = QGridLayout(); grid.setSpacing(6 if c else 10); grid.setContentsMargins(0, 0, 0, 0)
        self.tiles = []
        for i in range(C.NCH):
            t = Tile(i, c); t.clicked.connect(self.open_detail)
            grid.addWidget(t, i // 2, i % 2); self.tiles.append(t)
        gw = QWidget(); gw.setLayout(grid); h.addWidget(gw, 58 if c else 56)
        hc = card(); v = QVBoxLayout(hc); v.setSpacing(3 if c else 6)
        v.setContentsMargins(*((8, 6, 8, 4) if c else (16, 14, 16, 12)))
        v.addWidget(lab("Heat map · right forearm" if c else "Heat map · right forearm, palm up", "cardTitle"))
        self.map = ForearmMap(compact=c); self.map.zoneClicked.connect(self.open_detail); v.addWidget(self.map, 1)
        v.addWidget(HeatLegend(6 if c else 8))
        lg = QHBoxLayout(); lg.addWidget(lab("Rest", "legend")); lg.addStretch(); lg.addWidget(lab("Moderate", "legend"))
        lg.addStretch(); lg.addWidget(lab("High", "legend")); v.addLayout(lg)
        h.addWidget(hc, 42 if c else 44)
        return w

    def _detail(self):
        c = self.compact
        m = (10, 7, 10, 7) if c else (16, 14, 16, 14)
        w = QWidget(); h = QHBoxLayout(w); h.setSpacing(8 if c else 12)
        h.setContentsMargins(*((8, 6, 8, 2) if c else (18, 16, 18, 6)))
        left = QVBoxLayout(); left.setSpacing(8 if c else 12); left.setContentsMargins(0, 0, 0, 0)
        a = card(); av = QVBoxLayout(a); av.setContentsMargins(*m); av.setSpacing(2 if c else 6)
        av.addWidget(lab("Activation", "cardTitle"))
        bh = QHBoxLayout(); bh.addStretch(); self.big = lab("0", "big"); bh.addWidget(self.big)
        u = lab("%", "k"); bh.addWidget(u, 0, Qt.AlignBottom); bh.addStretch(); av.addLayout(bh)
        self.big_bar = LevelBar(8 if c else 10); av.addWidget(self.big_bar)
        left.addWidget(a)
        d = card(); dv = QVBoxLayout(d); dv.setContentsMargins(*m); dv.setSpacing(0)
        dv.addWidget(lab("Channel data", "cardTitle")); dv.addSpacing(2 if c else 6)
        self.vals = {}
        for key in ("Signal (RMS)", "Median frequency", "Fatigue state", "Sample rate", "Packets lost"):
            row = QHBoxLayout(); row.setContentsMargins(*((2, 4, 2, 4) if c else (2, 8, 2, 8)))
            row.addWidget(lab(key, "k")); row.addStretch(); val = lab("—", "v"); row.addWidget(val)
            dv.addLayout(row)
            line = QFrame(); line.setFixedHeight(1); line.setStyleSheet("background:#F0F2F5"); dv.addWidget(line)
            self.vals[key] = val
        dv.addSpacing(4 if c else 8); dv.addWidget(lab("Electrode site", "k"))
        self.site = lab("—"); self.site.setStyleSheet(f"font-size:{11 if c else 13}px;font-weight:700"); self.site.setWordWrap(True)
        dv.addWidget(self.site); dv.addStretch()
        left.addWidget(d, 1)
        lw = QWidget(); lw.setLayout(left); lw.setFixedWidth(200 if c else 240); h.addWidget(lw)

        pm = (10, 6, 8, 4) if c else (16, 12, 12, 8)
        right = QVBoxLayout(); right.setSpacing(8 if c else 12); right.setContentsMargins(0, 0, 0, 0)
        wc = card(); wv = QVBoxLayout(wc); wv.setContentsMargins(*pm); wv.setSpacing(2 if c else 6)
        wv.addWidget(lab("Time domain  ·  last 1.6 s", "cardTitle"))
        self.wave = quiet_plot(show_axes=True)
        pi = self.wave.getPlotItem(); pi.hideAxis("bottom"); pi.showGrid(x=False, y=True, alpha=0.12)
        pi.getAxis("left").setLabel("mV"); pi.getAxis("left").setTextPen(FAINT); pi.getAxis("left").setPen(FAINT)
        self.wave.setYRange(-C.WAVE_RANGE_MV, C.WAVE_RANGE_MV, padding=0)
        self.wave.setXRange(0, 1599, padding=0)
        self.wave_curve = self.wave.plot(pen=pg.mkPen(BLUE, width=1.4))
        wv.addWidget(self.wave, 1); right.addWidget(wc, 1)

        sc = card(); sv = QVBoxLayout(sc); sv.setContentsMargins(*pm); sv.setSpacing(2 if c else 6)
        sh = QHBoxLayout(); sh.addWidget(lab("Frequency spectrum  ·  FFT" if c else
                                             "Frequency spectrum  ·  FFT, 512-pt Welch, 1 s window", "cardTitle"))
        sh.addStretch(); self.spec_tag = lab("", "k"); sh.addWidget(self.spec_tag); sv.addLayout(sh)
        self.spec = quiet_plot(show_axes=True)
        pi = self.spec.getPlotItem(); pi.hideAxis("left")
        ax = pi.getAxis("bottom"); ax.setTextPen(FAINT); ax.setPen(FAINT)
        ax.setTicks([[(f, f"{f} Hz" if f in (0, 500) else str(f)) for f in range(0, 501, 100)]])
        self.spec.setXRange(-4, 504, padding=0); self.spec.setYRange(0, 1.1, padding=0)
        self.nb = 64; self.per = (D.NFFT // 2) // self.nb
        xs = (np.arange(self.nb) + 0.5) * self.per * (C.FS / D.NFFT)
        self.bars = pg.BarGraphItem(x=xs, height=np.zeros(self.nb), width=self.per * (C.FS / D.NFFT) * 0.82,
                                    brush="#8AB4F8", pen=pg.mkPen(None))
        self.spec.addItem(self.bars)
        self.line_start = pg.InfiniteLine(angle=90, pen=pg.mkPen("#9AA4B2", width=1.3, style=Qt.DashLine),
                                          label="start {value:.0f} Hz", labelOpts={"position": .93, "color": "#9AA4B2", "anchors": [(0, 0), (0, 0)]})
        self.line_now = pg.InfiniteLine(angle=90, pen=pg.mkPen("#E5484D", width=1.6, style=Qt.DashLine),
                                        label="now {value:.0f} Hz", labelOpts={"position": .82, "color": "#E5484D", "anchors": [(0, 0), (0, 0)]})
        self.spec.addItem(self.line_start); self.spec.addItem(self.line_now)
        sv.addWidget(self.spec, 1); right.addWidget(sc, 1)
        if c:                                             # smaller axis text on the small screen
            tf = QFont("Inter"); tf.setPixelSize(9)
            for ax in (self.wave.getPlotItem().getAxis("left"), self.spec.getPlotItem().getAxis("bottom")):
                ax.setStyle(tickFont=tf)
            self.wave.getPlotItem().getAxis("left").setWidth(34)
            self.wave.getPlotItem().getAxis("left").setLabel("mV", **{"font-size": "9px"})
            for ln, pos in ((self.line_start, .9), (self.line_now, .68)):
                ln.label.setFont(tf); ln.label.setPosition(pos)
        rw = QWidget(); rw.setLayout(right); h.addWidget(rw, 1)
        return w

    def _statusbar(self):
        c = self.compact
        s = QWidget(); s.setFixedHeight(20 if c else 30)
        h = QHBoxLayout(s); h.setSpacing(12 if c else 18)
        h.setContentsMargins(*((10, 0, 10, 4) if c else (18, 0, 18, 6)))
        self.st_state = lab("Idle", "status"); h.addWidget(self.st_state)
        self.st_src = lab("", "status"); h.addWidget(self.st_src)
        h.addWidget(lab(f"{C.NCH} ch @ {C.FS // 1000} kHz", "status"))
        self.st_csv = lab("No active file", "status"); h.addWidget(self.st_csv); h.addStretch()
        return s

    # ---------- navigation
    def show_home(self):
        self.stack.setCurrentIndex(0); self.back.hide(); self.sub.setText(f"{C.NCH} channels · heat map")

    def open_detail(self, i):
        self.sel = i; self.stack.setCurrentIndex(1); self.back.show()
        self.sub.setText(f"Channel {i+1} · {C.CHANNELS[i][0]}"); self.site.setText(C.CHANNELS[i][1])
        self.pmax = 1e-12

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal(); self.resize(*self.base_size)

    # ---------- session / CSV
    def toggle_session(self):
        if not self.recording:
            os.makedirs(C.SESSION_DIR, exist_ok=True)
            name = dt.datetime.now().strftime("session_%Y%m%d_%H%M%S.csv")
            path = os.path.join(C.SESSION_DIR, name)
            self.csv_file = open(path, "w", newline="")
            self.csv = csv.writer(self.csv_file)
            self.csv.writerow(["time_s", "packet_seq"] + [f"{c[0]}_mV" for c in C.CHANNELS])
            self.sess_samples = 0; self.t_session = time.perf_counter(); self.lost = 0
            self.fat.reset()
            self.recording = True
            self.start_btn.setText(self._btn_text(True)); self.st_csv.setText(path)
            self.st_state.setText("Recording"); self.st_state.setStyleSheet("color:#E5484D")
        else:
            self.recording = False
            self.csv_file.close(); self.csv_file = None; self.csv = None
            self.start_btn.setText(self._btn_text(False)); self.st_csv.setText("No active file")
            self.st_state.setText("Idle"); self.st_state.setStyleSheet("")
            self.timer_lbl.setText("00:00")
        self.start_btn.setProperty("rec", self.recording)
        self.start_btn.style().unpolish(self.start_btn); self.start_btn.style().polish(self.start_btn)

    def ask_exit(self):
        msg = "Stop recording and exit ManuCore?" if self.recording else "Exit ManuCore?"
        box = QMessageBox(self); box.setWindowTitle("Exit"); box.setText(msg)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel); box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Exit"); box.button(QMessageBox.Cancel).setText("Cancel")
        box.setStyleSheet("QPushButton { min-width: 110px; min-height: 44px; background:#F3F5F8; border:1px solid #E6E9EE; }")
        if box.exec_() == QMessageBox.Yes:
            self.close()

    def closeEvent(self, e):
        if self.csv_file:
            self.csv_file.close()
        self.src.stop()
        super().closeEvent(e)

    # ---------- main loop (~30 Hz)
    def tick(self):
        self.src.poll()
        n_new = 0
        while not self.src.q.empty():
            seq, _t0, codes = self.src.q.get_nowait()
            if self.last_seq is not None and seq != (self.last_seq + 1) & 0xFFFFFFFF:
                self.lost += (seq - self.last_seq - 1) & 0xFFFFFFFF
            self.last_seq = seq
            mv = D.codes_to_mv(codes)                         # (20, 8)
            self.ring.append(mv)
            n_new += mv.shape[0]
            if self.recording:
                for k in range(mv.shape[0]):
                    t = self.sess_samples / C.FS
                    self.csv.writerow([f"{t:.3f}", seq] + [f"{v:.4f}" for v in mv[k]])
                    self.sess_samples += 1
                self.csv_file.flush()
        self.stream_t += n_new / C.FS
        now = time.perf_counter()
        self.rate_hist.append((now, n_new))
        self.rate_hist = [(t, n) for t, n in self.rate_hist if now - t < 2.0]

        # header status
        self.conn.setText(self.src.status)
        self.dot.set("#2F80ED" if isinstance(self.src, SimSource) else ("#16A34A" if self.src.connected else "#E8A23B"))
        if self.recording:
            s = int(now - self.t_session); self.timer_lbl.setText(f"{s // 60:02d}:{s % 60:02d}")

        if self.ring.count < D.WELCH_LEN:
            return

        if now - self.last_rms > 0.1:                         # RMS every 100 ms (last 250 ms)
            self.last_rms = now
            self.rms_mv = D.rms(self.ring.last(250))
            self.pct = np.minimum(100, self.rms_mv / C.FULL_SCALE_RMS_MV * 100)
            for i, t in enumerate(self.tiles):
                t.pct.setText(f"{int(self.pct[i])}%"); t.bar.set(self.pct[i])
            self.map.set_levels(self.pct)

        if now - self.last_fft > 0.25:                        # FFT every 250 ms (last ~1 s)
            self.last_fft = now
            self.psd = D.welch_psd(self.ring.last(D.WELCH_LEN))
            self.mdf_raw = D.median_frequency(self.psd)
            self.fat.update(self.stream_t, self.pct, self.mdf_raw)
            sm = (np.roll(self.psd, 1, axis=1) + self.psd + np.roll(self.psd, -1, axis=1)) / 3
            self.psd_disp = sm if self.psd_disp is None else 0.65 * self.psd_disp + 0.35 * sm

        if self.stack.currentIndex() == 0:
            wave = self.ring.last(1600)[:, ::4]
            for i, t in enumerate(self.tiles):
                t.curve.setData(wave[i])
        else:
            self._update_detail()

    def _update_detail(self):
        i = self.sel
        self.big.setText(f"{int(self.pct[i])}"); self.big_bar.set(self.pct[i])
        self.vals["Signal (RMS)"].setText(f"{self.rms_mv[i]:.2f} mV")
        steady = bool(self.fat.steady[i])
        self.vals["Median frequency"].setText(f"{self.fat.mdf[i]:.0f} Hz" if steady else "—")
        txt, kind = self.fat.label(i)
        self.vals["Fatigue state"].setText(txt)
        self.vals["Fatigue state"].setStyleSheet(f"color:{STATE_COLORS[kind]}")
        rate = sum(n for _, n in self.rate_hist) / 2.0
        self.vals["Sample rate"].setText(f"{rate:.0f} Hz")
        self.vals["Packets lost"].setText(str(self.lost))
        self.wave_curve.setData(self.ring.last(1600)[i])
        if self.psd_disp is not None:
            p = self.psd_disp[i, :self.nb * self.per].reshape(self.nb, self.per).mean(axis=1)
            self.pmax = max(self.pmax * 0.985, p.max())
            self.bars.setOpts(height=p / self.pmax)
        base = self.fat.baseline[i]
        self.line_start.setVisible(not np.isnan(base))
        if not np.isnan(base): self.line_start.setValue(base)
        self.line_now.setVisible(steady)
        if steady: self.line_now.setValue(self.fat.mdf[i])
        self.spec_tag.setText(f"median {self.fat.mdf[i]:.0f} Hz" if steady
                              else ("median — (settling)" if self.fat.active[i] else "median — (rest)"))


def main():
    ap = argparse.ArgumentParser(description="ManuCore display box")
    ap.add_argument("--source", choices=["sim", "ble"], default=C.SOURCE)
    ap.add_argument("--demo", choices=["grip", "hold"], default=C.SIM_DEMO)
    ap.add_argument("--fullscreen", action="store_true")
    ap.add_argument("--compact", action="store_true", help="800x480 layout for small screens")
    args = ap.parse_args()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    for f in ("Inter-Regular.otf", "Inter-Medium.otf", "Inter-SemiBold.otf", "Inter-Bold.otf"):
        QFontDatabase.addApplicationFont(os.path.join(C.ASSET_DIR, f))
    app.setFont(QFont("Inter", 10))
    scr = app.primaryScreen().size()
    compact = args.compact or (args.fullscreen and scr.height() < 600)
    app.setStyleSheet(QSS + (QSS_COMPACT if compact else ""))
    pg.setConfigOptions(antialias=True)

    src = SimSource(args.demo) if args.source == "sim" else BleSource()
    win = MainWindow(src, compact)
    # Ctrl+C in the terminal closes the app cleanly (saves any open CSV)
    signal.signal(signal.SIGINT, lambda *_: (win.close(), app.quit()))
    win._sig_timer = QTimer(); win._sig_timer.timeout.connect(lambda: None); win._sig_timer.start(200)
    win.st_src.setText("Source: simulator" if args.source == "sim" else f"BLE: {C.BLE_NAME}")
    if args.fullscreen:
        win.showFullScreen()
    else:
        win.resize(*win.base_size); win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
