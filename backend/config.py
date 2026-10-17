"""Bridge settings. Override per machine with environment variables."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = REPO_ROOT / "recordings"

# Leave CSI_PORT unset to auto-detect whichever port is printing CSI_DATA.
SERIAL_PORT = os.environ.get("CSI_PORT") or None
# Console baud rate set in esp-csi's csi_recv sdkconfig.defaults.
SERIAL_BAUD = int(os.environ.get("CSI_BAUD", "921600"))
