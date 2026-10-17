from pathlib import Path

import numpy as np
import pytest

from backend.csi_format import DeviceClock, amplitudes, parse_line
from csi_lines import packet_line

SAMPLES = (Path(__file__).resolve().parent.parent / "docs" / "sample_csi_lines.txt").read_bytes().splitlines()


def test_parses_real_captured_lines():
    packets = [parse_line(raw) for raw in SAMPLES]
    assert [p.seq for p in packets] == [4963, 4964, 4966]
    assert all(len(p.csi) == 384 and p.csi.dtype == np.int8 for p in packets)
    assert packets[0].csi[:4].tolist() == [47, -16, 2, 0]


def test_reads_metadata_columns():
    p = parse_line(SAMPLES[0])
    assert (p.mac, p.rssi, p.noise_floor, p.timestamp_us) == ("1a:00:00:00:00:00", -68, -97, 35118912)
    assert (p.bandwidth, p.channel, p.secondary_channel, p.first_word_invalid) == (1, 11, 2, True)


@pytest.mark.parametrize("length", [128, 384])
def test_valid_sizes_and_value_extremes(length):
    data = [-128, 127] * (length // 2)
    p = parse_line(packet_line(data))
    assert p.csi.tolist() == data
    assert (p.seq, p.rssi, p.channel, p.timestamp_us) == (59894, -65, 11, 3564276)


@pytest.mark.parametrize("raw", [b"", b"I (100) wifi: startup\n", b"type,id,mac,rssi\n"])
def test_logs_and_headers_are_ignored(raw):
    assert parse_line(raw) is None


@pytest.mark.parametrize("printed", [-2**31, -1, 0, 2**32 - 1])
def test_signed_and_unsigned_counters_read_as_uint32(printed):
    p = parse_line(packet_line(overrides={1: str(printed), 18: str(printed)}))
    assert p.timestamp_us == p.seq == printed % 2**32


@pytest.mark.parametrize("raw", [
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
    b"CSI_DATA," + b"1," * 9000 + b'"[1,2]"\n',
])
def test_damaged_lines_raise(raw):
    with pytest.raises(ValueError):
        parse_line(raw)


def test_c5_c6_layout_has_clear_error():
    line = b'CSI_DATA,1,1a:00:00:00:00:00,-65,11,-97,0,0,11,100,47,1,2,0,"[1,2]"\n'
    with pytest.raises(ValueError, match="unsupported 15-column"):
        parse_line(line)


def test_clock_counts_through_signed_boundary_and_wraparound():
    clock = DeviceClock()
    printed = [2147483647, -2147483648, -1, 0, 10000]
    assert [clock(t % 2**32) for t in printed] == [
        (2147483647, 0), (2147483648, 0), (4294967295, 0), (4294967296, 0), (4294977296, 0)]


def test_clock_backward_jump_starts_new_segment():
    clock = DeviceClock()
    assert [clock(t % 2**32) for t in [-1, 10000, 100, 200]] == [
        (4294967295, 0), (4294977296, 0), (100, 1), (200, 1)]


def test_amplitudes_use_imaginary_then_real_and_zero_first_word():
    csi = np.array([[9, 9, 9, 9, 3, 4, 0, -2]], dtype=np.int8)
    assert amplitudes(csi).tolist() == [[0, 0, 5, 2]]
    assert amplitudes(csi, first_word_invalid=False)[0, 2:].tolist() == [5, 2]
