"""Panting: fast, shallow breathing that backend.breathing cannot see.

Panting (recordings/20261017-172315_panting_calib.parquet) runs at 92-103/min: too fast
for breathing.BAND and inside breathing.MOTION_BAND, so it shows up as movement or no
rhythm. Unlike fidgeting it is one sharp rhythm that most subcarriers share.
Kept out of breathing.py, whose hash the trained model checks.
"""
import numpy as np
from scipy import signal

BAND = (0.6, 2.5)    # Hz, 36 to 150 breaths/min
WINDOW_S = 8.0
MIN_BPM = 60.0       # demo panting 66-81/min; 50 let in shifting/heavy breathing at 54-57/min
CONC_MIN = 0.27      # band power within 0.08 Hz of the peak: panting 0.29-0.38, fidgeting <= 0.27
AGREE_MIN = 0.55     # subcarriers with their own peak there: panting 0.59-0.81, fidgeting <= 0.56
ACF_MIN = 0.4        # autocorrelation one cycle later: panting 0.46-0.81


def panting_rate(x: np.ndarray, fs: float) -> float | None:
    """Breaths/min if the last WINDOW_S of prepared subcarriers (breathing.prepare) show panting, else None."""
    n = int(WINDOW_S * fs)
    if len(x) < n:
        return None
    w = signal.detrend(x[-n:], axis=0)
    w = w / (w.std(axis=0) + 1e-12)
    f, p = signal.periodogram(w, fs=fs, window="hann", nfft=1024, axis=0)
    band = (f >= BAND[0]) & (f <= BAND[1])
    f, p = f[band], p[band]
    share = p / (p.sum(axis=0) + 1e-20)
    f0 = f[np.argmax(share.mean(axis=1))]
    near = np.abs(f - f0) <= 0.08
    conc = share[near].sum(axis=0).mean()
    agree = np.mean(np.abs(f[np.argmax(p, axis=0)] - f0) <= 0.1)
    top = np.argsort(share[near].sum(axis=0))[::-1][:max(5, w.shape[1] // 6)]
    sos = signal.butter(2, BAND, btype="band", fs=fs, output="sos")
    comb = signal.sosfiltfilt(sos, w[:, top], axis=0)
    c = comb @ np.linalg.svd(comb - comb.mean(axis=0), full_matrices=False)[2][0]
    ac = np.correlate(c, c, "full")[len(c) - 1:] / (c @ c + 1e-12)
    lag = int(round(fs / f0))
    acf = ac[max(1, lag - 2):lag + 3].max()
    ok = f0 * 60 >= MIN_BPM and conc >= CONC_MIN and agree >= AGREE_MIN and acf >= ACF_MIN
    return float(f0 * 60) if ok else None
