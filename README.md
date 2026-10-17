# AI-HealthCare-Tracker
Hack the Valley

## Read the ESP32 receiver

Use Python 3.11 or newer. Close other serial monitors before running the reader.
From the project root, set up a local environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r signal-processing/requirements.txt
python -m serial.tools.list_ports
python signal-processing/serial_reader.py --port /dev/cu.usbserial-0001
```

On Windows, create the environment with `python -m venv .venv`, activate it with
`.venv\Scripts\Activate.ps1` in PowerShell, and use the listed port such as `COM3`.
If using the project's existing uv environment, `uv sync` supplies pyserial too;
run the reader with `uv run python signal-processing/serial_reader.py --port ...`.

Replace the port with the receiver's port on your laptop. The default baud rate
is 921600; override it with `--baud`. Press Ctrl-C to close the connection.

The reader prints only validated `CSI_DATA` lines from the classic ESP32's
25-column format. Startup logs are ignored; malformed packets are skipped.
Each rejection reason is warned about once, with totals shown on exit.
The 15-column C5/C6 layout is reported as unsupported in this version.
A missing or disconnected device produces an error; reconnect and restart.

Every five seconds, stderr shows the accepted packet rate over that interval,
total accepted/rejected packets, rejection reasons, missing IDs, sequence
discontinuities, and time since the last valid sample. Reports continue while
the serial stream is silent. Missing IDs are an estimate from forward sequence
gaps, not proof of where data was lost; reordered packets and resets can affect it.
Sequence tracking is separate per transmitter and resets on timing segment changes.

## Save a raw recording

```bash
python3 signal-processing/serial_reader.py --port /dev/cu.usbserial-0001 \
  --record recordings/breathing.jsonl
```

Parent folders are created automatically, but an existing file is never
overwritten. Each JSONL row contains `received_at` (Unix seconds),
`received_monotonic` (host monotonic seconds), and `raw_line`. This includes
startup logs and malformed packets, so parsing problems can be investigated later.
Oversized lines and incomplete final fragments are discarded, not recorded.

To recover the original bytes, use `row["raw_line"].encode("latin-1")` after
`json.loads`; this also preserves malformed non-ASCII bytes. Accepted packets
can then be parsed again with `parse_line`. Files flush about once a second and
close on exit. A recording error stops capture with an error message. Flushing
does not guarantee recovery after power loss; use Ctrl-C to finish a capture.

## Signal processing handoff

Python callers use `read_samples(connection)` from `serial_reader.py`, passing
an already-open pyserial connection with a one-second timeout. The caller owns
closing the connection. Optional `recording=` accepts an open text file that
the caller must close; `diagnostics=True` enables the five-second reports.
Each iteration yields a `CSISample` with:

- `packet_id` (unsigned), `mac`, `rssi`, `channel`, and parsed `metadata`.
- `received_at` (Unix seconds) and `received_monotonic` (host monotonic seconds).
- `device_timestamp_raw` (as printed), `device_time_us` (unwrapped microseconds),
  and `time_segment` (starting at zero, tracked separately per transmitter).
- `raw_iq`, `csi` (complex values), `valid_mask`, and the original `raw_line` bytes.

CSI pairs are imaginary first, real second. When `first_word` is set, the first
two complex values have a false validity mask; their values and positions remain
intact. The pipeline must exclude masked entries and restart its processing
window when the transmitter, timing segment, CSI shape, or radio configuration changes.

Signed device timestamps are reinterpreted as unsigned. Backward jumps greater
than half the 32-bit range are treated as rollover; smaller backward jumps
start a new timing segment. Reboots and long outages can be ambiguous without a
firmware boot identifier. Host arrival times include serial buffering delays.

This generator blocks while reading USB. Run acquisition in a background thread
when integrating with an async server. Each new iterator starts a fresh capture;
do not combine its timing state with a previous session. Breathing estimation
is not implemented here.

Run the transport, parser, recording, and sample checks without hardware:

```bash
python3 -m unittest discover -s signal-processing -p 'test_*.py'
```

On macOS/Linux with pyserial installed, this also exercises the actual CLI and
serial driver through a virtual port, including recording and disconnection.
The virtual port uses 115200 baud; it does not verify the physical USB adapter
at 921600 baud. Other environments skip that one integration test. With the full
project environment, `uv run pytest` collects both the backend and reader suites.

## Teammate hardware check

1. Pull the latest `main`, activate the environment above, and keep both ESP32s powered.
2. Find the receiver's port. Close `idf.py monitor`, the live viewer, and any other
   serial reader before starting this one.
3. Run with `--record recordings/empty-chair.jsonl`. Confirm accepted packets and
   a measured rate appear, then press Ctrl-C after about 60 seconds.
4. Repeat with new filenames for 60–120 seconds of still, normal breathing and
   20–30 seconds of deliberate movement. Note board placement and trial activity.
5. During a separate connection check, unplug the receiver and confirm a clear
   error and program exit. Reconnect and restart with a new filename.
6. Send the recordings and diagnostic output back for analysis. `recordings/`
   is gitignored, so pulling/pushing code does not transfer captures.

The teammate's `backend.record` command saves Parquet for
`signal-processing/explore.py`. This reader saves raw JSONL; that plotting script
does not accept JSONL directly. Run one capture program at a time, and choose the
Parquet recorder when using the existing exploration plots.

Automated checks establish parsing and transport behavior. Physical receiver
throughput, placement, and reliable breathing detection still need hardware trials.
