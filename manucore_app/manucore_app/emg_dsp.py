"""
ManuCore - signal processing
  * raw ADC codes -> millivolts at the electrodes
  * RMS activation
  * Welch FFT (512-pt, Hann, 50% overlap, ~1 s window) -> power spectrum
  * median frequency (20-450 Hz) and fatigue state
Everything works on all 8 channels at once with numpy.
"""
import numpy as np
import config as C

NFFT = 512
WELCH_LEN = 1024                     # 3 segments of 512 with 50% overlap
BUF = 4096                           # ring buffer length per channel (~4 s)
HANN = np.hanning(NFFT)
FREQS = np.fft.rfftfreq(NFFT, 1.0 / C.FS)
BAND = (FREQS >= 20) & (FREQS <= 450)


def codes_to_mv(codes):
    """ADC codes (uint16) -> mV at the electrodes, using ADC range and total gain."""
    volts_at_adc = (codes.astype(np.float64) - C.ADC_MID_CODE) * (C.ADC_RANGE_V / 65536.0)
    return volts_at_adc / C.GAIN_TOTAL * 1000.0


class RingBuffer:
    """Fixed-size circular buffer, shape (NCH, BUF)."""

    def __init__(self):
        self.buf = np.zeros((C.NCH, BUF))
        self.wi = 0
        self.count = 0

    def append(self, block):                 # block: (n, NCH) in mV
        n = block.shape[0]
        idx = (self.wi + np.arange(n)) % BUF
        self.buf[:, idx] = block.T
        self.wi = (self.wi + n) % BUF
        self.count += n

    def last(self, n):                       # -> (NCH, n), oldest first
        idx = (self.wi - n + np.arange(n)) % BUF
        return self.buf[:, idx]


def rms(x):
    return np.sqrt(np.mean(x * x, axis=1))


def welch_psd(x):
    """x: (NCH, 1024) -> PSD (NCH, 257)."""
    p = np.zeros((x.shape[0], NFFT // 2 + 1))
    for st in range(0, WELCH_LEN - NFFT + 1, NFFT // 2):
        seg = x[:, st:st + NFFT] * HANN
        p += np.abs(np.fft.rfft(seg, axis=1)) ** 2
    return p


def median_frequency(psd):
    """Frequency that splits 20-450 Hz power in half, per channel."""
    f = FREQS[BAND]
    p = psd[:, BAND]
    cum = np.cumsum(p, axis=1)
    half = cum[:, -1:] / 2.0
    k = np.argmax(cum >= half, axis=1)
    out = np.empty(psd.shape[0])
    df = FREQS[1] - FREQS[0]
    for ch, kk in enumerate(k):              # linear interpolation inside the bin
        prev = cum[ch, kk - 1] if kk > 0 else 0.0
        frac = (half[ch, 0] - prev) / max(p[ch, kk], 1e-30)
        out[ch] = f[kk] - df / 2 + frac * df
    return out


class FatigueTracker:
    """
    Per-channel median-frequency fatigue tracking.
      - only measured during a steady contraction (FFT window fully inside it)
      - baseline = average of the first second of steady contraction
      - Fresh / Tiring / Fatigued from % drop vs baseline, with hysteresis
    """
    def __init__(self):
        self.reset()

    def reset(self):
        n = C.NCH
        self.active = np.zeros(n, bool)
        self.steady = np.zeros(n, bool)
        self.act_since = np.zeros(n)
        self.mdf = np.full(n, np.nan)
        self.base_samples = [[] for _ in range(n)]
        self.baseline = np.full(n, np.nan)
        self.state = np.zeros(n, int)          # 0 fresh, 1 tiring, 2 fatigued

    def update(self, t, pct, mdf_raw):
        was = self.active.copy()
        self.active = pct >= C.ACTIVE_PCT
        started = self.active & ~was
        self.act_since[started] = t
        self.steady = self.active & (t - self.act_since > 1.1)
        for ch in np.where(self.steady)[0]:
            f = mdf_raw[ch]
            self.mdf[ch] = f if np.isnan(self.mdf[ch]) else 0.87 * self.mdf[ch] + 0.13 * f
            if np.isnan(self.baseline[ch]):
                self.base_samples[ch].append(f)
                if len(self.base_samples[ch]) >= 4:
                    self.baseline[ch] = float(np.mean(self.base_samples[ch]))
            else:
                drop = (self.baseline[ch] - self.mdf[ch]) / self.baseline[ch] * 100
                up = 13 if self.state[ch] == 2 else 15
                mid = 6 if self.state[ch] >= 1 else 8
                self.state[ch] = 2 if drop > up else 1 if drop > mid else 0

    def label(self, ch):
        if not self.steady[ch]:
            if self.active[ch]:
                return "Measuring…", "muted"
            return ("Resting" if not np.isnan(self.baseline[ch]) else "—"), "muted"
        if np.isnan(self.baseline[ch]):
            return "Measuring…", "muted"
        return ["Fresh", "Tiring", "Fatigued"][self.state[ch]], ["ok", "warn", "bad"][self.state[ch]]
