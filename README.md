# AI-HealthCare-Tracker
Hack the Valley

Contactless breathing monitor: two ESP32 boards exchange Wi-Fi packets, and the
receiver reports Channel State Information (CSI) for each one. Breathing changes
the radio channel slightly, so it shows up as a slow wave in the CSI.

```
ESP32 TX ~~Wi-Fi~~> ESP32 RX --USB serial--> backend/ (Python) --> web app
csi_send            csi_recv                 read, record,
                                             process
```

## Setup

**Boards.** Two classic ESP32 boards flashed with Espressif's
[esp-csi](https://github.com/espressif/esp-csi) `examples/get-started` firmware:
`csi_send` on TX, `csi_recv` on RX. Build with ESP-IDF **v5.5.x**; esp-csi does not
compile on IDF 6.x. TX only needs USB power; RX connects to the computer.

**Python.** Install [uv](https://docs.astral.sh/uv/), then from the project root:

```bash
uv sync
```

Every command below finds the RX board automatically (it listens for `CSI_DATA`
lines). Pass `--port COM6` or `--port /dev/cu.usbserial-0001` to choose one.
Only one program can use the RX port at a time, so close `idf.py monitor`, the live
view, or a running recording before starting another.

## See what RX receives

```bash
uv run python -m backend.live_view
```

A window shows each subcarrier's amplitude over the last 30 s (movement appears
as vertical streaks) and a smoothed preview where slow breathing should look like
a slow wave. Use it to place the boards. Close the window to stop.

## Record a session

```bash
uv run python -m backend.record --label breathing --seconds 70
```

After a 5 s countdown (`--countdown`), packets are saved to
`recordings/<date>-<time>_<label>.parquet`, one row per packet: host time,
continuous device time, `segment`, transmitter MAC, sequence number, RSSI, noise
floor, channel, and the raw CSI array (int8, imaginary first, then real). Rows are
written every 10 s, so Ctrl+C or a crash keeps what was recorded. `recordings/` is
gitignored: raw CSI stays on the machine that recorded it.

Add `--raw-log` to also save every serial line, including boot logs and damaged
lines, to `<same name>.raw.jsonl`. Each row has `received_at` (Unix seconds),
`received_monotonic` (host monotonic seconds), and `raw_line`. Recover the exact
bytes with `row["raw_line"].encode("latin-1")` and re-parse them with
`backend.csi_format.parse_line`. Lines over 16 KiB are dropped, not logged.

While recording, the status line shows packets/s, the estimated drop rate, the
number of rejected lines, and RSSI. The summary at the end adds rejection reasons,
missing IDs, and sequence discontinuities. Missing IDs are estimated from forward
gaps in the TX sequence numbers, not proof of where data was lost; reordered
packets and restarts can affect them. They are tracked per transmitter and reset
when the timing segment changes. If the RX board is unplugged, recording stops
with a clear error and keeps the packets saved so far.

Expected numbers with the stock firmware: TX sends about 91 packets/s, and RX can
print about 71/s at 921600 baud (each line carries 192 subcarriers), so about 22%
of packets are dropped on the board. That is plenty for breathing (0.1 to 0.5 Hz).

## Analyse a recording

```bash
uv run python signal-processing/explore.py recordings/<file>.parquet
```

Add `--start`/`--end` (seconds) to analyse part of a recording. Prints a summary
and saves a PNG next to the recording. The analysis lives in `backend/breathing.py`
so the live server can reuse it:

1. Movement (energy above 1 Hz, which breathing barely has) is detected and ignored.
2. Inside movement the signal is frozen, so posture shifts can't ring through the
   filters as fake slow waves; slow drift is removed with a rolling median.
3. Subcarriers are picked by how rhythmic they are, not how much they change.
4. A rate (3 to 30 breaths/min) is only reported as breathing if it lasts at least
   3 cycles of calm data, stays steady over time, and stands out across all
   subcarriers. Energy at half the rate is noted, since the signal can show two
   bumps per breath; only marked breaths can settle that.

If the RX board restarted during the recording, the longest uninterrupted stretch
is analysed.

## Using the reader from code

`backend/serial_io.py` is the one place that reads the RX port:

```python
from backend.serial_io import CsiStream, find_rx_port, open_port

with open_port(find_rx_port(921600), 921600) as ser:
    stream = CsiStream(ser)            # optional: CsiStream(ser, raw_log=open_file)
    while True:
        for sample in stream.read():   # waits up to 50 ms, returns new samples
            ...
        stream.stats.summary()         # accepted, rejected by reason, missing IDs
```

Each `Sample` has `host_time` (Unix seconds when the chunk arrived, including USB
buffering delay), `device_time_us` (continuous RX clock), `segment`, and `packet`.
A `CsiPacket` (`backend/csi_format.py`) has `mac`, `seq`, `rssi`, `noise_floor`,
`bandwidth`, `channel`, `secondary_channel`, `timestamp_us` (as printed, made
unsigned), `first_word_invalid`, and `csi` (int8 numpy array `[im0, re0, im1, re1, ...]`).
`amplitudes(csi, first_word_invalid)` turns it into per-subcarrier amplitudes.

Things the processing pipeline must respect:

- When `first_word_invalid` is set, the first two subcarriers are garbage.
  `amplitudes()` zeroes them so indices stay aligned.
- The RX clock is a uint32 that wraps every ~71.6 min. A backward jump of more than
  half the 32-bit range counts as a wrap; a smaller one means the board restarted
  and starts a new `segment`. Never compare times across segments. Reboots after
  long outages can look like wraps, because the firmware prints no boot ID.
- Restart processing windows when the transmitter, segment, CSI length, or radio
  configuration changes.
- `read()` blocks briefly, so run it in a background thread next to an async server.

`parse_line()` returns `None` for non-CSI lines and raises `ValueError` naming the
problem for damaged ones. Only the classic ESP32 25-column layout is supported; the
ESP32-C5/C6 15-column layout is rejected with a clear message.

## Tests

```bash
uv run pytest
```

Covers parsing and validation (including real captured lines in
`docs/sample_csi_lines.txt`), clock wraparound and restarts, line splitting,
statistics, raw logging, and the Parquet format, all without hardware. Physical
throughput, placement, and breathing detection still need hardware trials.

## Teammate hardware check

1. Pull the latest `main`, run `uv sync`, and keep both ESP32s powered.
2. Close `idf.py monitor`, the live view, and any other serial tool.
3. Record an empty chair: `uv run python -m backend.record --label empty-chair --seconds 60 --raw-log`.
   Confirm the packet rate appears.
4. Record 60 to 120 seconds of still, normal breathing (`--label breathing`) and
   20 to 30 seconds of deliberate movement (`--label movement`). Note the board
   placement and what you did in each trial.
5. As a connection check, unplug the RX board during a recording and confirm a
   clear error. Reconnect and start a new recording.
6. Send the recordings and their printed summaries back for analysis.
   `recordings/` is gitignored, so pushing code does not transfer captures.
