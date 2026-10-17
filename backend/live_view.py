"""Live window showing what the RX board receives, for checking placement.

    uv run python -m backend.live_view

Top: every subcarrier's amplitude over the last 30 s (movement shows up as vertical
streaks). Bottom: a smoothed preview of the strongest common pattern, where slow
breathing should look like a slow wave when you sit still. Close the window to stop.
Only one program can use the RX port at a time, so close this before backend.record.
"""
import argparse
import threading
import time
from collections import deque

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.colors import LinearSegmentedColormap
from scipy.ndimage import median_filter, uniform_filter1d

from backend import config
from backend.csi_format import amplitudes, parse_line
from backend.serial_io import LineBuffer, find_rx_port, open_port

WINDOW_S = 30
SURFACE, INK, INK_2, GRID, BLUE = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0", "#2a78d6"
DIVERGING = LinearSegmentedColormap.from_list("blue_gray_red", ["#1c5cab", "#f0efec", "#e34948"])


class Reader(threading.Thread):
    """Background thread: read the RX port and keep the last WINDOW_S seconds of packets."""

    def __init__(self, port: str, baud: int) -> None:
        super().__init__(daemon=True)
        self.port, self.baud = port, baud
        self.lock = threading.Lock()
        self.packets: deque[tuple[float, int, np.ndarray]] = deque()  # (host time, rssi, amplitudes)
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            with open_port(self.port, self.baud) as ser:
                lines = LineBuffer()
                while True:
                    chunk = ser.read(max(1, ser.in_waiting))
                    now = time.time()
                    parsed = [p for p in map(parse_line, lines.feed(chunk)) if p is not None]
                    with self.lock:
                        for p in parsed:
                            self.packets.append((now, p.rssi, amplitudes(p.csi, p.first_word_invalid)))
                        while self.packets and self.packets[0][0] < now - WINDOW_S:
                            self.packets.popleft()
        except Exception as e:  # noqa: BLE001  (shown in the window title)
            self.error = e

    def snapshot(self) -> list[tuple[float, int, np.ndarray]]:
        with self.lock:
            return list(self.packets)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", default=config.SERIAL_PORT, help="RX serial port (default: auto-detect)")
    p.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    args = p.parse_args()
    try:
        port = args.port or find_rx_port(args.baud)
    except RuntimeError as e:
        raise SystemExit(str(e))
    reader = Reader(port, args.baud)
    reader.start()

    fig, (ax_heat, ax_wave) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, facecolor=SURFACE,
                                           gridspec_kw={"height_ratios": [2, 1.2], "hspace": 0.3})
    fig.canvas.manager.set_window_title("RX live view")
    status = fig.suptitle("waiting for packets...", x=0.125, ha="left", fontsize=12, color=INK)
    im = ax_heat.imshow(np.zeros((2, 2)), aspect="auto", origin="lower", cmap=DIVERGING, vmin=-3, vmax=3,
                        interpolation="nearest", extent=(-WINDOW_S, 0, 0, 1))
    (wave,) = ax_wave.plot([], [], color=BLUE, linewidth=1.6)
    ax_heat.set_title("Amplitude per subcarrier (movement = vertical streaks)", loc="left", fontsize=10, color=INK)
    ax_wave.set_title("Smoothed common pattern (sit still: breathing should look like a slow wave)",
                      loc="left", fontsize=10, color=INK)
    ax_heat.set_ylabel("subcarrier", color=INK_2)
    ax_wave.set_xlabel("seconds ago", color=INK_2)
    ax_wave.set_yticks([])
    ax_wave.set_xlim(-WINDOW_S, 0)
    for ax in (ax_heat, ax_wave):
        ax.set_facecolor(SURFACE)
        ax.tick_params(colors=INK_2, labelsize=8)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(GRID)
    ax_wave.grid(color=GRID, linewidth=0.6)
    prev_axis: list[np.ndarray | None] = [None]

    def update(_frame):
        if reader.error:
            status.set_text(f"Serial error on {port}: {reader.error}")
            return
        snap = reader.snapshot()
        if len(snap) < 50:
            status.set_text(f"{port}: waiting for packets... (is TX powered?)")
            return
        now = time.time()
        t = np.array([s[0] for s in snap]) - now
        amp = np.stack([s[2] for s in snap])
        mean = amp.mean(axis=0)
        keep = mean > 0.1 * np.median(mean)
        norm = amp[:, keep] / amp[:, keep].mean(axis=1, keepdims=True)  # cancel receiver gain jumps
        norm = median_filter(norm, size=(5, 1), mode="nearest")  # drop single-packet spikes
        z =(norm - norm.mean(axis=0)) / (norm.std(axis=0) + 1e-9)

        im.set_data(z.T)
        im.set_extent((t[0], t[-1], 0, z.shape[1]))
        ax_heat.set_ylim(0, z.shape[1])

        _, _, vt = np.linalg.svd(z, full_matrices=False)
        axis = vt[0]
        if prev_axis[0] is not None and prev_axis[0].shape == axis.shape and axis @ prev_axis[0] < 0:
            axis = -axis  # keep the sign stable between frames so the wave doesn't flip
        prev_axis[0] = axis
        rate = np.sum(t > -5) / 5
        smooth = uniform_filter1d(z @ axis, size=max(1, int(rate)))  # 1 s moving average
        wave.set_data(t, smooth)
        lim = max(3 * smooth.std(), 1e-6)
        ax_wave.set_ylim(-lim, lim)

        recent = snap[-1][1]
        status.set_text(f"{port}: {rate:.0f} packets/s, RSSI {recent} dBm "
                        f"({'good' if recent > -70 else 'weak, move boards closer'})")

    _anim = FuncAnimation(fig, update, interval=250, cache_frame_data=False)  # noqa: F841
    plt.show()


if __name__ == "__main__":
    main()
