"""Record CSI from the RX board into recordings/<timestamp>_<label>.parquet.

    uv run python -m backend.record --label breathing --seconds 60

One row per packet: host time, device time, RSSI, and the raw interleaved CSI array
(int8, imaginary first). Rows are written in batches, so a crash or Ctrl+C keeps
everything recorded so far. With --raw-log, every serial line (including boot logs
and damaged lines) also goes to <same name>.raw.jsonl for debugging the parser.
Raw CSI stays on this machine (recordings/ is gitignored).
"""
import argparse
import re
import sys
import time
from contextlib import ExitStack
from datetime import datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import serial

from backend import config
from backend.serial_io import CsiStream, Sample, find_rx_port, open_port

FLUSH_EVERY_S = 10.0

SCHEMA = pa.schema([
    ("host_time", pa.float64()),        # PC clock, Unix seconds
    ("device_time_us", pa.int64()),     # RX board clock, unwrapped, microseconds
    ("segment", pa.int32()),            # increases if the RX board restarts mid-recording
    ("timestamp_us", pa.uint32()),      # RX board clock as printed (wraps)
    ("mac", pa.string()),               # transmitter
    ("seq", pa.uint32()),               # TX sequence number; gaps = dropped packets
    ("rssi", pa.int16()),
    ("noise_floor", pa.int16()),
    ("channel", pa.int16()),
    ("first_word_invalid", pa.bool_()),
    ("csi", pa.list_(pa.int8())),       # [im0, re0, im1, re1, ...]
])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--label", required=True, help="short name for the session, e.g. wave or breathing")
    p.add_argument("--seconds", type=float, help="stop after this long (default: until Ctrl+C)")
    p.add_argument("--countdown", type=int, default=5, help="seconds to wait before recording starts")
    p.add_argument("--raw-log", action="store_true", help="also save every raw serial line as JSONL")
    p.add_argument("--port", default=config.SERIAL_PORT, help="RX serial port (default: auto-detect)")
    p.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    return p.parse_args()


def to_table(batch: list[Sample]) -> pa.Table:
    packets = [s.packet for s in batch]
    lengths = np.fromiter((len(p.csi) for p in packets), dtype=np.int32, count=len(packets))
    offsets = pa.array(np.concatenate([[0], np.cumsum(lengths)]).astype(np.int32))
    values = pa.array(np.concatenate([p.csi for p in packets]), type=pa.int8())
    return pa.table({
        "host_time": [s.host_time for s in batch],
        "device_time_us": [s.device_time_us for s in batch],
        "segment": [s.segment for s in batch],
        "timestamp_us": [p.timestamp_us for p in packets],
        "mac": [p.mac for p in packets],
        "seq": [p.seq for p in packets],
        "rssi": [p.rssi for p in packets],
        "noise_floor": [p.noise_floor for p in packets],
        "channel": [p.channel for p in packets],
        "first_word_invalid": [p.first_word_invalid for p in packets],
        "csi": pa.ListArray.from_arrays(offsets, values),
    }, schema=SCHEMA)


def main() -> None:
    args = parse_args()
    try:
        port = args.port or find_rx_port(args.baud)
    except RuntimeError as e:
        sys.exit(str(e))
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", args.label).strip("-") or "session"
    config.RECORDINGS_DIR.mkdir(exist_ok=True)
    started = datetime.now()
    path = config.RECORDINGS_DIR / f"{started:%Y%m%d-%H%M%S}_{label}.parquet"
    raw_path = path.with_suffix(".raw.jsonl")
    metadata = {"label": args.label, "port": port, "baud": str(args.baud), "started": started.isoformat()}

    error = None
    with ExitStack() as stack:
        ser = stack.enter_context(open_port(port, args.baud))
        raw_log = stack.enter_context(raw_path.open("x", encoding="utf-8")) if args.raw_log else None
        print(f"RX board on {port}. Recording '{args.label}' to {path.relative_to(config.REPO_ROOT)}")
        for remaining in range(args.countdown, 0, -1):
            print(f"  starting in {remaining}...", end="\r", flush=True)
            time.sleep(1)
        print("\a>>> RECORDING" + (f" for {args.seconds:.0f} s" if args.seconds else ", Ctrl+C to stop") + " " * 10)

        ser.reset_input_buffer()
        stream = CsiStream(ser, raw_log)
        writer = pq.ParquetWriter(path, SCHEMA.with_metadata(metadata))
        batch: list[Sample] = []
        t0 = last_flush = last_status = time.time()
        try:
            while args.seconds is None or time.time() - t0 < args.seconds:
                batch += stream.read()
                now = time.time()
                if now - last_flush >= FLUSH_EVERY_S and batch:
                    writer.write_table(to_table(batch))
                    if raw_log is not None:
                        raw_log.flush()
                    batch, last_flush = [], now
                if now - last_status >= 1.0:
                    s = stream.stats
                    rssi = batch[-1].packet.rssi if batch else "--"
                    print(f"  {now - t0:6.1f} s  {s.accepted / (now - t0):5.1f} pkt/s  "
                          f"dropped {100 * s.drop_fraction:4.1f}%  rejected {sum(s.rejected.values())}  "
                          f"rssi {rssi} dBm", end="\r", flush=True)
                    last_status = now
        except KeyboardInterrupt:
            pass
        except serial.SerialException as e:
            error = e
        finally:
            if batch:
                writer.write_table(to_table(batch))
            writer.close()

    elapsed = time.time() - t0
    stats = stream.stats
    print(f"\a\n>>> STOPPED after {elapsed:.1f} s: {stats.accepted} packets "
          f"({stats.accepted / max(elapsed, 1e-9):.1f}/s)")
    print(f"    {stats.summary()}")
    if error is not None:
        print(f"Serial connection lost: {error}. Check the RX USB cable, then start a new recording.")
    if stats.accepted == 0:
        path.unlink(missing_ok=True)
        sys.exit("No CSI packets received. Is the TX board powered?")
    print(f"Saved {path} ({path.stat().st_size / 1e6:.1f} MB)" + (f" and {raw_path.name}" if raw_log else ""))
    if error is not None:
        sys.exit(1)


if __name__ == "__main__":
    main()
