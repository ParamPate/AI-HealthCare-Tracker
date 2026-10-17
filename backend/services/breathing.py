import numpy as np
from scipy.signal import find_peaks

def analyze_breathing(wave, fs=20, baseline_amp=None, present=True):
    res = {"rr": None, "pattern": "unknown", "severity": "normal", "max_gap_s": 0.0}
    if not present or len(wave) < fs * 20:
        return res
    w = np.asarray(wave, float); w -= np.median(w)
    amp = baseline_amp or np.std(w)
    peaks, _ = find_peaks(w, distance=int(fs * 1.2), prominence=0.5 * amp)
    t = np.concatenate(([0], peaks / fs, [len(w) / fs]))
    res["max_gap_s"] = float(np.diff(t).max())
    if res["max_gap_s"] > 10:
        return {**res, "pattern": "apnea", "severity": "critical"}
    if len(peaks) < 3:
        return res
    ibi = np.diff(peaks) / fs
    rr = 60 / np.median(ibi)
    cv = np.std(ibi) / np.mean(ibi)
    shallow = baseline_amp is not None and np.mean(w[peaks]) < 0.5 * baseline_amp
    res["rr"] = float(rr)
    if rr > 22 and shallow:  res.update(pattern="rapid_shallow", severity="critical")
    elif rr > 28:            res.update(pattern="tachypnea", severity="critical")
    elif rr < 8:             res.update(pattern="bradypnea", severity="critical")
    elif cv > 0.4:
        res.update(pattern="irregular", severity="critical" if res["max_gap_s"] > 6 else "warning")
    elif rr > 22 or rr < 10: res.update(pattern="tachypnea" if rr > 22 else "bradypnea", severity="warning")
    else:                    res.update(pattern="normal")
    return res
