# AI-HealthCare-Tracker
Hack the Valley

## Read the ESP32 receiver

Close other serial monitors before running the reader. From the project root:

```bash
python3 -m pip install -r signal-processing/requirements.txt
python3 signal-processing/serial_reader.py --port /dev/cu.usbserial-0001
```

Replace the port with the receiver's port on your laptop. The default baud rate
is 921600; override it with `--baud`. Press Ctrl-C to close the connection.

The reader prints only validated `CSI_DATA` lines from the classic ESP32's
25-column format. Startup logs are ignored; malformed packets are skipped.
Each rejection reason is warned about once, with totals shown on exit.
The 15-column C5/C6 layout is reported as unsupported in this version.
Raw recording and periodic diagnostics will be added in the following step.
A missing or disconnected device produces an error; reconnect and restart.

## Signal processing handoff

Python callers use `read_samples(connection)` from `serial_reader.py`, passing
an already-open pyserial connection with a one-second timeout. The caller owns
closing the connection. Each iteration yields a `CSISample` with:

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

Run the transport, parser, and sample checks without hardware:

```bash
python3 -m unittest discover -s signal-processing -p 'test_*.py'
```
