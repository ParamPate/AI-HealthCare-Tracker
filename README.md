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
gitignored: raw CSI stays on the machine that recorded it. The one exception is the
shared breath-hold test, `recordings/20261017-013311_hold.parquet` (two marked holds,
60.3 to 80.3 s and 110.0 to 130.4 s; marks in the `.txt`), for tuning the
classification rules: `uv run python -m backend.main --source replay --file
recordings/20261017-013311_hold.parquet`.

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

## Live web page (waiting-room chair)

Two terminals. First the backend, which reads the RX board, analyses once a second
(the same `LiveAnalyser` as the terminal monitor), and serves `ws://localhost:8000/ws`:

```bash
uv run python -m backend.main --source serial
# or loop a saved recording (no boards needed; also a demo backup):
uv run python -m backend.main --source replay --file recordings/<file>.parquet
# or simulated data:
uv run python -m backend.main --source fake
```

Then the page (Next.js; run `npm install` the first time):

```bash
cd frontend
npm run dev
```

Open http://localhost:3000. The page shows the chair, whether the data is live, a
replay, or simulated, the status (starting, measuring, breathing, movement, pause), the
level, the rate or the seconds without a breath, a 30 s breathing wave (about 4 s
behind real time), and signal quality. It turns red during a pause or a critical
level. Only processed numbers and the wave reach the browser; raw CSI stays in the
Python process. Set `NEXT_PUBLIC_WS_URL` to point the page at another server.

The level (normal, warning, critical) comes from `classify()` in
`backend/services/alerts.py`, the same rules that ring the phone (see "Live server
and phone alarm" below). The page hides it while the class is unknown (starting,
measuring, movement, no signal). The phone page is served by the same backend at
`/phone`.

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
   `recordings/` is gitignored (except the shared breath-hold test), so pushing code
   does not transfer captures.

## Label recordings for a classification model

The first training step is collecting observed examples. Labels come from a human
observer, breath count, or independent reference, rather than the CSI prediction.
The filename's `--label` is only a session name; it does not label the whole file.
The shared `20261017-013311_hold` recording is now fully labeled for the first
binary task, `breathing` versus `breath_hold`. The participant confirmed continuous
breathing outside the two marked holds. There are 137.115 seconds of breathing
and 40.4 seconds of breath holds:

| Start (s) | End (s) | Label |
|---|---|---|
| 0 | 60.3 | breathing |
| 60.3 | 80.3 | breath_hold |
| 80.3 | 110.0 | breathing |
| 110.0 | 130.4 | breath_hold |
| 130.4 | 177.515118 | breathing |

The sidecar assigns anonymous participant P01, session S01, and split `train`;
retain P01 for this participant's later recordings. A `breathing` activity label
needs no measured rate. The more specific normal/slow/fast rate labels still need
an independent rate measurement. The intervals above are observer/participant
labels, not predictions from a trained model. Use windows wholly within each
interval and leave a margin around the marked transitions when training.

Separate validation/test recordings are still needed to assess a trained model.
This recording was already used for detector tuning and must not be treated as
held-out evaluation data.

Use anonymous participant IDs (`P01`, `P02`) and session IDs (`S01`, `S02`). Keep
one participant entirely in one split, including all their sessions and paired
empty-chair trials. For example, collect P01's sessions for `train`, P02's for
`validation`, and P03's for a final `test`. This is an initial collection plan,
not enough evidence on its own to establish model accuracy. Add more participants
and sessions with different chair positions and room conditions.

### 1. Collect and mark what actually happened

On the computer connected to RX, close other serial readers and run:

```bash
uv run python -m backend.live --label P01_S01
```

This records CSI while showing the existing detector. Press **Enter** at observed
activity transitions, then **Ctrl+C** to save the recording and its `.txt` log.
The log lists marked times relative to the first device packet. Separately note
which activity began at each mark, the independent breath count and count duration,
and the board placement. Keep patient names and medical details out of these notes.

Start with seated normal breathing, natural movement, and an empty chair. Add
other breathing examples only when their actual timing/rate can be observed. Leave
transition periods and ambiguous data unlabeled, or explicitly mark `uncertain`.
Do not use the detector's displayed status/rate as a training label. Record a new
file after an RX restart or transmitter change.

If a teammate records on another computer, transfer the `.parquet` and observation
notes to the same `recordings/` folder. Git pull does not transfer recordings.

### 2. Inspect and add observed intervals

Replace the example path with the actual saved filename:

```bash
uv run python -m backend.label show recordings/SESSION.parquet
```

The output gives the available time range. Times are seconds from the first
recorded device packet. Labels are half-open intervals: `[start, end)`. Add one
interval at a time, using the observer's timing and allowing a margin around changes.
For example, **if** the observer counted 8 breaths from second 5 to second 35,
that is `8 * 60 / 30 = 16` breaths/min:

```bash
uv run python -m backend.label add recordings/SESSION.parquet \
  --participant P01 --session S01 --split train \
  --start 5 --end 35 --label normal_breathing --reference-rr 16 \
  --note "Observer counted 8 breaths in these 30 seconds; seated, boards 1 m apart"
```

