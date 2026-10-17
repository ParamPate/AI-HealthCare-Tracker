"""One shared source per server process; WebSocket clients only read snapshots."""
from collections import deque
import logging
import math
import threading
import time

import numpy as np
import pandas as pd

from backend.csi_format import CsiPacket, amplitudes
from backend.live import BUFFER_S, LiveAnalyser, WAVE_DELAY_S  # same 60 s window the terminal monitor was tested with
from backend.serial_io import CsiStream, Sample, find_rx_port, open_port

LOGGER = logging.getLogger(__name__)
STALE_S = 2.0
RESULT_STALE_S = 5.0
MAX_PENDING = 24000
CHAIR = "Chair 1"


def empty_frame(source, reason, seq=0):
    return {"t": None, "breath": None, "rate_bpm": None, "status": "no_signal",
            "reason": reason, "source": source, "seq": seq, "waveform": [],
            "waveform_delay_s": 0.0, "pause_s": None, "alert": None, "chair": CHAIR, "level": None,
            "calm_s": None, "rssi": None, "packets_per_s": None}


class FakeSource:
    """Synthetic 15/min breathing, a 16 s pause, movement, and missing input."""
    name = "fake"

    def __init__(self):
        self.started = time.monotonic()
        self.epoch = time.time()

    def start(self):
        self.started, self.epoch = time.monotonic(), time.time()

    def stop(self):
        pass

    def get_latest(self):
        elapsed = time.monotonic() - self.started
        seq = int(elapsed * 15)
        t = self.epoch + seq / 15
        phase = elapsed % 60
        if 52 <= phase < 55:
            return empty_frame("fake", "simulated_signal_loss", seq)
        status = "pause" if 30 <= phase < 46 else "motion" if 46 <= phase < 52 else "breathing"
        breath = 0.0 if status == "pause" else math.sin(2 * math.pi * 0.25 * seq / 15)
        breath += 0.02 * math.sin(seq * 1.7)
        return {**empty_frame("fake", "simulated", seq),
                "t": t, "breath": breath, "rate_bpm": 15.0 if status == "breathing" else None,
                "status": status, "waveform": [{"t": t, "breath": breath}],
                "pause_s": phase - 30 if status == "pause" else None, "rssi": -60, "packets_per_s": 71.0,
                "alert": {"id": f"demo-{self.epoch}-{int(elapsed // 60)}", "kind": "simulated_pause"}
                if status == "pause" else None}


