"""Breathing rate from CSI amplitudes, with movement kept out.

Breathing moves the chest a few millimetres, slowly and smoothly. Fidgeting,
laughing, and posture shifts are bigger and sharper, and a bandpass filter turns
any sudden jump into a fake slow wave. So movement is handled before filtering:

1. prepare()           cancel receiver gain, drop spikes, average onto a uniform grid
2. motion_score()      energy above 1 Hz, where breathing has almost none (calm is about 1)
   motion_mask()       where that score is high, padded on both sides
3. clean()             freeze the signal during movement (a posture shift becomes a flat
                       join), subtract a rolling median (slow drift), scale robustly,
                       clip extremes, and fade movement stretches to zero
4. breathing_signal()  pick subcarriers by how rhythmic they are at the common
                       frequency, not by how much they change, and combine them
5. estimate_rate()     most prominent rhythm from 3 to 30 breaths/min, a verdict on
                       whether it is steady, and a note when it might be "two bumps per
                       breath" (energy at half its frequency)

All functions work on whole arrays (offline). Times are seconds on the uniform grid.
"""
from dataclasses import dataclass

import numpy as np
from scipy import ndimage, signal

FS = 20.0                 # Hz, uniform grid
BAND = (0.05, 0.5)        # Hz, 3 to 30 breaths/min
MOTION_BAND = (1.0, 5.0)  # Hz, breathing has almost no energy here
MOTION_THRESHOLD = 2.0    # motion score above this counts as movement (calm is 0.4 to 1.2)
MOTION_PAD_S = 1.5        # also ignore this long before and after movement
MIN_CALM_S = 3.0          # calm gaps shorter than this between movements count as movement
DETREND_S = 30.0          # rolling-median window, longer than the slowest breath (20 s)
SPECTRUM_S = 60.0         # longest Welch segment
WINDOW_S = 30.0           # sliding windows for the steadiness check
RHYTHM_TOL_HZ = 0.02      # about 1.2 breaths/min
HALF_NOTE_MIN = 0.3       # power at half the rhythm's frequency (relative) worth a "two bumps?" note
SHARE_MIN = 0.3           # verdict: share of band power at the rhythm
CONSISTENCY_MIN = 0.6     # verdict: share of sliding windows that agree on the rhythm
MIN_CALM_TOTAL_S = 15.0   # verdict: calm data needed at all
MIN_CYCLES = 3.0          # verdict: a rhythm needs this many full cycles of calm data
CONTRAST_MIN = 1.8        # verdict: consensus at the rhythm vs its neighbourhood (noise: up to ~1.45)
EDGE_S = 2.0              # fade in/out at the recording's start and end


def prepare(t: np.ndarray, amp: np.ndarray, fs: float = FS):
    """Irregular packets (t in s, amp shape (n, K)) -> (grid, x, kept subcarrier indices).

    Drops null subcarriers, divides each packet by its mean amplitude (cancels receiver
    gain jumps), removes single-packet spikes, and averages packets into 1/fs bins.
    """
    mean = amp.mean(axis=0)
    kept = np.flatnonzero(mean > 0.1 * np.median(mean))
    x = amp[:, kept]
    x = x / x.mean(axis=1, keepdims=True)
    x = ndimage.median_filter(x, size=(5, 1), mode="nearest")

    bins = np.floor((t - t[0]) * fs).astype(int)
    n = bins[-1] + 1
    sums = np.zeros((n, x.shape[1]))
    np.add.at(sums, bins, x)
    counts = np.bincount(bins, minlength=n)
    filled = counts > 0
    out = sums[filled] / counts[filled, None]
    grid = t[0] + (np.arange(n) + 0.5) / fs
    if not filled.all():  # bins with no packets: interpolate
        out = np.column_stack([np.interp(grid, grid[filled], out[:, k]) for k in range(out.shape[1])])
    return grid, out, kept


