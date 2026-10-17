"""Parse CSI_DATA lines printed by Espressif's csi_recv example (classic ESP32).

Each line has 25 comma-separated columns (real examples in docs/sample_csi_lines.txt):

    0 type ("CSI_DATA")   1 id (TX sequence number)   2 mac   3 rssi (dBm)
    4 rate   5 sig_mode   6 mcs   7 bandwidth   8 smoothing   9 not_sounding
    10 aggregation   11 stbc   12 fec_coding   13 sgi   14 noise_floor (dBm)
    15 ampdu_cnt   16 channel   17 secondary_channel
    18 local_timestamp (device clock, microseconds, uint32 printed as signed)
    19 ant   20 sig_len   21 rx_format (firmware repeats sig_mode here; ignore)
    22 len (number of int8 values in data)   23 first_word_invalid
    24 data: "[im0,re0,im1,re1,...]" (imaginary part first)

ESP32-C5/C6 boards print a different, shorter layout that this parser rejects.
"""
from dataclasses import dataclass

import numpy as np

PREFIX = b"CSI_DATA,"
N_COLUMNS = 25
_UINT32 = 1 << 32


@dataclass(frozen=True, slots=True)
class CsiPacket:
    seq: int
    rssi: int
    noise_floor: int
    channel: int
    timestamp_us: int  # raw device clock, wraps every ~71.6 min
    first_word_invalid: bool
    csi: np.ndarray  # int8, interleaved [im0, re0, im1, re1, ...]


def parse_line(raw: bytes) -> CsiPacket | None:
    """Return the packet in one serial line, or None if it is not a complete CSI_DATA line."""
    if not raw.startswith(PREFIX):
        return None
    parts = raw.rstrip(b"\r\n").split(b",", N_COLUMNS - 1)
    if len(parts) != N_COLUMNS:
        return None
    data = parts[24]
    if not (data.startswith(b'"[') and data.endswith(b']"')):
        return None
    try:
        values = [int(v) for v in data[2:-2].split(b",")]
        if len(values) != int(parts[22]):
            return None
        return CsiPacket(
            seq=int(parts[1]) % _UINT32,
            rssi=int(parts[3]),
            noise_floor=int(parts[14]),
            channel=int(parts[16]),
            timestamp_us=int(parts[18]) % _UINT32,
            first_word_invalid=parts[23] == b"1",
            csi=np.array(values, dtype=np.int8),
        )
    except (ValueError, OverflowError):
        return None


class TimestampUnwrapper:
    """Turn the device's wrapping uint32 microsecond clock into an ever-increasing count."""

    def __init__(self) -> None:
        self._offset = 0
        self._last: int | None = None

    def __call__(self, timestamp_us: int) -> int:
        if self._last is not None and timestamp_us < self._last - _UINT32 // 2:
            self._offset += _UINT32
        self._last = timestamp_us
        return timestamp_us + self._offset


def amplitudes(csi: np.ndarray, first_word_invalid: bool = True) -> np.ndarray:
    """Per-subcarrier amplitude from interleaved [im, re] values: shape (..., 2K) -> (..., K).

    When first_word_invalid is set, the first 4 values (2 subcarriers) are garbage,
    so those subcarriers are zeroed rather than dropped to keep indices aligned.
    """
    x = np.asarray(csi, dtype=np.float32).copy()
    if first_word_invalid:
        x[..., :4] = 0
    return np.hypot(x[..., 0::2], x[..., 1::2])
