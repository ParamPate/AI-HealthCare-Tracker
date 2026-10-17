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

The reader currently prints complete raw serial lines. CSI parsing, sample
conversion, and recording will be added in the following implementation steps.
A missing or disconnected device produces an error; reconnect and restart.

Run the transport checks without hardware:

```bash
python3 -m unittest discover -s signal-processing -p 'test_*.py'
```
