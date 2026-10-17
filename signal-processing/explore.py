"""Plot a CSI recording to check whether breathing is visible (Phase 2).

    uv run python signal-processing/explore.py recordings/<file>.parquet

Saves <file>.png next to the recording and prints a short summary. Panels:
RSSI, per-subcarrier amplitude heatmap, movement score, the subcarriers that
carry the most breathing-band energy, the first principal component in the
breathing band, and its spectrum in breaths/min.
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from scipy import ndimage, signal  # noqa: E402

from backend.csi_format import amplitudes  # noqa: E402

FS = 20.0                 # Hz, uniform grid the irregular packets are resampled onto
BREATH_BAND = (0.1, 0.5)  # Hz, 6 to 30 breaths/min
WIDE_BAND = (0.05, 2.0)   # Hz, drift and fast noise removed, breathing and slow motion kept

# Reference palette from the dataviz skill (light mode), categorical slots in fixed order.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"
DIVERGING = LinearSegmentedColormap.from_list("blue_gray_red", ["#1c5cab", "#f0efec", "#e34948"])


def load(path: Path, start: float = 0.0, end: float | None = None):
    """Read a recording; keep packets between start and end seconds (times stay relative to its start)."""
    df = pd.read_parquet(path)
    if "segment" in df and df["segment"].nunique() > 1:
        longest = df["segment"].value_counts().idxmax()
        print(f"note: the RX board restarted during this recording; analysing its longest stretch "
              f"(segment {longest}, {(df['segment'] == longest).mean():.0%} of packets)")
        df = df[df["segment"] == longest]
    lengths = df["csi"].map(len)
    df = df[lengths == lengths.mode().iloc[0]].reset_index(drop=True)
    t = (df["device_time_us"].to_numpy() - df["device_time_us"].iloc[0]) / 1e6
    window = (t >= start) & (t <= (np.inf if end is None else end))
    df, t = df[window].reset_index(drop=True), t[window]
    amp = amplitudes(np.stack(df["csi"].to_numpy()), bool(df["first_word_invalid"].iloc[0]))
    return df, t, amp


def resample(t: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    grid = np.arange(t[0], t[-1], 1 / FS)
    return grid, np.column_stack([np.interp(grid, t, x[:, k]) for k in range(x.shape[1])])


def zscore(x: np.ndarray) -> np.ndarray:
    std = x.std(axis=0)
    return (x - x.mean(axis=0)) / np.where(std > 0, std, 1)


def bandpass(x: np.ndarray, band: tuple[float, float], order: int = 4) -> np.ndarray:
    sos = signal.butter(order, band, btype="band", fs=FS, output="sos")
    return signal.sosfiltfilt(sos, x, axis=0)


def first_component(x: np.ndarray) -> tuple[np.ndarray, float]:
    x = x - x.mean(axis=0)
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    return x @ vt[0], float(s[0] ** 2 / np.sum(s ** 2))


def spectrum(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    nperseg = min(len(x), int(60 * FS))
    f, p = signal.welch(x, fs=FS, nperseg=nperseg, nfft=max(8192, nperseg))
    return f, p


def peak_bpm(f: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    """Peak frequency inside the breathing band (bpm) and the band's share of wide-band power."""
    band = (f >= BREATH_BAND[0]) & (f <= BREATH_BAND[1])
    wide = (f >= WIDE_BAND[0]) & (f <= WIDE_BAND[1])
    return float(f[band][np.argmax(p[band])] * 60), float(p[band].sum() / p[wide].sum())


