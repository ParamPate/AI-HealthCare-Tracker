"""Build CSI_DATA lines for tests (from Param's serial_reader tests)."""
import csv
import io
import json


def packet_line(data=None, overrides=None) -> bytes:
    """A classic-ESP32 CSI_DATA line; overrides maps column index to replacement text."""
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


class FakeSerial:
    """Stands in for a pyserial port: each read() returns the next chunk, then b"" (timeout)."""

    in_waiting = 4096

    def __init__(self, chunks):
        self.chunks = iter(chunks)

    def read(self, size):
        return next(self.chunks, b"")
