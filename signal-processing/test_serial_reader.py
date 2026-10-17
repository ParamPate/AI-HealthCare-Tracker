import unittest

from serial_reader import MAX_LINE_BYTES, read_lines


class FakeSerial:
    in_waiting = 4096

    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read(self, size):
        return next(self.chunks)


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
