"""Live breathing monitor in the terminal: the numbers the web app will show.

    uv run python -m backend.live                                      # RX board
    uv run python -m backend.live --replay recordings/<file>.parquet  # a saved recording

Once a second the last 60 s are analysed with backend.breathing and one line is
printed: status, breathing rate, seconds of calm data, a sketch of the breathing wave
over the last 16 s, RSSI, and packets/s. Ctrl+C stops and prints a summary.

Statuses: STARTING (first 10 s), MEASURING (not enough calm data yet, or a rhythm
not yet confirmed), BREATHING (a steady rhythm in 3 updates in a row), MOVEMENT
(movement right now), NO RHYTHM (enough calm data but no steady rhythm). Through
movement or a lost rhythm the last rate is kept for 10 s and marked "held". Only one
program can use the RX port at a time.
"""
import argparse
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend import breathing, config
from backend.csi_format import amplitudes
from backend.serial_io import CsiStream, find_rx_port, open_port

BUFFER_S = 60.0       # analyse this much recent data
MIN_DATA_S = 10.0     # before this, only collect
WARMUP_CALM_S = 30.0  # MEASURING until this much calm data (a first rate usually needs 25 to 30 s)
HOLD_S = 10.0         # keep showing the last good rate this long
CONFIRM = 3           # BREATHING needs this many updates in a row that are steady and agree...
AGREE_BPM = 2.0       # ...within this (a weak signal can flip between unrelated peaks)
WAVE_S = 30.0         # breathing wave kept for display
WAVE_HZ = 10.0
WAVE_DELAY_S = breathing.EDGE_S + 1.0  # exclude the artificial end fade; still an offline-filter preview
SPARK_S, SPARK_CHARS = 16.0, 40
BARS = "▁▂▃▄▅▆▇█"
LABELS = {"starting": "STARTING", "measuring": "MEASURING", "breathing": "BREATHING",
          "moving": "MOVEMENT", "no_rhythm": "NO RHYTHM"}


@dataclass(frozen=True)
class LiveState:
    elapsed_s: float         # seconds since data started
    status: str              # a key of LABELS
    rate_bpm: float | None   # breaths/min to show, or None
    held: bool               # rate_bpm is the last good rate, kept through movement or a lost rhythm
    calm_s: float            # calm seconds in the analysed window
    data_s: float            # seconds in the analysed window
    wave: np.ndarray         # breathing wave, last WAVE_S at WAVE_HZ (unit std, 0 during movement)
    rssi: int | None
    packets_per_s: float
    estimate: breathing.RateEstimate | None
    wave_times: np.ndarray = field(default_factory=lambda: np.zeros(0))  # device seconds


