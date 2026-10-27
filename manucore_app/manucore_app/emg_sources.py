"""
ManuCore - data sources
Both sources hand the app the SAME thing: packets of
    (seq, t0_us, codes)   codes = uint16 array (20 samples, 8 channels)
so everything after this file is identical for simulated and real data.

  SimSource : realistic simulated sEMG (runs on any PC)
  BleSource : live packets from the ESP32 over Bluetooth LE (Pi or PC with Bluetooth)
"""
import queue
import struct
import threading
import time
import numpy as np
import config as C


# =====================================================================
#  Simulator
# =====================================================================
class SimSource:
    """
    Surface-EMG model: white noise -> 1st-order high-pass (fl) -> two 1st-order
    low-passes (fh). Fatigue = spectral compression (fl and fh scale down
    together), which lowers the median frequency, like slowing conduction
    velocity in a tiring muscle. Output is converted to ADS8688A codes exactly
    as the real hardware would produce them.
    """
    FL0, FH0 = 85.0, 170.0                      # ~105 Hz median frequency when fresh
    GRIP = np.array([.50, .42, .55, .85, .82, .72, .45, .50])   # full-grip effort per channel

    def __init__(self, demo="grip"):
        self.demo = demo
        self.q = queue.Queue()
        self.status = "Simulator"
        self.connected = True
        n = C.NCH
        self.hp = np.zeros(n); self.xp = np.zeros(n)
        self.l1 = np.zeros(n); self.l2 = np.zeros(n)
        self.ms = np.full(n, 1e-4)
        self.level = np.full(n, .04)
        self.fat = np.ones(n)
        self.seq = 0
        self.produced = 0
        self.t_start = None
        self.pending = []

    def start(self):
        self.t_start = time.perf_counter()

    def stop(self):
        pass

    def _target(self, t):
        if self.demo == "hold":                 # 2 s rest, 28 s hold, 15 s rest, repeat
            p = t % 45
            return self.GRIP if 2 <= p < 30 else np.full(C.NCH, .04)
        p = t % 8                               # 2 s rest, 3 s grip, 3 s rest
        return self.GRIP if 2 <= p < 5 else np.full(C.NCH, .04)

    def _sample(self, t):
        dt = 1.0 / C.FS
        self.level += (self._target(t) - self.level) * 0.004          # ~250 ms ramp
        act = np.clip(self.level - .15, 0, None) / .85
        self.fat -= 0.012 * act * dt                                   # fatigue
        rest = self.level < .2
        self.fat[rest] += (1 - self.fat[rest]) / 20 * dt               # recovery
        np.clip(self.fat, .6, 1, out=self.fat)

        RCl = 1 / (2 * np.pi * self.FL0 * self.fat); a = RCl / (RCl + dt)
        RCh = 1 / (2 * np.pi * self.FH0 * self.fat); al = dt / (RCh + dt)
        x = np.random.standard_normal(C.NCH)
        self.hp = a * (self.hp + x - self.xp); self.xp = x
        self.l1 += al * (self.hp - self.l1); self.l2 += al * (self.l1 - self.l2)
        self.ms += 0.002 * (self.l2 ** 2 - self.ms)
        unit = self.l2 / np.sqrt(self.ms + 1e-12)
        mv = C.FULL_SCALE_RMS_MV * self.level * (1 + .35 * (1 - self.fat)) * unit
        mv += 0.015 * np.random.standard_normal(C.NCH)                 # electronics noise floor
        volts = mv / 1000.0 * C.GAIN_TOTAL
        return np.clip(np.round(volts / (C.ADC_RANGE_V / 65536.0)) + C.ADC_MID_CODE, 0, 65535)

    def poll(self):
        """Generate every sample due since start (called from the UI timer)."""
        if self.t_start is None:
            return
        due = int((time.perf_counter() - self.t_start) * C.FS)
        due = min(due, self.produced + 400)    # don't burst if the app stalled
        while self.produced < due:
            t = self.produced / C.FS
            self.pending.append(self._sample(t))
            self.produced += 1
            if len(self.pending) == C.SAMPLES_PER_PACKET:
                codes = np.array(self.pending, dtype=np.uint16)
                t0_us = int((self.produced - C.SAMPLES_PER_PACKET) * 1e6 / C.FS)
                self.q.put((self.seq & 0xFFFFFFFF, t0_us, codes))
                self.seq += 1
                self.pending = []


# =====================================================================
#  Bluetooth LE (ESP32)
# =====================================================================
PACKET_FMT = "<II" + "H" * (C.SAMPLES_PER_PACKET * C.NCH)    # seq, t0_us, 160 samples
PACKET_LEN = struct.calcsize(PACKET_FMT)                     # 328 bytes


class BleSource:
    """Scans for the ESP32 by name, connects, subscribes, and reconnects on drop."""

    def __init__(self):
        self.q = queue.Queue()
        self.status = "Searching…"
        self.connected = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def poll(self):
        pass                                    # packets arrive from the BLE thread

    def _on_data(self, _sender, data):
        if len(data) != PACKET_LEN:
            return
        vals = struct.unpack(PACKET_FMT, data)
        codes = np.array(vals[2:], dtype=np.uint16).reshape(C.SAMPLES_PER_PACKET, C.NCH)
        self.q.put((vals[0], vals[1], codes))

    def _run(self):
        import asyncio
        try:
            from bleak import BleakScanner, BleakClient
        except ImportError:
            self.status = "bleak not installed"
            return

        async def main():
            while not self._stop.is_set():
                self.status, self.connected = "Searching…", False
                dev = await BleakScanner.find_device_by_name(C.BLE_NAME, timeout=5.0)
                if dev is None:
                    continue
                try:
                    async with BleakClient(dev) as client:
                        self.status, self.connected = "Connected", True
                        await client.start_notify(C.BLE_DATA_UUID, self._on_data)
                        while client.is_connected and not self._stop.is_set():
                            await asyncio.sleep(0.5)
                except Exception:
                    pass
                self.status, self.connected = "Reconnecting…", False
                await asyncio.sleep(1.0)

        asyncio.run(main())
