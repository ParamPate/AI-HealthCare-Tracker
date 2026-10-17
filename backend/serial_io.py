"""Read CSI packets from the RX board's serial port.

pyserial's readline() reads one byte per call. On Windows that only keeps up with
about 50 CSI lines/s while the board prints about 71/s, so the backlog grows until
lines get corrupted. CsiStream reads whole chunks and splits lines itself.

    with open_port(find_rx_port(921600), 921600) as ser:
        stream = CsiStream(ser)
        while True:
            for sample in stream.read():
                ...  # sample.packet.csi, sample.device_time_us, ...
            print(stream.stats.summary())

CsiStream.read() blocks for up to the port timeout (50 ms), so run it in a
background thread when integrating with an async server.
"""
import json
import time
from collections import Counter
from dataclasses import dataclass
from typing import TextIO

import serial
from serial.tools import list_ports

from backend.csi_format import MAX_LINE_BYTES, PREFIX, CsiPacket, DeviceClock, parse_line

_UINT32 = 1 << 32


def open_port(port: str, baud: int) -> serial.Serial:
    """Open a port without toggling DTR/RTS, which would reset the ESP32."""
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    ser.open()
    if hasattr(ser, "set_buffer_size"):  # Windows only
        ser.set_buffer_size(rx_size=1 << 20)
    return ser


def find_rx_port(baud: int, listen_s: float = 1.5) -> str:
    """Return the USB serial port that is printing CSI_DATA lines (the RX board)."""
    candidates = [p.device for p in list_ports.comports() if p.vid is not None]
    busy = []
    for device in candidates:
        try:
            with open_port(device, baud) as ser:
                deadline = time.monotonic() + listen_s
                tail = b""
                while time.monotonic() < deadline:
                    tail += ser.read(4096)
                    if PREFIX in tail:
                        return device
                    tail = tail[-len(PREFIX):]
        except serial.SerialException:
            busy.append(device)  # usually another program holds it
    if busy:
        raise RuntimeError(
            f"Could not open {', '.join(busy)}: another program is probably using it. Close the "
            "live view, idf.py monitor, or any other serial tool, then try again."
        )
    checked = ", ".join(candidates) or "none found"
    raise RuntimeError(
        f"No USB serial port is printing CSI_DATA (checked: {checked}). Check that the RX board "
        "is plugged in, the TX board is powered (RX prints nothing without it), and no other "
        "program (like idf.py monitor) is using the RX port."
    )


class LineBuffer:
    """Accumulate serial chunks and hand back complete lines, newline included.

    Only LF ends a line. A line longer than MAX_LINE_BYTES is dropped up to its
    newline and counted in `oversized`, so noise or a wrong baud rate can't grow
    the buffer without limit.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._discarding = False
        self.oversized = 0

    def feed(self, chunk: bytes) -> list[bytes]:
        lines = []
        pieces = chunk.split(b"\n")
        for i, piece in enumerate(pieces):
            complete = i < len(pieces) - 1
            if not self._discarding:
                self._buf += piece
                if len(self._buf) + complete > MAX_LINE_BYTES:
                    self.oversized += 1
                    self._buf.clear()
                    self._discarding = True
            if complete:
                if not self._discarding:
                    lines.append(bytes(self._buf) + b"\n")
                self._buf.clear()
                self._discarding = False
        return lines


@dataclass(frozen=True, slots=True)
class Sample:
    host_time: float     # Unix seconds when the chunk arrived (includes USB buffering delay)
    device_time_us: int  # continuous RX clock; only comparable within one segment
    segment: int         # increases when the RX clock jumps back (board restart)
    packet: CsiPacket


class CaptureStats:
    """Running counts for one capture: accepted, rejected by reason, and lost packets."""

    def __init__(self) -> None:
        self.accepted = 0
        self.rejected: Counter[str] = Counter()
        self.missing_ids = 0      # estimated from forward gaps in TX sequence numbers
        self.discontinuities = 0  # sequence went backwards (TX restart or reordering)
        self.last_valid: float | None = None  # time.monotonic() of the newest packet
        self._last_seq: dict[str, tuple[int, int]] = {}

    def accept(self, mac: str, seq: int, segment: int) -> None:
        self.accepted += 1
        self.last_valid = time.monotonic()
        previous = self._last_seq.get(mac)
        if previous is not None and previous[1] == segment:
            delta = (seq - previous[0]) % _UINT32
            if 0 < delta < _UINT32 // 2:
                self.missing_ids += delta - 1
            elif delta >= _UINT32 // 2:
                self.discontinuities += 1
        self._last_seq[mac] = (seq, segment)

    @property
    def drop_fraction(self) -> float:
        total = self.accepted + self.missing_ids
        return self.missing_ids / total if total else 0.0

    def summary(self) -> str:
        age = "never" if self.last_valid is None else f"{time.monotonic() - self.last_valid:.1f}s ago"
        reasons = f" reasons={dict(self.rejected)}" if self.rejected else ""
        return (f"accepted={self.accepted} rejected={sum(self.rejected.values())} "
                f"missing_ids={self.missing_ids} ({100 * self.drop_fraction:.1f}%) "
                f"discontinuities={self.discontinuities} last_valid={age}{reasons}")


class CsiStream:
    """Parsed CSI from an open RX port. Call read() in a loop; check .stats any time.

    raw_log, if given, is an open text file that receives every complete line as
    JSONL ({received_at, received_monotonic, raw_line}), including boot logs and
    damaged lines, so parsing problems can be investigated later. Recover the exact
    bytes with row["raw_line"].encode("latin-1"). The caller flushes and closes it.
    """

    def __init__(self, ser: serial.Serial, raw_log: TextIO | None = None) -> None:
        self._ser = ser
        self._raw_log = raw_log
        self._lines = LineBuffer()
        self._clocks: dict[str, DeviceClock] = {}
        self.stats = CaptureStats()

    def read(self) -> list[Sample]:
        """Read what the port has (waiting up to its timeout) and return the new samples."""
        chunk = self._ser.read(max(1, self._ser.in_waiting))
        if not chunk:
            return []
        now, now_monotonic = time.time(), time.monotonic()
        samples = []
        for raw in self._lines.feed(chunk):
            if self._raw_log is not None:
                self._raw_log.write(json.dumps({"received_at": now, "received_monotonic": now_monotonic,
                                                "raw_line": raw.decode("latin-1")}) + "\n")
            try:
                packet = parse_line(raw)
            except ValueError as e:
                self.stats.rejected[str(e)] += 1
                continue
            if packet is None:
                continue
            device_time_us, segment = self._clocks.setdefault(packet.mac, DeviceClock())(packet.timestamp_us)
            self.stats.accept(packet.mac, packet.seq, segment)
            samples.append(Sample(now, device_time_us, segment, packet))
        if self._lines.oversized:
            self.stats.rejected["oversized serial line"] = self._lines.oversized
        return samples
