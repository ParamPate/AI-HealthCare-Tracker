"""Read complete lines from the ESP32 receiver's USB serial port."""

import argparse
from collections import Counter
import csv
import json
import logging
import re
import sys


MAX_LINE_BYTES = 16 * 1024
LOGGER = logging.getLogger(__name__)
COLUMNS = (
    "type", "id", "mac", "rssi", "rate", "sig_mode", "mcs", "bandwidth",
    "smoothing", "not_sounding", "aggregation", "stbc", "fec_coding", "sgi",
    "noise_floor", "ampdu_cnt", "channel", "secondary_channel", "local_timestamp",
    "ant", "sig_len", "rx_format", "len", "first_word", "data",
)


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


def read_lines(connection):
    """Yield newline-terminated bytes, retaining fragments across read timeouts."""
    pending = bytearray()
    discarding = False
    while True:
        chunk = connection.read(min(connection.in_waiting or 1, 4096))
        # An empty read is a timeout, not the end of a live serial stream.
        if not chunk:
            continue
        for piece in chunk.splitlines(keepends=True):
            # Only LF terminates firmware records; splitlines also splits on CR.
            complete = piece.endswith(b"\n")
            if not discarding:
                pending.extend(piece)
                if len(pending) > MAX_LINE_BYTES:
                    LOGGER.warning("Discarding serial line exceeding %d bytes", MAX_LINE_BYTES)
                    pending.clear()
                    discarding = True
            if complete:
                if not discarding:
                    yield bytes(pending)
                pending.clear()
                discarding = False


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Receiver port, e.g. /dev/cu.usbserial-0001")
    parser.add_argument("--baud", type=positive_int, default=921600, help="Baud rate (default: 921600)")
    args = parser.parse_args(argv)
    try:
        import serial
    except ImportError:
        print("Install pyserial: python3 -m pip install -r signal-processing/requirements.txt", file=sys.stderr)
        return 1

    rejected = Counter()
    try:
        with serial.Serial(args.port, baudrate=args.baud, timeout=1) as connection:
            print(f"Reading {args.port} at {args.baud} baud. Press Ctrl-C to stop.", file=sys.stderr)
            for line in read_lines(connection):
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
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()
    except KeyboardInterrupt:
        print("\nSerial reader stopped.", file=sys.stderr)
        return 0
    except (serial.SerialException, OSError) as error:
        print(
            f"Serial reader failed: {error}\n"
            "Check the USB connection and port, close other serial monitors, then restart.",
            file=sys.stderr,
        )
        return 1
    finally:
        if rejected:
            print(f"Rejected CSI packets by reason: {dict(rejected)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