The first interval requires participant, session, and split. Later intervals reuse
them. For an observed movement period in that same recording:

```bash
uv run python -m backend.label add recordings/SESSION.parquet \
  --start 45 --end 55 --label movement --note "Observed arm and torso movement"
```

Only use example time ranges when they match what actually happened in your file.
For the initial two-class task, label an observed breathing range without a rate:

```bash
uv run python -m backend.label add recordings/SESSION.parquet \
  --start 5 --end 35 --label breathing --note "Participant confirmed continuous breathing"
```

`--reference-rr` is optional for `breathing`, and required for normal/slow/fast
breathing labels. It must be an independent measurement, not the model's estimate.

| Label | Required observation |
|---|---|
| breathing | observed continuous breathing; no rate measurement required |
| normal_breathing | measured rate 10–22/min; supply `--reference-rr` |
| slow_breathing | measured rate greater than 0 and below 10/min; supply `--reference-rr` |
| fast_breathing | measured rate above 22/min; supply `--reference-rr` |
| breath_hold | observed voluntary pause with known start/end; this is not a clinical apnea diagnosis |
| movement | observed body movement |
| empty_chair | nobody in the monitored chair; use the paired session's participant ID |
| uncertain | ambiguous timing, transitions, or missing input; exclude from model training |

These rate boundaries match the current prototype rules. The tool saves
`SESSION.labels.json` beside `SESSION.parquet`, including the source file's SHA-256,
participant/session/split, time basis, and interval annotations. It leaves raw CSI
unchanged. Raw captures are gitignored except for the shared breath-hold test;
`recordings/*.labels.json` sidecars can be committed. Transfer each sidecar together
with its matching recording when sharing the dataset with your teammate.

### 3. Check before training

```bash
uv run python -m backend.label check recordings
```

This checks hashes, timestamps, intervals, packet coverage, duplicate recordings,
and participant IDs across splits. It reports labeled seconds by split/class and
which splits are still missing. Missing classes/participants must still be reviewed
before fitting a model; a successful integrity check is not an accuracy result.

Overlapping/out-of-range labels are rejected. A range crossing a packet gap over
2 s cannot be labeled as breathing or a breath hold; mark it `uncertain`. For a
mistake in an existing label, edit its `.labels.json` sidecar and run `check` again.

Training must use windows wholly inside one observed interval,
exclude unlabeled/uncertain time, and keep the assigned participant split. Tune on
`validation`; reserve `test` for final evaluation. Fit normalization/PCA on training
data only. Do not generate training examples from predicted CSI labels or treat
the fake source as measured validation data. Missing input remains a signal-quality
gate; it is not a breath-hold label.

## Trained binary prototype

`backend/classifier.py` trains a breathing-versus-breath-hold logistic regression
using NumPy/SciPy. It operates on raw CSI packets in trailing 10 s windows, once
per second. Training windows stay one second inside a single observed label.
Each window independently uses the shared I/Q conversion, invalid-word handling,
gain normalization, spike removal, and 20 Hz resampling. Five spectral/variance
features are standardized using training data only. No full-recording filtering
or PCA is fitted before extracting windows.

```bash
uv run python -m backend.classifier train --data recordings --output models/breathing-v1.json
uv run python -m backend.classifier predict --model models/breathing-v1.json --file recordings/20261017-013311_hold.parquet
uv run python -m backend.classifier validate --data recordings --model models/breathing-v1.json --output models/validation-v1.json
```

`train` saves the JSON model and `breathing-v1.training.json`. The bundle includes
preprocessing settings, feature order, learned means/scales, coefficients, class
mapping, threshold 0.5, source hashes, dependency versions and dataset provenance.
The source revision is recorded at training time; preprocessing hashes must match
the code used to load the bundle. Do not edit the pipeline without regenerating
the artifact. Loading JSON does not execute serialized Python objects.

`predict` prints chronological JSONL with `end_s`, `label`, `hold_score`, and
`reason`. `hold_score` is an uncalibrated model score, not a signal-confidence or
clinical-risk probability. Incomplete windows, invalid CSI, clock changes, packet
gaps over 2 s and incompatible radio settings return `no_signal` with a null score.
Old recordings lack bandwidth/secondary-channel columns; their unknown values
are preserved in provenance rather than inferred.

`validate` uses only `validation` sidecars. It rejects training participants and
copied training recordings, even when the training files are absent from the new
computer. It reports window confusion counts, hold precision/recall, false holds
during breathing, missed hold episodes, detection delay, and separate movement/
empty-chair challenge results. For episode metrics a run begins at its first
positive window; invalid or missing updates break the run. Episode starts match
each observed hold at most once; unmatched starts in known activity are false
detections. These are model-level results before alarm confirmation/debouncing.
Missing validation data produces a `pending` report with no accuracy metrics.

The saved prototype is trained on the single P01/S01 recording; training fit is
reported as `training_fit_only`. Its overlapping windows are not independent
validation. Motion, empty-chair discrimination and generalization to new people
remain unmeasured. The model is not connected to the live server or alarm yet;
the existing server still uses its DSP/rules pipeline.

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