def motion_score(x: np.ndarray, fs: float = FS) -> np.ndarray:
    """Fast-change energy per sample, relative to each subcarrier's calm noise (calm is about 1)."""
    sos = signal.butter(4, MOTION_BAND, btype="band", fs=fs, output="sos")
    fast = signal.sosfiltfilt(sos, x, axis=0)
    # The 25th percentile of |noise| is 0.3186 std for Gaussian noise. Using a low
    # percentile keeps this a calm-period estimate even if most of the data is movement.
    noise = np.percentile(np.abs(fast), 25, axis=0) / 0.3186 + 1e-12
    power = ((fast / noise) ** 2).mean(axis=1)
    return np.sqrt(ndimage.uniform_filter1d(power, size=int(fs), mode="nearest"))


def _runs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Start and end (exclusive) indices of each run of True."""
    edges = np.flatnonzero(np.diff(np.concatenate([[0], mask.astype(np.int8), [0]])))
    return edges[0::2], edges[1::2]


def motion_mask(score: np.ndarray, fs: float = FS, threshold: float = MOTION_THRESHOLD) -> np.ndarray:
    """True where the person is moving: score above threshold, padded, short calm gaps filled."""
    moving = score > threshold
    if moving.any():
        moving = ndimage.binary_dilation(moving, iterations=int(MOTION_PAD_S * fs))
    for start, end in zip(*_runs(~moving)):
        if end - start < MIN_CALM_S * fs:
            moving[start:end] = True
    return moving


def remove_steps(x: np.ndarray, moving: np.ndarray, clip_mads: float = 6.0) -> np.ndarray:
    """Freeze the signal during movement, so level changes there become flat joins.

    Also limits any single-sample jump outside movement to clip_mads times the typical
    calm change, which catches steps the motion score missed without touching breathing.
    """
    d = np.diff(x, axis=0, prepend=x[:1])
    d[moving] = 0.0
    calm = ~moving
    if calm.sum() > 1:
        limit = clip_mads * 1.4826 * np.median(np.abs(d[calm]), axis=0) + 1e-12
        d = np.clip(d, -limit, limit)
    return x[0] + np.cumsum(d, axis=0)


def rolling_median(y: np.ndarray, fs: float = FS, window_s: float = DETREND_S, coarse_hz: float = 2.0):
    """Rolling median along time (computed at coarse_hz for speed, then interpolated back)."""
    step = max(1, int(round(fs / coarse_hz)))
    n = len(y) // step * step
    if n == 0:
        return np.repeat(np.median(y, axis=0, keepdims=True), len(y), axis=0)
    coarse = y[:n].reshape(-1, step, y.shape[1]).mean(axis=1)
    size = max(1, int(window_s * coarse_hz)) | 1
    med = ndimage.median_filter(coarse, size=(size, 1), mode="nearest")
    centers = np.arange(len(coarse)) * step + (step - 1) / 2
    idx = np.arange(len(y))
    return np.column_stack([np.interp(idx, centers, med[:, k]) for k in range(y.shape[1])])


def clean(x: np.ndarray, moving: np.ndarray, fs: float = FS) -> tuple[np.ndarray, np.ndarray]:
    """Return (z, gate): drift-free, robustly scaled subcarriers, and a 0..1 weight that is 0 in movement."""
    y = remove_steps(x, moving)
    y = y - rolling_median(y, fs)
    calm = ~moving
    ref = y[calm] if calm.sum() > 10 else y
    center = np.median(ref, axis=0)
    scale = 1.4826 * np.median(np.abs(ref - center), axis=0) + 1e-12
    z = np.clip((y - center) / scale, -3.0, 3.0)  # one swing can't dominate
    gate = ndimage.uniform_filter1d(calm.astype(float), size=int(fs), mode="nearest")  # 1 s fades
    edge = min(int(EDGE_S * fs), len(gate) // 4)
    if edge:  # fade the recording's own start and end too, where filters misbehave
        ramp = np.linspace(0, 1, edge)
        gate[:edge] *= ramp
        gate[-edge:] *= ramp[::-1]
    return z * gate[:, None], gate


def welch(x: np.ndarray, fs: float = FS, segment_s: float = SPECTRUM_S):
    nper = min(len(x), int(segment_s * fs))
    return signal.welch(x, fs=fs, window="hann", nperseg=nper, noverlap=nper // 2,
                        nfft=max(8192, nper), axis=0)


def main_peak(p: np.ndarray) -> int:
    """Index of the most prominent peak in a spectrum slice.

    Drift makes power rise toward the low edge of the band, so the tallest point is
    often just that edge. Prominence (how far a peak stands above its surroundings)
    picks a real rhythm instead. Falls back to the tallest point if there is no peak.
    """
    peaks, props = signal.find_peaks(p, prominence=0)
    return int(peaks[np.argmax(props["prominences"])]) if len(peaks) else int(np.argmax(p))


def band_shares(z: np.ndarray, fs: float = FS) -> tuple[np.ndarray, np.ndarray]:
    """(f, share): each subcarrier's breathing-band spectrum, scaled to sum to 1."""
    f, p = welch(z, fs)
    band = (f >= BAND[0]) & (f <= BAND[1])
    return f[band], p[band] / (p[band].sum(axis=0) + 1e-20)