def style(ax, ylabel: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.tick_params(colors=INK_2, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("recording", type=Path)
    p.add_argument("--start", type=float, default=0.0, help="analyse from this many seconds in")
    p.add_argument("--end", type=float, help="analyse up to this many seconds in (default: the end)")
    args = p.parse_args()
    path = args.recording

    df, t, amp = load(path, args.start, args.end)
    if len(t) < 2 or t[-1] - t[0] < 2:
        raise SystemExit("Too little data to analyse (under 2 s). Check --start and --end.")
    span = t[-1] - t[0]
    seq = df["seq"].to_numpy(dtype=np.int64)
    dropped = 1 - len(seq) / ((seq[-1] - seq[0]) % (1 << 32) + 1)

    # Null and guard subcarriers carry ~zero amplitude; detect them from the data.
    mean_amp = amp.mean(axis=0)
    keep = (mean_amp > 0.1 * np.median(mean_amp)) & (amp.std(axis=0) > 0)
    sc_index = np.flatnonzero(keep)
    amp = amp[:, keep]
    # Dividing by each packet's mean amplitude cancels receiver gain (AGC) jumps,
    # which a classic ESP32 does not compensate for.
    amp_norm = amp / amp.mean(axis=1, keepdims=True)

    grid, z = resample(t, ndimage.median_filter(amp, size=(5, 1), mode="nearest"))
    _, z_norm = resample(t, ndimage.median_filter(amp_norm, size=(5, 1), mode="nearest"))
    z, z_norm = zscore(z), zscore(z_norm)

    wide, wide_norm = bandpass(z, WIDE_BAND, order=2), bandpass(z_norm, WIDE_BAND, order=2)
    breath_share = bandpass(wide, BREATH_BAND).var(axis=0) / wide.var(axis=0)
    top = np.argsort(breath_share)[::-1][:5]

    pc, pc_var = first_component(wide)
    pc_norm, pc_norm_var = first_component(wide_norm)
    f, p_pc = spectrum(pc)
    _, p_pc_norm = spectrum(pc_norm)
    bpm, share = peak_bpm(f, p_pc)
    bpm_norm, share_norm = peak_bpm(f, p_pc_norm)
    movement = ndimage.uniform_filter1d(np.abs(np.diff(z, axis=0, prepend=z[:1])).mean(axis=1), size=int(FS))

    label = (pq.read_schema(path).metadata or {}).get(b"label", path.stem.encode()).decode()
    rate = (len(t) - 1) / span
    rssi = int(df["rssi"].median())
    plt.rcParams.update({"font.size": 9, "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 10,
                         "axes.titlelocation": "left", "legend.frameon": False, "legend.fontsize": 8})
    fig = plt.figure(figsize=(13, 15), facecolor=SURFACE)
    gs = fig.add_gridspec(6, 1, height_ratios=[1, 2.2, 1, 2, 1.6, 1.6], hspace=0.45, top=0.94)
    ax_rssi = fig.add_subplot(gs[0])
    ax_heat, ax_move, ax_top, ax_pc = (fig.add_subplot(gs[i], sharex=ax_rssi) for i in range(1, 5))
    ax_spec = fig.add_subplot(gs[5])

    ax_rssi.plot(t, df["rssi"], color=SERIES[0], linewidth=1)
    ax_rssi.set_title("RSSI")
    style(ax_rssi, "dBm")

    im = ax_heat.imshow(z.T, aspect="auto", origin="lower", cmap=DIVERGING, vmin=-3, vmax=3,
                        interpolation="nearest", extent=(grid[0], grid[-1], 0, z.shape[1]))
    ax_heat.set_title(f"Amplitude per subcarrier, z-scored ({z.shape[1]} of {len(mean_amp)} subcarriers kept)")
    style(ax_heat, "subcarrier (kept)")
    ax_heat.grid(False)
    cbar = fig.colorbar(im, cax=ax_heat.inset_axes((1.005, 0, 0.01, 1)))
    cbar.ax.tick_params(colors=INK_2, labelsize=8)
    cbar.outline.set_visible(False)

    ax_move.plot(grid, movement, color=SERIES[0], linewidth=1)
    ax_move.set_title("Movement score (mean sample-to-sample change, 1 s average)")
    style(ax_move, "z / sample")

    for rank, k in enumerate(top):
        trace = bandpass(wide[:, k], BREATH_BAND)
        ax_top.plot(grid, trace / trace.std() - 4 * rank, color=SERIES[rank], linewidth=1.2,
                    label=f"subcarrier {sc_index[k]} ({100 * breath_share[k]:.0f}% in band)")
    ax_top.set_title("Subcarriers with the most breathing-band energy, filtered 0.1 to 0.5 Hz (offset for clarity)")
    ax_top.set_yticks([])
    ax_top.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    style(ax_top, "")

    for x, color, name in ((pc, SERIES[0], "raw amplitude"), (pc_norm, SERIES[1], "gain-normalized amplitude")):
        trace = bandpass(x, BREATH_BAND)
        ax_pc.plot(grid, trace / trace.std(), color=color, linewidth=1.4, label=name)
    ax_pc.set_title("Breathing estimate: first principal component, filtered 0.1 to 0.5 Hz")
    ax_pc.set_xlabel("time since start (s)", color=INK_2)
    ax_pc.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    style(ax_pc, "z")

    ax_spec.axvspan(BREATH_BAND[0] * 60, BREATH_BAND[1] * 60, color="#f0efec", zorder=0)
    for pw, color, name, peak in ((p_pc, SERIES[0], "raw amplitude", bpm),
                                  (p_pc_norm, SERIES[1], "gain-normalized amplitude", bpm_norm)):
        ax_spec.plot(f * 60, pw / pw.max(), color=color, linewidth=1.4, label=f"{name}: peak {peak:.1f} bpm")
    ax_spec.set_xlim(0, 60)
    ax_spec.set_title("Spectrum of the first principal component (shaded: 6 to 30 breaths/min)")
    ax_spec.set_xlabel("breaths per minute", color=INK_2)
    ax_spec.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    style(ax_spec, "relative power")

    fig.suptitle(f"{label}: {t[0]:.0f} to {t[-1]:.0f} s, {rate:.0f} packets/s, {100 * dropped:.0f}% dropped, "
                 f"RSSI median {rssi} dBm", x=0.125, y=0.975, ha="left", fontsize=12, color=INK)
    trimmed = args.start > 0 or args.end is not None
    out = path.with_name(f"{path.stem}_{t[0]:.0f}-{t[-1]:.0f}s.png") if trimmed else path.with_suffix(".png")
    fig.savefig(out, dpi=110, bbox_inches="tight", facecolor=SURFACE)

    print(f"{path.name}: {t[0]:.1f} to {t[-1]:.1f} s, {len(t)} packets ({rate:.1f}/s), dropped {100 * dropped:.1f}%, "
          f"RSSI median {rssi} dBm")
    print(f"subcarriers kept: {z.shape[1]} of {len(mean_amp)} (null: {sorted(set(range(len(mean_amp))) - set(sc_index))})")
    print(f"PC1 raw:        {100 * pc_var:4.1f}% of variance, peak {bpm:5.1f} bpm, "
          f"{100 * share:4.1f}% of 0.05 to 2 Hz power in the breathing band")
    print(f"PC1 normalized: {100 * pc_norm_var:4.1f}% of variance, peak {bpm_norm:5.1f} bpm, "
          f"{100 * share_norm:4.1f}% of 0.05 to 2 Hz power in the breathing band")
    print(f"top breathing subcarriers: {[int(sc_index[k]) for k in top]}")
    print(f"plot: {out}")


if __name__ == "__main__":
    main()
