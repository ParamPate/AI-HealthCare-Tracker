"""Waiting-room level for the chair: normal, warning, or critical.

Param and akhmcfc own these rules. The server calls classify() on every analysis
update (once a second) and sends the result to the page as `level`. "critical" is
also what should set off the phone alarm. Return None when there is nothing to
classify yet; the page then hides the level.

Useful fields on LiveState (backend/live.py):
    status    "starting", "measuring", "breathing", "moving", "no_rhythm", or "pause"
    rate_bpm  breaths/min while status is "breathing", else None
    pause_s   seconds without a breath while status is "pause", else None
    calm_s    seconds of calm data in the analysed window
    estimate  breathing.RateEstimate with the numbers behind the verdict
"""
from typing import Literal

from backend.live import LiveState

Level = Literal["normal", "warning", "critical"]


def classify(state: LiveState) -> Level | None:
    return None  # Rules go here (Param, akhmcfc).
