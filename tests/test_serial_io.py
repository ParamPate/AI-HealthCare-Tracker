import io
import json
from unittest.mock import patch

import pyarrow.parquet as pq

from backend.csi_format import MAX_LINE_BYTES, parse_line
from backend.record import SCHEMA, to_table
from backend.serial_io import CaptureStats, CsiStream, LineBuffer
from csi_lines import FakeSerial, packet_line


def read_all(stream, calls):
    return [s for _ in range(calls) for s in stream.read()]


def test_line_buffer_joins_fragments_and_keeps_cr():
    lines = LineBuffer()
    out = [line for chunk in (b"CSI_", b"", b"DATA,1\r", b"\nCSI_DATA,2\n") for line in lines.feed(chunk)]
    assert out == [b"CSI_DATA,1\r\n", b"CSI_DATA,2\n"]


def test_oversized_line_is_dropped_until_newline():
    lines = LineBuffer()
    assert lines.feed(b"x" * (MAX_LINE_BYTES + 1)) == []
    assert lines.feed(b"tail\nvalid\n") == [b"valid\n"]
    assert lines.oversized == 1


def test_line_at_limit_is_kept():
    line = b"x" * (MAX_LINE_BYTES - 1) + b"\n"
    assert LineBuffer().feed(line) == [line]


def test_stream_skips_logs_counts_rejections_and_keeps_going():
    valid = packet_line()
    stream = CsiStream(FakeSerial([b"boot\nCSI_DATA,bad\nCSI_DATA,bad\n" + valid]))
    with patch("backend.serial_io.time.time", return_value=1729125600.12):
        (sample,) = stream.read()
    assert sample.host_time == 1729125600.12
    assert (sample.packet.seq, sample.device_time_us, sample.segment) == (59894, 3564276, 0)
    assert stream.stats.accepted == 1
    assert stream.stats.rejected == {"missing quoted CSI array": 2}


def test_stream_reassembles_real_lines_split_into_odd_chunks():
    from pathlib import Path
    data = (Path(__file__).resolve().parent.parent / "docs" / "sample_csi_lines.txt").read_bytes()
    stream = CsiStream(FakeSerial([data[i:i + 100] for i in range(0, len(data), 100)]))
    assert [s.packet.seq for s in read_all(stream, len(data) // 100 + 1)] == [4963, 4964, 4966]
    assert stream.stats.missing_ids == 1  # 4965 was dropped on the board
    assert not stream.stats.rejected


def test_stream_handles_mixed_csi_sizes():
    stream = CsiStream(FakeSerial([packet_line([1, 2] * (n // 2)) for n in (128, 384)]))
    assert [len(s.packet.csi) for s in read_all(stream, 2)] == [128, 384]


def test_transmitters_have_independent_clocks():
    first, second = "1a:00:00:00:00:00", "1a:00:00:00:00:01"
    frames = [(first, -1), (second, 50), (first, 0), (second, 100)]
    stream = CsiStream(FakeSerial([packet_line(overrides={1: "-1", 2: mac, 18: str(t)}) for mac, t in frames]))
    samples = read_all(stream, len(frames))
    assert [s.device_time_us for s in samples] == [4294967295, 50, 4294967296, 100]
    assert [s.segment for s in samples] == [0] * 4
    assert samples[0].packet.seq == 4294967295


def test_board_restart_starts_new_segment():
    stream = CsiStream(FakeSerial([packet_line(overrides={18: str(t)}) for t in (-1, 10000, 100, 200)]))
    samples = read_all(stream, 4)
    assert [(s.device_time_us, s.segment) for s in samples] == [
        (4294967295, 0), (4294977296, 0), (100, 1), (200, 1)]


def test_oversized_lines_are_counted_as_rejections():
    stream = CsiStream(FakeSerial([b"x" * (MAX_LINE_BYTES + 1), b"\n", packet_line()]))
    assert len(read_all(stream, 3)) == 1
    assert stream.stats.rejected["oversized serial line"] == 1


def test_raw_log_preserves_logs_damaged_bytes_and_packets():
    lines = [b"boot\xff\n", b"CSI_DATA,bad\n", packet_line()]
    raw_log = io.StringIO()
    (sample,) = CsiStream(FakeSerial([b"".join(lines)]), raw_log).read()
    rows = [json.loads(r) for r in raw_log.getvalue().splitlines()]
    assert [r["raw_line"].encode("latin-1") for r in rows] == lines
    assert rows[-1]["received_at"] == sample.host_time
    assert parse_line(rows[-1]["raw_line"].encode("latin-1")).csi.tolist() == sample.packet.csi.tolist()


def test_missing_ids_rollover_duplicates_and_discontinuities():
    stats = CaptureStats()
    for seq in (4294967294, 4294967295, 0, 3, 3, 0, 1):
        stats.accept("tx", seq, segment=0)
    assert (stats.missing_ids, stats.discontinuities) == (2, 1)
    stats.accept("tx", 500, segment=1)  # new segment: no gap counted across a restart
    assert stats.missing_ids == 2


def test_sequence_gaps_are_per_transmitter():
    stats = CaptureStats()
    for mac, seq in (("a", 100), ("b", 500), ("a", 102), ("b", 501)):
        stats.accept(mac, seq, segment=0)
    assert stats.missing_ids == 1


def test_summary_before_and_after_packets():
    stats = CaptureStats()
    assert "last_valid=never" in stats.summary()
    stats.accept("tx", 1, 0)
    stats.accept("tx", 4, 0)
    assert "missing_ids=2 (50.0%)" in stats.summary()


def test_recorded_table_round_trips(tmp_path):
    samples = read_all(CsiStream(FakeSerial([packet_line(), packet_line(overrides={1: "59896"})])), 2)
    path = tmp_path / "r.parquet"
    pq.write_table(to_table(samples), path)
    table = pq.read_table(path)
    assert table.schema.equals(SCHEMA)
    assert table["seq"].to_pylist() == [59894, 59896]
    assert table["csi"].to_pylist()[0] == samples[0].packet.csi.tolist()
