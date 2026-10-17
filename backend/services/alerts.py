"""Breathing rules and elapsed-time confirmation shared by live and external input."""
from dataclasses import dataclass

CRITICAL_S = 2.0
RECOVERY_S = 3.0
MAX_UPDATE_GAP_S = 2.5
PAUSE_S = 10.0


def classify(status, rr=None, pause_s=None, *, ml_label=None):
    if ml_label is not None:
        if ml_label == "breath_hold":
            return "breath_hold", "critical"
        if ml_label == "breathing":
            return "normal", "normal"
        return ml_label, "unknown"
    if status in ("no_signal", "motion"):
        return status, "unknown"
    if status == "pause":
        if pause_s is None:
            return "no_signal", "unknown"
        return "breathing_pause", "critical" if pause_s >= PAUSE_S else "warning"
    if status != "breathing" or rr is None:
        return "no_signal", "unknown"
    if rr < 10:
        return "slow_breathing", "critical" if rr < 8 else "warning"
    if rr > 22:
        return "fast_breathing", "critical" if rr > 28 else "warning"
    return "normal", "normal"


@dataclass
class AlertState:
    pending_since: float | None = None
    recovery_since: float | None = None
    last_update: float | None = None
    pattern: str | None = None
    fired: bool = False

    def interrupt(self):
        self.pending_since = self.recovery_since = None
        self.pattern = None

    def evaluate(self, pattern, severity, now):
        if self.last_update is not None and (now <= self.last_update or now - self.last_update > MAX_UPDATE_GAP_S):
            self.interrupt()
        self.last_update = now
        if severity == "critical":
            self.recovery_since = None
            if self.pending_since is None or self.pattern != pattern:
                self.pending_since, self.pattern = now, pattern
            return not self.fired and now - self.pending_since >= CRITICAL_S
        self.pending_since, self.pattern = None, None
        if severity == "normal":
            if self.recovery_since is None:
                self.recovery_since = now
            if now - self.recovery_since >= RECOVERY_S:
                self.fired = False
        else:
            self.recovery_since = None
        return False
