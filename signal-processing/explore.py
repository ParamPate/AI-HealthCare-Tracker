"""Plot a CSI recording and estimate the breathing rate (Phase 2).

    uv run python signal-processing/explore.py recordings/<file>.parquet [--start S] [--end E]

Uses backend/breathing.py: movement is detected and ignored, posture shifts and
drift are removed before filtering, and a rhythm only counts as breathing if it
is steady, lasts at least 3 cycles, and stands out across all subcarriers.
Saves <file>.png (or <file>_<start>-<end>s.png) next to the recording. Panels:
amplitude heatmap, movement score, cleaned breathing signal, rhythm over time,
and the spectrum with the verdict.
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

from backend import breathing  # noqa: E402
from backend.csi_format import amplitudes  # noqa: E402

# Reference palette from the dataviz skill (light mode).
BLUE, ORANGE = "#2a78d6", "#eb6834"
SURFACE, INK, INK_2, GRID, BAND_FILL = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0", "#f0efec"
MOVEMENT = "#fab219"  # status "warning", always labelled
DIVERGING = LinearSegmentedColormap.from_list("blue_gray_red", ["#1c5cab", "#f0efec", "#e34948"])
SEQUENTIAL = LinearSegmentedColormap.from_list("blues", ["#fcfcfb", "#86b6ef", "#2a78d6", "#104281"])


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


def shade_movement(ax, grid: np.ndarray, moving: np.ndarray, label: bool = False) -> None:
    for i, (a, b) in enumerate(zip(*breathing._runs(moving))):
        ax.axvspan(grid[a], grid[b - 1], color=MOVEMENT, alpha=0.22, lw=0,
                   label="movement (ignored)" if label and i == 0 else None)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("recording", type=Path)
    p.add_argument("--start", type=float, default=0.0, help="analyse from this many seconds in")
    p.add_argument("--end", type=float, help="analyse up to this many seconds in (default: the end)")
    args = p.parse_args()
    path = args.recording

    df, t, amp = load(path, args.start, args.end)
    if len(t) < 2 or t[-1] - t[0] < 5:
        raise SystemExit("Too little data to analyse (under 5 s). Check --start and --end.")
    r = breathing.analyse(t, amp)
    grid, moving, est = r["grid"], r["moving"], r["estimate"]
    seq = df["seq"].to_numpy(dtype=np.int64)
    dropped = 1 - len(seq) / ((seq[-1] - seq[0]) % (1 << 32) + 1)
    span = t[-1] - t[0]
    rate = (len(t) - 1) / span
    label = (pq.read_schema(path).metadata or {}).get(b"label", path.stem.encode()).decode()

    plt.rcParams.update({"font.size": 9, "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 10,
                         "axes.titlelocation": "left", "legend.frameon": False, "legend.fontsize": 8})
    fig = plt.figure(figsize=(13, 14), facecolor=SURFACE)
    gs = fig.add_gridspec(5, 1, height_ratios=[2, 1.1, 1.6, 1.6, 1.6], hspace=0.5, top=0.93)
    ax_heat = fig.add_subplot(gs[0])
    ax_move, ax_breath, ax_tf = (fig.add_subplot(gs[i], sharex=ax_heat) for i in (1, 2, 3))
    ax_spec = fig.add_subplot(gs[4])

    x = r["x"]
    xz = np.clip((x - np.median(x, axis=0)) / (1.4826 * np.median(np.abs(x - np.median(x, axis=0)), axis=0) + 1e-12),
                 -3, 3)
    im = ax_heat.imshow(xz.T, aspect="auto", origin="lower", cmap=DIVERGING, vmin=-3, vmax=3,
                        interpolation="nearest", extent=(grid[0], grid[-1], 0, xz.shape[1]))
    ax_heat.set_title(f"Amplitude per subcarrier before cleaning ({xz.shape[1]} of {amp.shape[1]} subcarriers kept)")
    style(ax_heat, "subcarrier")
    ax_heat.grid(False)
    cbar = fig.colorbar(im, cax=ax_heat.inset_axes((1.005, 0, 0.01, 1)))
    cbar.ax.tick_params(colors=INK_2, labelsize=8)
    cbar.outline.set_visible(False)

    shade_movement(ax_move, grid, moving, label=True)
    ax_move.plot(grid, r["score"], color=BLUE, linewidth=1)
    ax_move.axhline(breathing.MOTION_THRESHOLD, color=INK_2, linewidth=0.8, linestyle="--",
                    label=f"threshold {breathing.MOTION_THRESHOLD:g}")
    ax_move.set_yscale("log")
    ax_move.set_title(f"Movement score (fast changes; calm is about 1). Ignored: {moving.mean():.0%} of the time")
    ax_move.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    style(ax_move, "score")

    shade_movement(ax_breath, grid, moving)
    ax_breath.plot(grid, r["breath"], color=BLUE, linewidth=1.4)
    ax_breath.set_title("Breathing signal: movement ignored, posture shifts and drift removed, rhythmic subcarriers combined")
    style(ax_breath, "z")

    centers, fw, power = breathing.sliding_spectra(r["breath"], r["gate"])
    if len(centers):
        sel = fw * 60 <= 40
        valid = ~np.isnan(power[0])
        cols = np.full((sel.sum(), len(centers)), np.nan)
        cols[:, valid] = power[sel][:, valid] / power[sel][:, valid].max(axis=0, keepdims=True)
        cmap = SEQUENTIAL.copy()
        cmap.set_bad(SURFACE)
        half_step = (centers[1] - centers[0]) / 2 if len(centers) > 1 else 0.5
        ax_tf.imshow(np.ma.masked_invalid(cols), aspect="auto", origin="lower", cmap=cmap, vmin=0, vmax=1,
                     interpolation="nearest",
                     extent=(grid[0] + centers[0] - half_step, grid[0] + centers[-1] + half_step, 0, 40))
        if np.isfinite(est.rate_bpm):
            ax_tf.axhline(est.rate_bpm, color=ORANGE, linewidth=1, linestyle="--",
                          label=f"overall rhythm {est.rate_bpm:.1f}/min")
            ax_tf.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    else:
        ax_tf.text(0.5, 0.5, f"recording shorter than one {breathing.WINDOW_S:.0f} s window",
                   transform=ax_tf.transAxes, ha="center", color=INK_2)
    ax_tf.set_ylim(0, 40)
    ax_heat.set_xlim(grid[0], grid[-1])  # shared by the time panels; imshow above would narrow it
    ax_tf.set_title(f"Rhythm over time ({breathing.WINDOW_S:.0f} s windows, darker = stronger; "
                    "a steady horizontal band is breathing)")
    ax_tf.set_xlabel("time since start (s)", color=INK_2)
    style(ax_tf, "per minute")
    ax_tf.grid(False)

    f, pw = breathing.welch(r["breath"])
    fc, consensus = r["consensus"]
    show = f * 60 <= 40
    ax_spec.axvspan(breathing.BAND[0] * 60, breathing.BAND[1] * 60, color=BAND_FILL, zorder=0)
    ax_spec.plot(f[show] * 60, pw[show] / pw[show].max(), color=BLUE, linewidth=1.4, label="breathing signal")
    ax_spec.plot(fc * 60, consensus / consensus.max(), color=ORANGE, linewidth=1.2,
                 label="all subcarriers (consensus)")
    if np.isfinite(est.rate_bpm):
        ax_spec.axvline(est.rate_bpm, color=INK_2, linewidth=0.8, linestyle="--")
        if est.maybe_half:
            ax_spec.axvline(est.rate_bpm / 2, color=INK_2, linewidth=0.8, linestyle=":")
    ax_spec.set_xlim(0, 40)
    ax_spec.set_title("Spectrum (shaded: 3 to 30 breaths/min searched)")
    ax_spec.set_xlabel("breaths per minute", color=INK_2)
    ax_spec.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0))
    style(ax_spec, "relative power")

    fig.suptitle(f"{label}: {t[0]:.0f} to {t[-1]:.0f} s, {rate:.0f} packets/s, {100 * dropped:.0f}% dropped, "
                 f"RSSI median {df['rssi'].median():.0f} dBm\n{est.verdict()}",
                 x=0.125, y=0.975, ha="left", fontsize=12, color=INK)
    trimmed = args.start > 0 or args.end is not None
    out = path.with_name(f"{path.stem}_{t[0]:.0f}-{t[-1]:.0f}s.png") if trimmed else path.with_suffix(".png")
    fig.savefig(out, dpi=110, bbox_inches="tight", facecolor=SURFACE)

    print(f"{path.name}: {t[0]:.1f} to {t[-1]:.1f} s, {len(t)} packets ({rate:.1f}/s), dropped {100 * dropped:.1f}%, "
          f"RSSI median {df['rssi'].median():.0f} dBm (range {df['rssi'].min()} to {df['rssi'].max()})")
    print(f"subcarriers kept: {xz.shape[1]} of {amp.shape[1]}")
    print(f"movement: {100 * moving.mean():.0f}% of the time ignored; calm data used: {est.calm_s:.0f} s")
    if np.isfinite(est.rate_bpm):
        print(f"rhythm: {est.rate_bpm:.1f}/min, contrast {est.contrast:.2f} (noise about 1, need "
              f"{breathing.CONTRAST_MIN:g}), {100 * est.rhythm_share:.0f}% of band power, steady in "
              f"{100 * est.consistency:.0f}% of {est.windows} windows, {est.cycles:.1f} cycles")
        print(f"two-bumps check: power at {est.rate_bpm / 2:.1f}/min is {est.half_ratio:.2f} of the peak")
    print(f"verdict: {est.verdict()}")
    print(f"plot: {out}")


if __name__ == "__main__":
    main()
