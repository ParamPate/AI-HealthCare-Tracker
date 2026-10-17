import csv
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from serial_reader import MAX_LINE_BYTES, main, parse_line, read_lines, read_samples


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


if __name__ == "__main__":
    unittest.main()
