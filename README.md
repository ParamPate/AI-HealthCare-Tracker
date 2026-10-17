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

## Live breathing monitor

```bash
uv run python -m backend.live                                      # from the RX board
uv run python -m backend.live --replay recordings/<file>.parquet  # a recording, in real time
```

Once a second the last 60 s are analysed (same `backend/breathing.py`) and one line
is printed: status, rate, calm data, a sketch of the last 16 s of the breathing
wave, RSSI, and packets/s. Ctrl+C prints a summary, including the median rate
while BREATHING was shown, to compare with a manual breath count.

| Status | Meaning |
|---|---|
| STARTING | first 10 s of data |
| MEASURING | not enough calm data yet (needs about 30 s), or a rhythm not yet confirmed |
| BREATHING | a steady rhythm in 3 updates in a row, agreeing within 2/min |
| MOVEMENT | movement right now; the last rate stays on screen, marked "(last)", for up to 10 s |
| NO RHYTHM | enough calm data but no steady rhythm (the rate is cleared: this can be a pause) |
| PAUSE | breathing was confirmed, the person is still, and the breathing wave has gone flat; shows seconds without a breath. First alert about 11 s into a pause, clears about 5 s after breathing resumes |

Press Enter while it runs to mark a moment, such as the start and end of a breath
hold; marks are printed and listed in the summary.

From the board, every session is also saved: the packets as
`recordings/<date>-<time>_<label>.parquet` (same format as `backend.record`, so it can
be replayed or analysed; `--label`, default `live`) and the printed lines as a `.txt`
next to it. `--replay ... --speed 0` runs as fast as possible, and `--debug` adds the
numbers behind each verdict. `LiveAnalyser` in `backend/live.py` is what the server will use.

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

## Live server and phone alarm

Run one server from the project root (close other serial readers first):

```bash
uv run python -m backend.main --source serial --port /dev/cu.usbserial-0001 --host 0.0.0.0
```

On the same Wi-Fi network, open `http://<computer-LAN-IP>:8000/phone` on the phone
and tap **Enable alarm**. Keep the page open and the phone awake. Sound depends on
browser audio permission; vibration is optional and is not supported on every
phone. This is a local demo server with no authentication; use a trusted LAN.

To try the complete alert path without boards:

```bash
uv run python -m backend.main --source fake --host 0.0.0.0
```

The fake source cycles through breathing, a 16 s pause, movement, and missing input.
An alarm should appear around 42–44 s after startup and is marked **DEMO**. Acknowledge
it on the phone. For an immediate delivery/sound check, bypass classification with:

```bash
curl -X POST http://localhost:8000/api/demo/alert
```

The live path is:

```
serial_io → LiveAnalyser → SerialSource → shared server publisher
    → breathing classification → timed alert → /ws/dashboard → phone sound
```

The shared publisher runs independently of browser connections. It evaluates new
snapshots at most once a second; opening more tabs or receiving the same snapshot
again does not advance alert confirmation. It publishes these rule-based classes:

| Class | Input | Result |
|---|---|---|
| normal | confirmed RR 10–22/min | normal |
| slow_breathing | confirmed RR below 10/min | warning; critical below 8/min |
| fast_breathing | confirmed RR above 22/min | warning; critical above 28/min |
| breathing_pause | detector reports a pause with duration | warning below 10 s; critical from 10 s |
| motion / no_signal | movement, warmup, unreliable rhythm, missing packets | unknown; interrupts pending alarm |

Critical readings must continue for **2 elapsed seconds** with fresh updates and
the same classification. A gap longer than 2.5 s resets confirmation. The live
pause detector itself uses an 8 s window ending 3 s ago; delivery therefore has
that detection delay **plus** confirmation time, and filtering can add more delay.
These are prototype thresholds, not a trained or clinically validated model.
The current DSP only estimates rates within 3–30/min, so fast-rate detection has
limited range. It does not classify shallow breathing or diagnose apnea.

One alert is sent per episode. It stays active until acknowledged. Acknowledgement
silences all connected phones; it does not immediately rearm the detector. Three
seconds of fresh normal breathing rearm it for a later episode. Motion and signal
loss cannot rearm it. Unacknowledged alerts survive a server restart and are sent
when a phone reconnects. SQLite adds the new alert columns without deleting data.

### Frontend and teammate contract

- `/ws`: existing waveform stream (~15 messages/s), now including `pause_s`.
  Serial analysis updates about once a second; use `seq` to deduplicate waveforms.
- `/ws/dashboard`: phone events. First message is
  `{"type":"snapshot","alerts":[...]}`, followed by `vitals`, `alert`, and `ack`.
- `/api/alerts/active`: current unacknowledged alerts.
- `POST /api/alerts/{alert_id}/ack`: acknowledge an alert.
- `/health`: current source status. `/api/integrations`: phone and video endpoints.

Example event that starts the phone alarm:

```json
{"type":"alert","alert_id":42,"seat_id":"CHAIR_01","severity":"critical","pattern":"breathing_pause","rr":null,"max_gap_s":13.0,"source":"serial"}
```

Phone alarms consume `/ws/dashboard`; the legacy simulated `alert` field on `/ws`
is only a waveform demo marker. Video remains a placeholder in `/api/integrations`.
No heart-rate input participates in classification.

For Akshat's external-vitals simulator, run the standalone alert app **instead of**
the live server:

```bash
uv run uvicorn backend.alert_app:app --host 0.0.0.0 --port 8000
uv run python -m backend.scripts.simulate
```

Its `/api/vitals` endpoint accepts the existing breathing payload. Severity is
computed from the values; a supplied severity string cannot force an alert. Low
confidence interrupts pending confirmation. The live server rejects external
vitals with HTTP 409 to prevent simulated and serial readings mixing in one seat.
Live CSI does not supply a calibrated confidence probability.

Checks: `uv run pytest` covers the synthetic pause detector, adapter, timed rules,
WebSocket delivery, duplicate suppression, acknowledgement and recovery. Run
`node tests/phone_alarm.cjs` for phone script behavior using mocked browser APIs.
Real board placement, false alarms, detection timing and audible phone output
still need an end-to-end hardware trial.
