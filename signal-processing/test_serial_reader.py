import csv
from collections import Counter
from dataclasses import replace
import io
import importlib.util
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from serial_reader import CaptureStats, MAX_LINE_BYTES, main, parse_line, read_lines, read_samples


def packet_line(data=None, overrides=None):
    if data is None:
        data = [-16, 47] * 64
    fields = (
        "CSI_DATA,59894,1a:00:00:00:00:00,-65,11,1,0,1,1,1,0,0,0,0,"
        "-97,0,11,2,3564276,0,47,1"
    ).split(",") + [str(len(data)), "1", json.dumps(data)]
    for index, value in (overrides or {}).items():
        fields[index] = value
    output = io.StringIO()
    csv.writer(output).writerow(fields)
    return output.getvalue().encode("ascii")


class ParseLineTests(unittest.TestCase):
    def test_teammates_captured_packets(self):
        path = Path(__file__).resolve().parent.parent / "docs" / "sample_csi_lines.txt"
        packets = [parse_line(line) for line in path.read_bytes().splitlines()]
        self.assertEqual([p["id"] for p in packets], [4963, 4964, 4966])
        self.assertTrue(all(len(p["data"]) == 384 for p in packets))
        self.assertEqual(packets[0]["data"][:4], [47, -16, 2, 0])

    def test_valid_packet_sizes_and_metadata(self):
        for length in (128, 384):
            with self.subTest(length=length):
                data = [-128, 127] * (length // 2)
                packet = parse_line(packet_line(data))
                self.assertEqual(packet["data"], data)
                self.assertEqual(packet["len"], length)
                self.assertEqual(packet["id"], 59894)
                self.assertEqual(packet["channel"], 11)
                self.assertEqual(packet["local_timestamp"], 3564276)
                self.assertEqual(packet["first_word"], 1)
                self.assertEqual(packet["rssi"], -65)

    def test_logs_and_headers_are_ignored(self):
        for line in (b"", b"I (100) wifi: startup\n", b"type,id,mac,rssi\n"):
            self.assertIsNone(parse_line(line))

    def test_signed_and_unsigned_counter_values_are_preserved(self):
        for timestamp in (-2147483648, -1, 0, 4294967295):
            packet = parse_line(packet_line(overrides={18: str(timestamp)}))
            self.assertEqual(packet["local_timestamp"], timestamp)

    def test_invalid_packets_are_rejected(self):
        invalid = [
            packet_line(overrides={2: "bad-mac"}),
            packet_line(overrides={3: "unknown"}),
            packet_line(overrides={3: "-129"}),
            packet_line(overrides={16: "0"}),
            packet_line(overrides={18: str(2**32)}),
            packet_line(overrides={22: "126"}),
            packet_line(overrides={23: "2"}),
            packet_line(overrides={24: "[1,"}),
            packet_line(overrides={24: "{}"}),
            packet_line([]),
            packet_line([1, 2, 3]),
            packet_line([True, 1]),
            packet_line([1.0, 1]),
            packet_line([128, 0]),
            packet_line([-129, 0]),
            packet_line(["1", 2]),
            b"CSI_DATA,1\n",
            packet_line()[:-10] + b"\n",
            b"CSI_DATA,\xff\n",
        ]
        for line in invalid:
            with self.subTest(line=line[:100]):
                with self.assertRaises(ValueError):
                    parse_line(line)

    def test_short_layout_has_clear_error(self):
        line = b'CSI_DATA,1,1a:00:00:00:00:00,-65,11,-97,0,0,11,100,47,1,2,0,"[1,2]"\n'
        with self.assertRaisesRegex(ValueError, "unsupported 15-column"):
            parse_line(line)

    def test_cli_skips_bad_packets_and_continues(self):
        valid = packet_line()
        connection = unittest.mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.in_waiting = 4096
        connection.read.side_effect = [b"boot\nCSI_DATA,bad\nCSI_DATA,bad\n" + valid, KeyboardInterrupt()]
        serial_module = SimpleNamespace(Serial=lambda *args, **kwargs: connection, SerialException=OSError)
        output = io.BytesIO()
        errors = io.StringIO()
        with patch.dict("sys.modules", {"serial": serial_module}), \
                patch("sys.stdout", SimpleNamespace(buffer=output)), \
                patch("sys.stderr", errors), \
                self.assertLogs("serial_reader", level="WARNING") as logs:
            self.assertEqual(main(["--port", "fake"]), 0)
        self.assertEqual(output.getvalue(), valid)
        self.assertEqual(len(logs.output), 1)
        self.assertIn("'expected 25 CSV columns': 2", errors.getvalue())
        connection.__exit__.assert_called_once()


class FakeSerial:
    in_waiting = 4096

    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read(self, size):
        return next(self.chunks)


class ReadSamplesTests(unittest.TestCase):
    def test_iq_order_mask_and_arrival_clocks(self):
        data = [-16, 47, 2, -3, 4, 5]
        line = packet_line(data)
        with patch("serial_reader.time.time", return_value=1729125600.12), \
                patch("serial_reader.time.monotonic", return_value=123.5):
            sample = next(read_samples(FakeSerial([line])))
        self.assertEqual(sample.csi, (47 - 16j, -3 + 2j, 5 + 4j))
        self.assertEqual(sample.valid_mask, (False, False, True))
        self.assertEqual(sample.raw_iq, tuple(data))
        self.assertEqual(sample.raw_line, line)
        self.assertEqual(sample.received_at, 1729125600.12)
        self.assertEqual(sample.received_monotonic, 123.5)
        self.assertEqual(sample.metadata["bandwidth"], 1)
        self.assertEqual(sample.metadata["len"], 6)
        self.assertNotIn("data", sample.metadata)

    def test_variable_sizes_and_all_valid_flag(self):
        lines = [packet_line([1, 2] * (size // 2), {23: "0"}) for size in (128, 384)]
        reader = read_samples(FakeSerial(lines))
        for size in (128, 384):
            sample = next(reader)
            self.assertEqual(len(sample.csi), size // 2)
            self.assertEqual(sample.valid_mask, (True,) * (size // 2))

    def test_signed_boundary_and_full_rollover(self):
        raw_times = [2147483647, -2147483648, -1, 0, 10000]
        reader = read_samples(FakeSerial([packet_line(overrides={18: str(t)}) for t in raw_times]))
        samples = [next(reader) for _ in raw_times]
        self.assertEqual([s.device_timestamp_raw for s in samples], raw_times)
        self.assertEqual([s.device_time_us for s in samples],
                         [2147483647, 2147483648, 4294967295, 4294967296, 4294977296])
        self.assertEqual([s.time_segment for s in samples], [0] * 5)

    def test_backward_jump_starts_new_segment_and_resets_offset(self):
        raw_times = [-1, 10000, 100, 200]
        reader = read_samples(FakeSerial([packet_line(overrides={18: str(t)}) for t in raw_times]))
        samples = [next(reader) for _ in raw_times]
        self.assertEqual([s.device_time_us for s in samples], [4294967295, 4294977296, 100, 200])
        self.assertEqual([s.time_segment for s in samples], [0, 0, 1, 1])

    def test_transmitters_have_independent_clocks(self):
        first_mac, second_mac = "1a:00:00:00:00:00", "1a:00:00:00:00:01"
        frames = [(first_mac, -1), (second_mac, 50), (first_mac, 0), (second_mac, 100)]
        reader = read_samples(FakeSerial([
            packet_line(overrides={2: mac, 18: str(timestamp), 1: "-1"})
            for mac, timestamp in frames
        ]))
        samples = [next(reader) for _ in frames]
        self.assertEqual([s.device_time_us for s in samples], [4294967295, 50, 4294967296, 100])
        self.assertEqual([s.time_segment for s in samples], [0] * 4)
        self.assertEqual(samples[0].packet_id, 4294967295)
        self.assertEqual(samples[0].metadata["id"], -1)


class RecordingAndStatsTests(unittest.TestCase):
    def test_recording_preserves_logs_malformed_bytes_and_valid_packets(self):
        lines = [b"boot\xff\n", b"CSI_DATA,bad\n", packet_line()]
        recording = io.StringIO()
        with self.assertLogs("serial_reader", level="WARNING"):
            sample = next(read_samples(FakeSerial(lines), recording=recording))
        records = [json.loads(line) for line in recording.getvalue().splitlines()]
        self.assertEqual([r["raw_line"].encode("latin-1") for r in records], lines)
        self.assertEqual(records[-1]["received_at"], sample.received_at)
        self.assertEqual(records[-1]["received_monotonic"], sample.received_monotonic)
        self.assertEqual(parse_line(records[-1]["raw_line"].encode("latin-1"))["data"], list(sample.raw_iq))

    def test_missing_ids_rollover_duplicates_and_discontinuities(self):
        base = next(read_samples(FakeSerial([packet_line()])))
        stats = CaptureStats(Counter())
        for seq in (4294967294, 4294967295, 0, 3, 3, 0, 1):
            stats.accept(replace(base, packet_id=seq))
        self.assertEqual(stats.missing_ids, 2)
        self.assertEqual(stats.sequence_discontinuities, 1)
        stats.accept(replace(base, packet_id=500, time_segment=1))
        self.assertEqual(stats.missing_ids, 2)

    def test_sequence_counts_are_per_transmitter(self):
        base = next(read_samples(FakeSerial([packet_line()])))
        stats = CaptureStats(Counter())
        for mac, seq in (("a", 100), ("b", 500), ("a", 102), ("b", 501)):
            stats.accept(replace(base, mac=mac, packet_id=seq))
        self.assertEqual(stats.missing_ids, 1)

    def test_diagnostics_and_flush_continue_during_silence(self):
        now = [0.0]
        chunks = iter([b""] * 5 + [packet_line()] + [b""] * 5)
        connection = MagicMock()
        connection.in_waiting = 4096

        def read(size):
            now[0] += 1
            try:
                return next(chunks)
            except StopIteration:
                raise KeyboardInterrupt()

        connection.read.side_effect = read
        recording = MagicMock(wraps=io.StringIO())
        errors = io.StringIO()
        with patch("serial_reader.time.monotonic", side_effect=lambda: now[0]), \
                patch("sys.stderr", errors):
            reader = read_samples(connection, recording=recording, diagnostics=True)
            next(reader)
            with self.assertRaises(KeyboardInterrupt):
                next(reader)
        self.assertIn("0.0 packets/s | accepted=0", errors.getvalue())
        self.assertIn("last_valid=never", errors.getvalue())
        self.assertIn("0.2 packets/s | accepted=1", errors.getvalue())
        self.assertIn("last_valid=4.0s ago", errors.getvalue())
        self.assertGreaterEqual(recording.flush.call_count, 10)

    def test_oversized_lines_are_counted(self):
        rejected = Counter()
        reader = read_samples(FakeSerial([b"x" * (MAX_LINE_BYTES + 1), b"\n", packet_line()]), rejected)
        with self.assertLogs("serial_reader", level="WARNING"):
            next(reader)
        self.assertEqual(rejected["oversized serial line"], 1)

    def test_cli_creates_recording_and_refuses_overwrite(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.in_waiting = 4096
        line = packet_line()
        connection.read.side_effect = [line, KeyboardInterrupt()]
        serial_factory = MagicMock(return_value=connection)
        serial_module = SimpleNamespace(Serial=serial_factory, SerialException=OSError)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "captures" / "sample.jsonl"
            with patch.dict("sys.modules", {"serial": serial_module}), \
                    patch("sys.stdout", SimpleNamespace(buffer=io.BytesIO())), \
                    patch("sys.stderr", io.StringIO()):
                self.assertEqual(main(["--port", "fake", "--record", str(path)]), 0)
                original = path.read_bytes()
                self.assertEqual(json.loads(original)["raw_line"].encode("latin-1"), line)
                self.assertEqual(main(["--port", "fake", "--record", str(path)]), 1)
            self.assertEqual(path.read_bytes(), original)
        serial_factory.assert_called_once()
        connection.__exit__.assert_called_once()

    def test_recording_failure_closes_serial_and_reports_error(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.in_waiting = 4096
        connection.read.return_value = packet_line()
        serial_module = SimpleNamespace(Serial=lambda *a, **kw: connection, SerialException=OSError)
        recording = MagicMock()
        recording.__enter__.return_value = recording
        recording.write.side_effect = OSError("disk full")
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict("sys.modules", {"serial": serial_module}), \
                patch("serial_reader.Path.open", return_value=recording), \
                patch("sys.stderr", errors):
            self.assertEqual(main(["--port", "fake", "--record", str(Path(folder) / "sample.jsonl")]), 1)
        self.assertIn("disk full", errors.getvalue())
        connection.__exit__.assert_called_once()
        recording.__exit__.assert_called_once()


class ReadLinesTests(unittest.TestCase):
    def test_fragments_and_timeouts_preserve_complete_records(self):
        reader = read_lines(FakeSerial([b"CSI_", b"", b"DATA,1\r", b"\nCSI_DATA,2\n"]))
        self.assertEqual(next(reader), b"CSI_DATA,1\r\n")
        self.assertEqual(next(reader), b"CSI_DATA,2\n")

    def test_oversized_line_is_discarded_until_newline(self):
        reader = read_lines(FakeSerial([b"x" * (MAX_LINE_BYTES + 1), b"tail\nvalid\n"]))
        with self.assertLogs("serial_reader", level="WARNING"):
            self.assertEqual(next(reader), b"valid\n")

    def test_line_at_limit_is_preserved(self):
        line = b"x" * (MAX_LINE_BYTES - 1) + b"\n"
        self.assertEqual(next(read_lines(FakeSerial([line]))), line)


class FailureTests(unittest.TestCase):
    def test_port_open_failure_is_reported(self):
        serial_module = SimpleNamespace(Serial=MagicMock(side_effect=OSError("port unavailable")), SerialException=OSError)
        errors = io.StringIO()
        with patch.dict("sys.modules", {"serial": serial_module}), patch("sys.stderr", errors):
            self.assertEqual(main(["--port", "missing"]), 1)
        self.assertIn("port unavailable", errors.getvalue())

    def test_disconnect_closes_connection(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.in_waiting = 1
        connection.read.side_effect = OSError("device disconnected")
        serial_module = SimpleNamespace(Serial=lambda *a, **kw: connection, SerialException=OSError)
        errors = io.StringIO()
        with patch.dict("sys.modules", {"serial": serial_module}), patch("sys.stderr", errors):
            self.assertEqual(main(["--port", "fake"]), 1)
        self.assertIn("device disconnected", errors.getvalue())
        connection.__exit__.assert_called_once()

    def test_missing_dependency_has_install_instruction(self):
        errors = io.StringIO()
        with patch.dict("sys.modules", {"serial": None}), patch("sys.stderr", errors):
            self.assertEqual(main(["--port", "fake"]), 1)
        self.assertIn("pip install", errors.getvalue())

    def test_required_port_and_positive_baud(self):
        for args in ([], ["--port", "fake", "--baud", "0"], ["--port", "fake", "--baud", "-1"]):
            with self.subTest(args=args), patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as error:
                main(args)
            self.assertEqual(error.exception.code, 2)


@unittest.skipUnless(os.name == "posix" and importlib.util.find_spec("serial") is not None,
                     "POSIX and pyserial required for virtual serial-port check")
class VirtualSerialTests(unittest.TestCase):
    def read_until(self, stream, marker):
        data = b""
        deadline = time.monotonic() + 5
        while marker not in data:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, f"Timed out waiting for {marker!r}; received {data!r}")
            readable, _, _ = select.select([stream], [], [], remaining)
            self.assertTrue(readable, f"Timed out waiting for {marker!r}")
            chunk = os.read(stream.fileno(), 65536)
            self.assertTrue(chunk, f"Process closed stream before {marker!r}: {data!r}")
            data += chunk
        return data

    def test_real_serial_driver_recording_and_shutdown(self):
        # A PTY exercises pyserial and the CLI without opening a physical ESP32.
        import pty

        for disconnect in (False, True):
            with self.subTest(disconnect=disconnect), tempfile.TemporaryDirectory() as folder:
                master, slave = pty.openpty()
                process = None
                path = Path(folder) / "capture.jsonl"
                try:
                    process = subprocess.Popen(
                        # macOS PTYs support standard baud rates, not ESP32's 921600.
                        [sys.executable, str(Path(__file__).with_name("serial_reader.py")),
                         "--port", os.ttyname(slave), "--baud", "115200", "--record", str(path)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    self.read_until(process.stderr, b"Recording to")
                    line = packet_line()
                    os.write(master, b"boot\n" + line[:100])
                    os.write(master, line[100:])
                    self.assertEqual(self.read_until(process.stdout, b"\n"), line)
                    if disconnect:
                        os.close(master)
                        master = None
                    else:
                        process.send_signal(signal.SIGINT)
                    _, errors = process.communicate(timeout=5)
                    self.assertEqual(process.returncode, 1 if disconnect else 0, errors.decode())
                    records = [json.loads(row) for row in path.read_text().splitlines()]
                    self.assertEqual([r["raw_line"].encode("latin-1") for r in records], [b"boot\n", line])
                    self.assertIsNotNone(parse_line(records[-1]["raw_line"].encode("latin-1")))
                finally:
                    if process is not None:
                        if process.poll() is None:
                            process.kill()
                        process.communicate(timeout=5)
                    if master is not None:
                        os.close(master)
                    os.close(slave)


if __name__ == "__main__":
    unittest.main()
