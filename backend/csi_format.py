"""Parse CSI_DATA lines printed by Espressif's csi_recv example (classic ESP32).

Each line has 25 comma-separated columns (real examples in docs/sample_csi_lines.txt):

    0 type ("CSI_DATA")   1 id (TX sequence number)   2 mac   3 rssi (dBm)
    4 rate   5 sig_mode   6 mcs   7 bandwidth   8 smoothing   9 not_sounding
    10 aggregation   11 stbc   12 fec_coding   13 sgi   14 noise_floor (dBm)
    15 ampdu_cnt   16 channel   17 secondary_channel
    18 local_timestamp (RX clock, microseconds, uint32 printed as signed)
    19 ant   20 sig_len   21 rx_format (firmware repeats sig_mode here; ignore)
    22 len (number of int8 values in data)   23 first_word_invalid
    24 data: "[im0,re0,im1,re1,...]" (imaginary part first)

parse_line() returns None for lines that are not CSI_DATA (boot logs, the header)
and raises ValueError naming the problem for a CSI_DATA line that is damaged or in
the 15-column ESP32-C5/C6 layout, so callers can count rejections by reason.
"""
import re
from dataclasses import dataclass

import numpy as np

PREFIX = b"CSI_DATA,"
MAX_LINE_BYTES = 16 * 1024
_UINT32 = 1 << 32
_MAC = re.compile(rb"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


@dataclass(frozen=True, slots=True)
class CsiPacket:
    mac: str
    seq: int                # TX sequence number, unsigned
    rssi: int
    noise_floor: int
    bandwidth: int          # 0 = 20 MHz, 1 = 40 MHz
    channel: int
    secondary_channel: int  # 0 none, 1 above, 2 below
    timestamp_us: int       # RX clock, unsigned, wraps every ~71.6 min
    first_word_invalid: bool
    csi: np.ndarray         # int8, interleaved [im0, re0, im1, re1, ...]


def parse_line(raw: bytes) -> CsiPacket | None:
    """Parse one serial line. None for non-CSI lines; ValueError for damaged CSI lines."""
    if not raw.startswith(PREFIX):
        return None
    if len(raw) > MAX_LINE_BYTES:
        raise ValueError("line exceeds maximum length")
    line = raw.rstrip(b"\r\n")
    start = line.find(b',"[')
    if start < 0 or not line.endswith(b']"'):
        raise ValueError("missing quoted CSI array")
    head = line[:start].split(b",")
    if len(head) == 14:
        raise ValueError("unsupported 15-column CSI layout; expected classic ESP32 format")
    if len(head) != 24:
        raise ValueError("expected 25 CSV columns")
    if not _MAC.fullmatch(head[2]):
        raise ValueError("invalid transmitter MAC")
    try:
        f = {i: int(head[i]) for i in range(1, 24) if i != 2}
    except ValueError:
        raise ValueError("invalid integer metadata") from None
    if not all(-(1 << 31) <= f[i] < _UINT32 for i in (1, 18)):
        raise ValueError("packet ID or timestamp outside 32-bit range")
    if f[23] not in (0, 1):
        raise ValueError("first_word must be 0 or 1")
    if not 1 <= f[16] <= 14:
        raise ValueError("invalid 2.4 GHz channel")
    if not -128 <= f[3] <= 127:
        raise ValueError("RSSI outside signed-byte range")
    if f[22] <= 0 or f[22] % 2:
        raise ValueError("CSI length must be positive and even")
    try:
        values = [int(v) for v in line[start + 3:-2].split(b",")]
    except ValueError:
        raise ValueError("invalid CSI array") from None
    if len(values) != f[22]:
        raise ValueError("CSI array length does not match declared length")
    if min(values) < -128 or max(values) > 127:
        raise ValueError("CSI values must be signed-byte integers")
    return CsiPacket(
        mac=head[2].decode().lower(),
        seq=f[1] % _UINT32,
        rssi=f[3],
        noise_floor=f[14],
        bandwidth=f[7],
        channel=f[16],
        secondary_channel=f[17],
        timestamp_us=f[18] % _UINT32,
        first_word_invalid=f[23] == 1,
        csi=np.array(values, dtype=np.int8),
    )


class DeviceClock:
    """Turn the RX board's wrapping uint32 microsecond clock into a continuous count.

    A backward jump of more than half the 32-bit range is a wrap and keeps counting.
    A smaller backward jump means the RX board restarted, so a new segment begins;
    times from different segments must not be compared. Reboots after very long
    outages can look like wraps, since the firmware prints no boot ID.
    """

    def __init__(self) -> None:
        self.offset = 0
        self.segment = 0
        self._last: int | None = None

    def __call__(self, timestamp_us: int) -> tuple[int, int]:
        """Return (continuous microseconds, segment) for one raw timestamp."""
        if self._last is not None and timestamp_us < self._last:
            if self._last - timestamp_us > _UINT32 // 2:
                self.offset += _UINT32
            else:
                self.offset = 0
                self.segment += 1
        self._last = timestamp_us
        return timestamp_us + self.offset, self.segment


def amplitudes(csi: np.ndarray, first_word_invalid: bool = True) -> np.ndarray:
    """Per-subcarrier amplitude from interleaved [im, re] values: shape (..., 2K) -> (..., K).

    When first_word_invalid is set, the first 4 values (2 subcarriers) are garbage,
    so those subcarriers are zeroed rather than dropped to keep indices aligned.
    """
    x = np.asarray(csi, dtype=np.float32).copy()
    if first_word_invalid:
        x[..., :4] = 0
    return np.hypot(x[..., 0::2], x[..., 1::2])