class LiveAnalyser:
    """Rolling buffer of the last BUFFER_S of packets. add() and update() may run in different threads."""

    def __init__(self, buffer_s: float = BUFFER_S) -> None:
        self.lock = threading.Lock()
        self.buffer_s = buffer_s
        self.packets: deque[tuple[float, np.ndarray]] = deque(maxlen=int(buffer_s * 200))
        self.rssi: int | None = None
        self.start: float | None = None
        self.segment: int | None = None
        self.last_good: tuple[float, float] | None = None  # (device time s, rate)
        self.streak, self.prev_rate = 0, np.nan  # steady updates in a row that agree on the rate

    def add(self, t_s: float, amp: np.ndarray, rssi: int, segment: int = 0) -> None:
        with self.lock:
            discontinuity = bool(self.packets) and (
                t_s < self.packets[-1][0] or t_s - self.packets[-1][0] > 2.0
                or amp.shape != self.packets[-1][1].shape
            )
            if segment != self.segment or discontinuity:
                self.packets.clear()
                self.start, self.segment, self.last_good, self.streak = None, segment, None, 0
                self.prev_rate = np.nan
            if self.packets and t_s == self.packets[-1][0]:
                return
            if self.start is None:
                self.start = t_s
            self.packets.append((t_s, amp))
            self.rssi = rssi
            while self.packets[0][0] < t_s - self.buffer_s:
                self.packets.popleft()

    def update(self) -> LiveState:
        """Analyse the buffer (about 0.1 s of work) and decide what to show."""
        with self.lock:
            snap, rssi, start = list(self.packets), self.rssi, self.start
        if not snap:
            return LiveState(0.0, "starting", None, False, 0.0, 0.0, np.zeros(0), None, 0.0, None)
        t = np.array([p[0] for p in snap])
        now, data_s = t[-1], t[-1] - t[0]
        pps = np.sum(t > now - 5) / max(min(5.0, data_s), 1.0)
        if data_s < MIN_DATA_S:
            return LiveState(now - start, "starting", None, False, 0.0, data_s, np.zeros(0), rssi, pps, None)

        r = breathing.analyse(t - t[0], np.stack([p[1] for p in snap]))
        est = r["estimate"]
        moving = r["moving"][-int(breathing.FS):].mean() > 0.5
        if not est.steady:
            self.streak = 0
        elif self.streak and abs(est.rate_bpm - self.prev_rate) <= AGREE_BPM:
            self.streak += 1
        else:
            self.streak = 1
        self.prev_rate = est.rate_bpm
        confirmed = self.streak >= CONFIRM
        if confirmed:
            self.last_good = (now, est.rate_bpm)
        if moving:
            status = "moving"
        elif confirmed:
            status = "breathing"
        elif est.steady or est.calm_s < WARMUP_CALM_S:
            status = "measuring"
        else:
            status = "no_rhythm"

        rate, held = None, False
        if status == "breathing":
            rate = est.rate_bpm
        elif self.last_good and now - self.last_good[0] <= HOLD_S:
            rate, held = self.last_good[1], True
        end = max(0, len(r["breath"]) - int(WAVE_DELAY_S * breathing.FS))
        indices = np.arange(max(0, end - int(WAVE_S * breathing.FS)), end,
                            int(breathing.FS / WAVE_HZ))
        wave = r["breath"][indices]
        return LiveState(now - start, status, rate, held, est.calm_s, data_s, wave, rssi, pps, est,
                         t[0] + r["grid"][indices])


def sparkline(wave: np.ndarray) -> str:
    """The last SPARK_S of the wave as block characters, scaled over the whole wave so a pause looks flat."""
    n = int(SPARK_S * WAVE_HZ)
    if len(wave) < n:
        return " " * SPARK_CHARS
    lo, hi = np.percentile(wave, [2, 98])
    blocks = wave[-n:].reshape(SPARK_CHARS, -1).mean(axis=1)
    idx = np.clip((blocks - lo) / (hi - lo + 1e-9) * len(BARS), 0, len(BARS) - 1).astype(int)
    return "".join(BARS[i] for i in idx)


HEADER = f"{'time':>6}  {'status':<9}  {'rate':<14}  {'calm data':<12}  {'breathing wave, last 16 s':<{SPARK_CHARS}}  RSSI  pkt/s"


def format_line(s: LiveState, debug: bool = False) -> str:
    if s.status == "starting" and not s.packets_per_s:
        return f"{s.elapsed_s:5.0f}s  waiting for packets... (is TX powered?)"
    rate = "--" if s.rate_bpm is None else f"{s.rate_bpm:4.1f}/min" + (" held" if s.held else "")
    if s.status == "starting":
        calm = f"data {s.data_s:.0f}/{MIN_DATA_S:.0f} s"
    elif s.status == "measuring":
        calm = f"{s.calm_s:.0f}/{WARMUP_CALM_S:.0f} s"
    else:
        calm = f"{s.calm_s:.0f} s"
    rssi = "--" if s.rssi is None else str(s.rssi)
    line = (f"{s.elapsed_s:5.0f}s  {LABELS[s.status]:<9}  {rate:<14}  {calm:<12}  {sparkline(s.wave)}  "
            f"{rssi:>4}  {s.packets_per_s:5.0f}")
    if debug and s.estimate is not None:
        e = s.estimate
        line += (f"   [peak {e.rate_bpm:4.1f}/min, contrast {e.contrast:.2f}, steady {e.consistency:.2f} "
                 f"of {e.windows}, cycles {e.cycles:.1f}{', half?' if e.maybe_half else ''}]")
    return line