class SerialSource:
    name = "serial"

    def __init__(self, port=None, baud=921600):
        self.port, self.baud = port, baud
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pending = deque()
        self._generation = 0
        self._last_input = None
        self._last_result = None
        self._error = None
        self._frame = empty_frame(self.name, "warming_up")
        self._threads = []

    def start(self):
        for target in (self._acquire, self._process):
            thread = threading.Thread(target=target, daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self):
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)
            if thread.is_alive():
                LOGGER.warning("Source worker did not stop within five seconds")

    def get_latest(self):
        with self._lock:
            now = time.monotonic()
            reason = self._error
            if reason is None and (self._last_input is None or now - self._last_input > STALE_S):
                reason = "waiting_for_packets" if self._last_input is None else "stale_input"
            if reason is None and self._last_result is not None and now - self._last_result > RESULT_STALE_S:
                reason = "processing_delayed"
            return empty_frame(self.name, reason, self._frame["seq"]) if reason else self._frame.copy()

    def _acquire(self):
        try:
            port = self.port or find_rx_port(self.baud)
            with open_port(port, self.baud) as connection:
                stream = CsiStream(connection)
                while not self._stop.is_set():
                    samples = stream.read()
                    if not samples:
                        continue
                    with self._lock:
                        if len(self._pending) + len(samples) > MAX_PENDING:
                            self._pending.clear()
                            self._generation += 1
                            self._frame = empty_frame(self.name, "buffer_overrun", self._frame["seq"] + 1)
                        self._pending.extend(samples[-MAX_PENDING:])
                        self._last_input = time.monotonic()
        except Exception:
            LOGGER.exception("CSI acquisition stopped; reconnect and restart the server")
            with self._lock:
                self._error = "disconnected"

    def _process(self):
        analyser, key, generation = LiveAnalyser(buffer_s=BUFFER_S), None, -1
        while not self._stop.wait(1.0):
            with self._lock:
                batch = list(self._pending)
                self._pending.clear()
                current_generation = self._generation
            if not batch:
                continue
            try:
                if generation != current_generation:
                    analyser, key = LiveAnalyser(buffer_s=BUFFER_S), None
                    generation = current_generation
                for sample in batch:
                    p = sample.packet
                    next_key = (p.mac, sample.segment, len(p.csi), p.channel, p.bandwidth, p.secondary_channel)
                    if key != next_key:
                        analyser, key = LiveAnalyser(buffer_s=BUFFER_S), next_key
                    analyser.add(sample.device_time_us / 1e6,
                                 amplitudes(p.csi, p.first_word_invalid), p.rssi, sample.segment)
                state = analyser.update()
                frame = self._state_frame(state, batch[-1])
            except Exception:
                LOGGER.exception("Breathing analysis failed; restarting the processing window")
                analyser, key = LiveAnalyser(buffer_s=BUFFER_S), None
                frame = empty_frame(self.name, "processing_error")
            with self._lock:
                if generation == self._generation:
                    frame["seq"] = self._frame["seq"] + 1
                    self._frame = frame
                    self._last_result = time.monotonic()

    @classmethod
    def _state_frame(cls, state, sample):
        mapping = {"starting": ("no_signal", "warming_up"), "measuring": ("no_signal", "measuring"),
                   "moving": ("motion", "movement"), "no_rhythm": ("no_signal", "unreliable_rhythm"),
                   "breathing": ("breathing", None), "pause": ("pause", "breathing_pause")}
        status, reason = mapping[state.status]
        frame = empty_frame(cls.name, reason)
        # level is set in main.py by the same classifier that drives the phone alarm.
        frame.update(status=status, waveform_delay_s=WAVE_DELAY_S,
                     pause_s=float(state.pause_s) if status == "pause" and state.pause_s is not None
                     and math.isfinite(state.pause_s) else None,
                     calm_s=float(state.calm_s), rssi=state.rssi,
                     packets_per_s=float(state.packets_per_s))
        if state.status == "breathing" and not state.stale and state.rate_bpm is not None and math.isfinite(state.rate_bpm):
            frame["rate_bpm"] = float(state.rate_bpm)
        offset = sample.host_time - sample.device_time_us / 1e6
        # A whole delayed window replaces the prior one; filtering may revise older points.
        frame["waveform"] = [{"t": float(t + offset), "breath": float(value) if np.isfinite(value) else None}
                             for t, value in zip(state.wave_times, state.wave)]
        if frame["waveform"]:
            frame["t"] = frame["waveform"][-1]["t"]
            frame["breath"] = frame["waveform"][-1]["breath"]
        return frame


class ReplaySource(SerialSource):
    """Plays a saved recording in real time, looping, through the same analysis as the board.

    For working on the page without the boards, and as a backup during a demo.
    """
    name = "replay"

    def __init__(self, path):
        super().__init__()
        self.path = path

    def _acquire(self):
        df = pd.read_parquet(self.path)
        t_us = df["device_time_us"].to_numpy(dtype=np.int64)
        packets = [CsiPacket(mac=row.mac, seq=int(row.seq), rssi=int(row.rssi), noise_floor=int(row.noise_floor),
                             bandwidth=1, channel=int(row.channel), secondary_channel=0,
                             timestamp_us=int(row.timestamp_us), first_word_invalid=bool(row.first_word_invalid),
                             csi=np.asarray(row.csi, dtype=np.int8))
                   for row in df.itertuples()]
        # Each loop continues the clock, so the analysis sees one long recording.
        loop_us = int(t_us[-1] - t_us[0]) + int(np.median(np.diff(t_us)))
        i, loop, started = 0, 0, time.monotonic()
        while not self._stop.is_set():
            elapsed_us = (time.monotonic() - started) * 1e6
            batch = []
            while t_us[i] - t_us[0] + loop * loop_us <= elapsed_us:
                batch.append(Sample(time.time(), int(t_us[i] + loop * loop_us), 0, packets[i]))
                i += 1
                if i == len(packets):
                    i, loop = 0, loop + 1
            if batch:
                with self._lock:
                    self._pending.extend(batch)
                    self._last_input = time.monotonic()
            self._stop.wait(0.05)
