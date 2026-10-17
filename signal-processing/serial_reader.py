"""Read complete lines from the ESP32 receiver's USB serial port."""

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import sys
import time


MAX_LINE_BYTES = 16 * 1024
LOGGER = logging.getLogger(__name__)
COLUMNS = (
    "type", "id", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth",
    "smoothing", "not_sounding", "aggregation", "stbc", "fec_coding", "sgi",
    "noise_floor", "ampdu_cnt", "channel", "secondary_channel", "local_timestamp",
    "ant", "sig_len", "rx_format", "len", "first_word", "data",
)


@dataclass(frozen=True)
class CSISample:
    packet_id: int
    mac: str
    rssi: int
    channel: int
    received_at: float
    received_monotonic: float
    device_timestamp_raw: int
    device_time_us: int
    time_segment: int
    metadata: dict
    raw_iq: tuple
    csi: tuple
    valid_mask: tuple
    raw_line: bytes


class CaptureStats:
    def __init__(self, rejected):
        self.rejected = rejected
        self.accepted = 0
        self.missing_ids = 0
        self.sequence_discontinuities = 0
        self.previous_ids = {}
        self.last_valid = None
        self.last_report = time.monotonic()
        self.last_count = 0

    def accept(self, sample):
        self.accepted += 1
        self.last_valid = sample.received_monotonic
        previous = self.previous_ids.get(sample.mac)
        if previous is not None and previous[1] == sample.time_segment:
            delta = (sample.packet_id - previous[0]) & 0xFFFFFFFF
            if 0 < delta < 2**31:
                self.missing_ids += delta - 1
            elif delta >= 2**31:
                self.sequence_discontinuities += 1
        self.previous_ids[sample.mac] = (sample.packet_id, sample.time_segment)

    def report(self, now):
        elapsed = now - self.last_report
        if elapsed < 5:
            return
        rate = (self.accepted - self.last_count) / elapsed
        age = "never" if self.last_valid is None else f"{now - self.last_valid:.1f}s ago"
        print(
            f"CSI: {rate:.1f} packets/s | accepted={self.accepted} | "
            f"rejected={sum(self.rejected.values())} | missing_ids={self.missing_ids} | "
            f"sequence_discontinuities={self.sequence_discontinuities} | "
            f"last_valid={age} | rejection_reasons={dict(self.rejected)}",
            file=sys.stderr,
        )
        self.last_report = now
        self.last_count = self.accepted


def parse_line(line):
    """Return a validated ESP32 packet, None for logs, or raise ValueError."""
    if not line.startswith(b"CSI_DATA,"):
        return None
    if len(line) > MAX_LINE_BYTES:
        raise ValueError("line exceeds maximum length")
    try:
        row = next(csv.reader([line.decode("ascii").rstrip("\r\n")], strict=True))
    except (UnicodeDecodeError, csv.Error) as error:
        raise ValueError("invalid CSV or text encoding") from error
    if len(row) == 15:
        raise ValueError("unsupported 15-column CSI layout; expected classic ESP32 format")
    if len(row) != len(COLUMNS):
        raise ValueError("expected 25 CSV columns")
    packet = dict(zip(COLUMNS, row))
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", packet["mac"]):
        raise ValueError("invalid transmitter MAC")
    packet["mac"] = packet["mac"].lower()
    try:
        for name in COLUMNS:
            if name not in ("type", "mac", "data"):
                packet[name] = int(packet[name])
    except ValueError as error:
        raise ValueError("invalid integer metadata") from error
    for name in ("id", "local_timestamp"):
        if not -(2**31) <= packet[name] <= 2**32 - 1:
            raise ValueError("packet ID or timestamp outside 32-bit range")
    if packet["first_word"] not in (0, 1):
        raise ValueError("first_word must be 0 or 1")
    if not 1 <= packet["channel"] <= 14:
        raise ValueError("invalid 2.4 GHz channel")
    if not -128 <= packet["rssi"] <= 127:
        raise ValueError("RSSI outside signed-byte range")
    if packet["len"] <= 0 or packet["len"] % 2:
        raise ValueError("CSI length must be positive and even")
    try:
        data = json.loads(packet["data"])
    except (ValueError, RecursionError) as error:
        raise ValueError("invalid CSI JSON array") from error
    if not isinstance(data, list) or len(data) != packet["len"]:
        raise ValueError("CSI array length does not match declared length")
    if any(type(value) is not int or not -128 <= value <= 127 for value in data):
        raise ValueError("CSI values must be signed-byte integers")
    packet["data"] = data
    return packet