def summary(states: list[LiveState]) -> str:
    analysed = [s for s in states if s.status != "starting"]
    if not analysed:
        return "No analysis yet (the first one needs 10 s of data)."
    counts = Counter(s.status for s in analysed)
    shares = ", ".join(f"{LABELS[k]} {v / len(analysed):.0%}" for k, v in counts.most_common())
    out = f"{states[-1].elapsed_s:.0f} s of data. Share of updates: {shares}."
    rates = [s.rate_bpm for s in analysed if s.status == "breathing"]
    if rates:
        out += (f"\nRate while BREATHING was shown: median {np.median(rates):.1f}/min "
                f"(range {min(rates):.1f} to {max(rates):.1f}).")
    else:
        out += "\nNo steady breathing rhythm was found."
    return out


def read_board(analyser: LiveAnalyser, port: str, baud: int, errors: list[Exception]) -> None:
    """Background thread: feed every packet from the RX board into the analyser."""
    try:
        with open_port(port, baud) as ser:
            stream = CsiStream(ser)
            while True:
                for s in stream.read():
                    p = s.packet
                    analyser.add(s.device_time_us / 1e6, amplitudes(p.csi, p.first_word_invalid), p.rssi, s.segment)
    except Exception as e:  # noqa: BLE001  (reported by the main loop)
        errors.append(e)


def run_board(port: str, baud: int, show) -> None:
    analyser, errors = LiveAnalyser(), []
    threading.Thread(target=read_board, args=(analyser, port, baud, errors), daemon=True).start()
    print(f"Reading {port}. Ctrl+C to stop.")
    tick = time.monotonic()
    while True:
        tick += 1.0
        time.sleep(max(0.0, tick - time.monotonic()))
        if errors:
            raise SystemExit(f"Serial error on {port}: {errors[0]}")
        show(analyser.update())


def run_replay(path: str, speed: float, show) -> None:
    """Feed a recording in one-second steps, paced at `speed` x real time (0: as fast as possible)."""
    df = pd.read_parquet(path)
    t = df["device_time_us"].to_numpy() / 1e6
    amp = amplitudes(np.stack(df["csi"].to_numpy()), bool(df["first_word_invalid"].iloc[0]))
    rssi = df["rssi"].to_numpy()
    segment = df["segment"].to_numpy() if "segment" in df else np.zeros(len(df), int)  # older recordings
    ends = np.searchsorted(t, np.arange(t[0] + 1.0, t[-1] + 1.0, 1.0), side="right")
    print(f"Replaying {path} ({t[-1] - t[0]:.0f} s) at {speed:g}x. Ctrl+C to stop." if speed else
          f"Replaying {path} ({t[-1] - t[0]:.0f} s) as fast as possible.")
    analyser, i, wall0 = LiveAnalyser(), 0, time.monotonic()
    for k, j in enumerate(ends, start=1):
        for row in range(i, j):
            analyser.add(t[row], amp[row], int(rssi[row]), int(segment[row]))
        i = j
        if speed:
            time.sleep(max(0.0, wall0 + k / speed - time.monotonic()))
        show(analyser.update())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--replay", metavar="PARQUET", help="play back a recording instead of reading the board")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed, 0 = as fast as possible (default 1)")
    p.add_argument("--debug", action="store_true", help="also print the numbers behind each verdict")
    p.add_argument("--port", default=config.SERIAL_PORT, help="RX serial port (default: auto-detect)")
    p.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # block characters, even when output is redirected

    states: list[LiveState] = []

    def show(state: LiveState) -> None:
        states.append(state)
        print(format_line(state, args.debug), flush=True)

    print("Screening signal only, not a diagnosis.")
    print(HEADER)
    try:
        if args.replay:
            run_replay(args.replay, args.speed, show)
        else:
            try:
                port = args.port or find_rx_port(args.baud)
            except RuntimeError as e:
                raise SystemExit(str(e))
            run_board(port, args.baud, show)
    except KeyboardInterrupt:
        pass
    print("\n" + summary(states))


if __name__ == "__main__":
    main()
