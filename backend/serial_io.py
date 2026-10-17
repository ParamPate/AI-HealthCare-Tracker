"""Serial helpers for the RX board.

pyserial's readline() reads one byte per call. On Windows that only keeps up with
about 50 CSI lines/s while the board prints about 71/s, so the backlog grows until
lines get corrupted. Read whole chunks and split lines with LineBuffer instead.
"""
import time

import serial
from serial.tools import list_ports

from backend.csi_format import PREFIX

_MAX_PARTIAL_LINE = 1 << 16


def open_port(port: str, baud: int) -> serial.Serial:
    """Open a port without toggling DTR/RTS, which would reset the ESP32."""
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.05
    ser.dtr = False
    ser.rts = False
    ser.open()
    if hasattr(ser, "set_buffer_size"):  # Windows only
        ser.set_buffer_size(rx_size=1 << 20)
    return ser


class LineBuffer:
    """Accumulate serial chunks and hand back complete lines."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        *lines, rest = self._buf.split(b"\n")
        # Wrong baud rate or noise can mean no newline ever arrives.
        self._buf = bytearray(rest) if len(rest) < _MAX_PARTIAL_LINE else bytearray()
        return [bytes(line) for line in lines]


def find_rx_port(baud: int, listen_s: float = 1.5) -> str:
    """Return the USB serial port that is printing CSI_DATA lines (the RX board)."""
    candidates = [p.device for p in list_ports.comports() if p.vid is not None]
    for device in candidates:
        try:
            with open_port(device, baud) as ser:
                deadline = time.monotonic() + listen_s
                tail = b""
                while time.monotonic() < deadline:
                    tail += ser.read(4096)
                    if PREFIX in tail:
                        return device
                    tail = tail[-len(PREFIX):]
        except serial.SerialException:
            continue  # busy (e.g. idf.py monitor) or not a real port
    checked = ", ".join(candidates) or "none found"
    raise RuntimeError(
        f"No USB serial port is printing CSI_DATA (checked: {checked}). Check that the RX board "
        "is plugged in, the TX board is powered (RX prints nothing without it), and no other "
        "program (like idf.py monitor) is using the RX port."
    )
