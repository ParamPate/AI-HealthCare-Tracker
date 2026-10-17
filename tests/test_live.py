import numpy as np

from backend.live import LiveAnalyser, format_line, summary
from test_breathing import synthetic


def run(t, amp):
    """Feed packets in one-second steps like the live loop; return {second: state}."""
    analyser, states, i = LiveAnalyser(), {}, 0
    for second in range(1, int(t[-1]) + 1):
        j = np.searchsorted(t, second, side="right")
        for row in range(i, j):
            analyser.add(t[row], amp[row], -60)
        i = j
        states[second] = analyser.update()
    return states


def test_locks_on_breathing_and_holds_the_rate_through_fidgeting():
    states = run(*synthetic())  # 15 breaths/min, fidgeting from 40 to 45 s
    assert states[5].status == "starting"
    assert states[38].status == "breathing" and abs(states[38].rate_bpm - 15) <= 1
    assert states[43].status == "moving" and states[43].stale and abs(states[43].rate_bpm - 15) <= 1
    last = states[max(states)]
    assert last.status == "breathing" and abs(last.rate_bpm - 15) <= 1
    format_line(last, debug=True)
    assert "Rate while BREATHING was shown: median 14.9/min" in summary(list(states.values()))


def test_never_shows_breathing_without_it():
    states = run(*synthetic(breathing_on=False))
    assert all(s.status != "breathing" and s.rate_bpm is None for s in states.values())