def read_lines(connection, poll=None, rejected=None):
    """Yield newline-terminated bytes, retaining fragments across read timeouts."""
    pending = bytearray()
    discarding = False
    while True:
        chunk = connection.read(min(connection.in_waiting or 1, 4096))
        if poll is not None:
            poll()
        # An empty read is a timeout, not the end of a live serial stream.
        if not chunk:
            continue
        for piece in chunk.splitlines(keepends=True):
            # Only LF terminates firmware records; splitlines also splits on CR.
            complete = piece.endswith(b"\n")
            if not discarding:
                pending.extend(piece)
                if len(pending) > MAX_LINE_BYTES:
                    if rejected is not None:
                        rejected["oversized serial line"] += 1
                    if rejected is None or rejected["oversized serial line"] == 1:
                        LOGGER.warning("Discarding serial line exceeding %d bytes", MAX_LINE_BYTES)
                    pending.clear()
                    discarding = True
            if complete:
                if not discarding:
                    yield bytes(pending)
                pending.clear()
                discarding = False


def read_samples(connection, rejected=None, recording=None, diagnostics=False):
    """Yield CSI samples from an open serial connection owned by the caller.

    A new iterator starts a new capture session. Device time is continuous only
    within the same transmitter and time_segment. Calls block on serial input;
    run acquisition outside the server's async event loop. Optional recording
    is a text file owned by the caller; diagnostics are written to stderr.
    """
    if rejected is None:
        rejected = Counter()
    stats = CaptureStats(rejected)
    last_flush = time.monotonic()

    def poll():
        nonlocal last_flush
        now = time.monotonic()
        if diagnostics:
            stats.report(now)
        if recording is not None and now - last_flush >= 1:
            recording.flush()
            last_flush = now

    clocks = {}
    for line in read_lines(connection, poll=poll, rejected=rejected):
        received_at = time.time()
        received_monotonic = time.monotonic()
        if recording is not None:
            # Latin-1 round-trips every byte, including malformed serial output.
            recording.write(json.dumps({
                "received_at": received_at,
                "received_monotonic": received_monotonic,
                "raw_line": line.decode("latin-1"),
            }) + "\n")
        try:
            packet = parse_line(line)
        except ValueError as error:
            reason = str(error)
            rejected[reason] += 1
            if rejected[reason] == 1:
                LOGGER.warning("Skipping CSI packet: %s", reason)
            continue
        if packet is None:
            continue

        timestamp = packet["local_timestamp"] & 0xFFFFFFFF
        previous, offset, segment = clocks.get(packet["mac"], (timestamp, 0, 0))
        if timestamp < previous:
            # shortcut: counter-only rollover detection is ambiguous after resets
            # or long outages; add firmware boot IDs if those must be distinguished.
            if previous - timestamp > 2**31:
                offset += 2**32
            else:
                offset = 0
                segment += 1
        clocks[packet["mac"]] = (timestamp, offset, segment)

        raw_iq = tuple(packet["data"])
        csi = tuple(complex(raw_iq[i + 1], raw_iq[i]) for i in range(0, len(raw_iq), 2))
        valid_mask = tuple(not (packet["first_word"] and i < 2) for i in range(len(csi)))
        sample = CSISample(
            packet_id=packet["id"] & 0xFFFFFFFF,
            mac=packet["mac"],
            rssi=packet["rssi"],
            channel=packet["channel"],
            received_at=received_at,
            received_monotonic=received_monotonic,
            device_timestamp_raw=packet["local_timestamp"],
            device_time_us=timestamp + offset,
            time_segment=segment,
            metadata={name: value for name, value in packet.items() if name != "data"},
            raw_iq=raw_iq,
            csi=csi,
            valid_mask=valid_mask,
            raw_line=line,
        )
        stats.accept(sample)
        yield sample


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Receiver port, e.g. /dev/cu.usbserial-0001")
    parser.add_argument("--baud", type=positive_int, default=921600, help="Baud rate (default: 921600)")
    parser.add_argument("--record", type=Path, help="Create a new raw JSONL recording (never overwrite)")
    args = parser.parse_args(argv)
    try:
        import serial
    except ImportError:
        print("Install pyserial: python3 -m pip install -r signal-processing/requirements.txt", file=sys.stderr)
        return 1

    rejected = Counter()
    try:
        with ExitStack() as resources:
            recording = None
            if args.record is not None:
                args.record.parent.mkdir(parents=True, exist_ok=True)
                recording = resources.enter_context(args.record.open("x", encoding="utf-8"))
            connection = resources.enter_context(serial.Serial(args.port, baudrate=args.baud, timeout=1))
            print(f"Reading {args.port} at {args.baud} baud. Press Ctrl-C to stop.", file=sys.stderr)
            if args.record is not None:
                print(f"Recording to {args.record}", file=sys.stderr)
            for sample in read_samples(connection, rejected, recording=recording, diagnostics=True):
                sys.stdout.buffer.write(sample.raw_line)
                sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        print("\nSerial reader stopped.", file=sys.stderr)
        return 0
    except (serial.SerialException, OSError) as error:
        print(
            f"Serial reader failed: {error}\n"
            "Check the USB connection and port, close other serial monitors, "
            "and check the recording path if provided, then restart.",
            file=sys.stderr,
        )
        return 1
    finally:
        if rejected:
            print(f"Rejected CSI packets by reason: {dict(rejected)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
