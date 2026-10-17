"""Read complete lines from the ESP32 receiver's USB serial port."""

import argparse
import logging
import sys


MAX_LINE_BYTES = 16 * 1024
LOGGER = logging.getLogger(__name__)


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

    try:
        with serial.Serial(args.port, baudrate=args.baud, timeout=1) as connection:
            print(f"Reading {args.port} at {args.baud} baud. Press Ctrl-C to stop.", file=sys.stderr)
            for line in read_lines(connection):
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