def contrast(f: np.ndarray, consensus: np.ndarray, f0: float) -> float:
    """How far the consensus spectrum at f0 stands above its neighbourhood (about 1 = no rhythm).

    The consensus averages every subcarrier, so noise flattens out and picking
    subcarriers afterwards can't fake a peak here.
    """
    near = np.abs(f - f0) <= RHYTHM_TOL_HZ
    around = (np.abs(f - f0) > 2 * RHYTHM_TOL_HZ) & (np.abs(f - f0) <= 0.1)
    return float(consensus[near].mean() / (np.median(consensus[around]) + 1e-20)) if around.any() else np.nan


def breathing_signal(z: np.ndarray, gate: np.ndarray, fs: float = FS, top_fraction: float = 0.15):
    """Combine the subcarriers that share the strongest common rhythm.

    Returns (breath, top, rhythm, consensus): the breathing waveform (unit std over calm
    data, 0 in movement), indices of the subcarriers used, every subcarrier's rhythm score
    (share of its breathing-band power at the common frequency), and (f, consensus
    spectrum) for estimate_rate().
    """
    f, share = band_shares(z, fs)
    consensus = share.mean(axis=1)
    common = f[main_peak(consensus)]
    rhythm = share[np.abs(f - common) <= RHYTHM_TOL_HZ].sum(axis=0)
    top = np.argsort(rhythm)[::-1][:max(5, int(top_fraction * z.shape[1]))]

    sos = signal.butter(2, BAND, btype="band", fs=fs, output="sos")
    # Long padding: at a 0.05 Hz cutoff the filter's start-up transient lasts ~20 s.
    zb = signal.sosfiltfilt(sos, z[:, top], axis=0, padlen=min(len(z) - 1, int(20 * fs)))
    calm = gate > 0.99
    fit = zb[calm] if calm.sum() > 10 else zb
    _, _, vt = np.linalg.svd(fit - fit.mean(axis=0), full_matrices=False)
    breath = zb @ vt[0]
    if np.dot(breath, zb[:, 0]) < 0:  # sign: follow the most rhythmic subcarrier
        breath = -breath
    breath = breath * gate
    std = breath[calm].std() if calm.sum() > 10 else breath.std()
    return breath / (std + 1e-12), top, rhythm, (f, consensus)


def sliding_spectra(breath: np.ndarray, gate: np.ndarray, fs: float = FS,
                    window_s: float = WINDOW_S, step_s: float = 1.0):
    """Spectra of sliding windows: (centers in s from the grid start, f, power[f, window]).

    Windows that are mostly movement are NaN.
    """
    n, step = int(window_s * fs), max(1, int(step_s * fs))
    starts = np.arange(0, len(breath) - n + 1, step)
    f = np.fft.rfftfreq(4096, 1 / fs)
    power = np.full((len(f), len(starts)), np.nan)
    for j, s in enumerate(starts):
        if gate[s:s + n].mean() >= 0.5:
            _, power[:, j] = signal.periodogram(breath[s:s + n], fs=fs, window="hann", nfft=4096)
    return (starts + n / 2) / fs, f, power


