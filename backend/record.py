"""Record CSI from the RX board into recordings/<timestamp>_<label>.parquet.

    uv run python -m backend.record --label breathing --seconds 60

One row per packet: host time, device time, RSSI, and the raw interleaved CSI array
(int8, imaginary first). Rows are written in batches, so a crash or Ctrl+C keeps
everything recorded so far. Raw CSI stays on this machine (recordings/ is gitignored).
"""
import argparse
import re
import sys
import time
from datetime import datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from backend import config
from backend.csi_format import CsiPacket, TimestampUnwrapper, parse_line
from backend.serial_io import LineBuffer, find_rx_port, open_port

FLUSH_EVERY_S = 10.0

SCHEMA = pa.schema([
    ("host_time", pa.float64()),        # PC clock, Unix seconds
    ("device_time_us", pa.int64()),     # RX board clock, unwrapped, microseconds
    ("timestamp_us", pa.uint32()),      # RX board clock as printed (wraps)
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
    p.add_argument("--port", default=config.SERIAL_PORT, help="RX serial port (default: auto-detect)")
    p.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    return p.parse_args()


def to_table(batch: list[tuple[float, int, CsiPacket]]) -> pa.Table:
    packets = [p for _, _, p in batch]
    lengths = np.fromiter((len(p.csi) for p in packets), dtype=np.int32, count=len(packets))
    offsets = pa.array(np.concatenate([[0], np.cumsum(lengths)]).astype(np.int32))
    values = pa.array(np.concatenate([p.csi for p in packets]), type=pa.int8())
    return pa.table({
        "host_time": [h for h, _, _ in batch],
        "device_time_us": [d for _, d, _ in batch],
        "timestamp_us": [p.timestamp_us for p in packets],
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
    metadata = {"label": args.label, "port": port, "baud": str(args.baud), "started": started.isoformat()}

    with open_port(port, args.baud) as ser:
        print(f"RX board on {port}. Recording '{args.label}' to {path.relative_to(config.REPO_ROOT)}")
        for remaining in range(args.countdown, 0, -1):
            print(f"  starting in {remaining}...", end="\r", flush=True)
            time.sleep(1)
        print("\a>>> RECORDING" + (f" for {args.seconds:.0f} s" if args.seconds else ", Ctrl+C to stop") + " " * 10)

        ser.reset_input_buffer()
        lines, unwrap = LineBuffer(), TimestampUnwrapper()
        writer = pq.ParquetWriter(path, SCHEMA.with_metadata(metadata))
        batch: list[tuple[float, int, CsiPacket]] = []
        total = malformed = 0
        first_seq = last_seq = None
        t0 = last_flush = last_status = time.time()
        try:
            while args.seconds is None or time.time() - t0 < args.seconds:
                chunk = ser.read(max(1, ser.in_waiting))
                now = time.time()
                for raw in lines.feed(chunk):
                    packet = parse_line(raw)
                    if packet is None:
                        malformed += raw.startswith(b"CSI_DATA")
                        continue
                    batch.append((now, unwrap(packet.timestamp_us), packet))
                    first_seq = packet.seq if first_seq is None else first_seq
                    last_seq = packet.seq
                    total += 1
                if now - last_flush >= FLUSH_EVERY_S and batch:
                    writer.write_table(to_table(batch))
                    batch, last_flush = [], now
                if now - last_status >= 1.0 and total:
                    sent = (last_seq - first_seq) % (1 << 32) + 1
                    print(f"  {now - t0:6.1f} s  {total / (now - t0):5.1f} pkt/s  "
                          f"dropped {100 * (1 - total / sent):4.1f}%  rssi {batch[-1][2].rssi if batch else '--'} dBm",
                          end="\r", flush=True)
                    last_status = now
        except KeyboardInterrupt:
            pass
        finally:
            if batch:
                writer.write_table(to_table(batch))
            writer.close()

    elapsed = time.time() - t0
    print(f"\a\n>>> STOPPED after {elapsed:.1f} s: {total} packets ({total / max(elapsed, 1e-9):.1f}/s), "
          f"{malformed} malformed lines")
    if total == 0:
        path.unlink(missing_ok=True)
        sys.exit("No CSI packets received. Is the TX board powered?")
    print(f"Saved {path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
