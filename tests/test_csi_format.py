from pathlib import Path

import numpy as np
import pytest

from backend.csi_format import TimestampUnwrapper, amplitudes, parse_line
from backend.serial_io import LineBuffer

SAMPLES = (Path(__file__).resolve().parent.parent / "docs" / "sample_csi_lines.txt").read_bytes().splitlines()


@pytest.mark.parametrize("raw", SAMPLES)
def test_parses_real_lines(raw):
    packet = parse_line(raw)
    assert packet is not None
    assert packet.csi.dtype == np.int8
    assert len(packet.csi) == 384
    assert packet.channel == 11
    assert packet.first_word_invalid


def test_reads_metadata_columns():
    packet = parse_line(SAMPLES[0])
    assert (packet.seq, packet.rssi, packet.noise_floor, packet.timestamp_us) == (4963, -68, -97, 35118912)
    assert packet.csi[:4].tolist() == [47, -16, 2, 0]


@pytest.mark.parametrize("raw", [
    b"I (312) csi_recv: ================ CSI RECV ================",
    b"",
    SAMPLES[0][:200],                                # cut off mid-array
    SAMPLES[0].replace(b",384,", b",386,", 1),        # len disagrees with data
    SAMPLES[0].replace(b'"[47,', b'"[470,', 1),       # value outside int8
])
def test_rejects_non_csi_and_broken_lines(raw):
    assert parse_line(raw) is None


def test_negative_timestamp_is_read_as_uint32():
    raw = SAMPLES[0].replace(b",35118912,", b",-2147483648,", 1)
    assert parse_line(raw).timestamp_us == 2**31


def test_unwrapper_counts_through_wraparound():
    unwrap = TimestampUnwrapper()
    assert [unwrap(t) for t in [2**32 - 20, 2**32 - 10, 5, 15]] == [2**32 - 20, 2**32 - 10, 2**32 + 5, 2**32 + 15]


def test_amplitudes_use_imaginary_then_real_and_zero_first_word():
    csi = np.array([[9, 9, 9, 9, 3, 4, 0, -2]], dtype=np.int8)
    assert amplitudes(csi).tolist() == [[0, 0, 5, 2]]
    assert amplitudes(csi, first_word_invalid=False)[0, 2:].tolist() == [5, 2]


def test_line_buffer_joins_chunks():
    lines = LineBuffer()
    assert lines.feed(b"CSI_DATA,1") == []
    assert lines.feed(b"23\nCSI_DA") == [b"CSI_DATA,123"]
    assert lines.feed(b"TA,4\n") == [b"CSI_DATA,4"]