@dataclass(frozen=True)
class RateEstimate:
    rate_bpm: float      # strongest rhythm in the band, in cycles/min
    half_ratio: float    # power at half that frequency / power at it (high: maybe two bumps per breath)
    rhythm_share: float  # share of band power within ~1 breath/min of the rhythm
    consistency: float   # share of sliding windows whose peak agrees with the rhythm (NaN if none)
    windows: int         # sliding windows used for the consistency check
    contrast: float      # consensus spectrum at the rhythm vs its neighbourhood (about 1 = noise)
    calm_s: float        # seconds of calm data
    cycles: float        # cycles of the rhythm that fit in the calm data
    steady: bool         # verdict: a steady breathing rhythm is present

    @property
    def maybe_half(self) -> bool:
        """Notable energy at half the frequency: the signal may show two bumps per breath.

        Only ground truth (marked breaths) can settle this, so it is a note, not a decision.
        """
        return self.half_ratio >= HALF_NOTE_MIN

    def verdict(self) -> str:
        if self.calm_s < MIN_CALM_TOTAL_S:
            return f"not enough calm data ({self.calm_s:.0f} s; need {MIN_CALM_TOTAL_S:.0f} s)"
        if self.cycles < MIN_CYCLES:
            return (f"too few cycles to call it a rhythm ({self.cycles:.1f} at {self.rate_bpm:.1f}/min; "
                    f"need {MIN_CYCLES:.0f})")
        if not self.steady:
            return "no steady breathing rhythm"
        note = (f"; or {self.rate_bpm / 2:.1f}/min if the signal shows two bumps per breath"
                if self.maybe_half else "")
        return f"steady breathing rhythm, about {self.rate_bpm:.1f} breaths/min{note}"


def estimate_rate(breath: np.ndarray, gate: np.ndarray, consensus=None, fs: float = FS) -> RateEstimate:
    """Rate and verdict for a breathing signal.

    consensus is the (f, spectrum) pair from breathing_signal(). Without it the contrast
    check is skipped, which is only right for a signal that wasn't built by picking
    subcarriers (e.g. a single clean waveform).
    """
    calm_s = float((gate > 0.99).sum() / fs)
    f, p = welch(breath, fs)
    band = (f >= BAND[0]) & (f <= BAND[1])
    if p[band].sum() <= 0:
        return RateEstimate(np.nan, np.nan, 0.0, np.nan, 0, np.nan, calm_s, 0.0, False)
    i = main_peak(p[band])
    rate, rate_power = f[band][i], p[band][i]
    share = float(p[band][np.abs(f[band] - rate) <= RHYTHM_TOL_HZ].sum() / p[band].sum())
    half_ratio = 0.0
    if rate / 2 >= BAND[0]:
        half_ratio = float(p[np.abs(f - rate / 2) <= RHYTHM_TOL_HZ].max() / rate_power)
    cycles = calm_s * rate

    # Steadiness: does the same peak show up in sliding windows long enough for 3 cycles?
    _, fw, power = sliding_spectra(breath, gate, fs, window_s=max(WINDOW_S, MIN_CYCLES / rate))
    valid = ~np.isnan(power[0])
    consistency = np.nan
    if valid.any():
        wband = (fw >= BAND[0]) & (fw <= BAND[1])
        peaks = np.array([fw[wband][main_peak(col)] for col in power[wband][:, valid].T])
        consistency = float(np.mean(np.abs(peaks - rate) <= 2 / 60))  # within 2 breaths/min
    rhythm_contrast = contrast(*consensus, rate) if consensus is not None else np.nan
    steady = (calm_s >= MIN_CALM_TOTAL_S and cycles >= MIN_CYCLES and share >= SHARE_MIN
              and consistency >= CONSISTENCY_MIN
              and (consensus is None or rhythm_contrast >= CONTRAST_MIN))
    return RateEstimate(float(rate * 60), half_ratio, share, consistency, int(valid.sum()),
                        rhythm_contrast, calm_s, float(cycles), bool(steady))


def analyse(t: np.ndarray, amp: np.ndarray, fs: float = FS) -> dict:
    """Run the whole pipeline on one recording. Returns every intermediate for plotting."""
    grid, x, kept = prepare(t, amp, fs)
    score = motion_score(x, fs)
    moving = motion_mask(score, fs)
    z, gate = clean(x, moving, fs)
    breath, top, rhythm, consensus = breathing_signal(z, gate, fs)
    return {"grid": grid, "x": x, "kept": kept, "score": score, "moving": moving, "z": z,
            "gate": gate, "breath": breath, "top": top, "rhythm": rhythm, "consensus": consensus,
            "estimate": estimate_rate(breath, gate, consensus, fs)}
