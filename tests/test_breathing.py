import numpy as np
import pytest

from backend import breathing


def synthetic(seed=0, duration=90.0, k=40, bpm=15.0, breathing_on=True, motion=(40.0, 45.0)):
    """Irregular packets like the real board: some subcarriers breathe, plus optional fidgeting.

    The fidgeting is fast, large and random, and ends in a posture shift: every
    subcarrier keeps a new level afterwards, the kind of jump a filter turns into a fake wave.
    """
    rng = np.random.default_rng(seed)
    t = np.sort(rng.uniform(0, duration, int(duration * 71)))
    base = rng.uniform(15, 30, k)
    sensitivity = rng.normal(0, 1, k) * (rng.random(k) < 0.4)
    wave = np.sin(2 * np.pi * bpm / 60 * t) if breathing_on else np.zeros_like(t)
    amp = base * (1 + 0.03 * np.outer(wave, sensitivity)) + rng.normal(0, 0.6, (len(t), k))
    if motion:
        moving = (t > motion[0]) & (t < motion[1])
        amp[moving] *= 1 + 0.15 * rng.normal(0, 1, (moving.sum(), k))
        amp[t > np.mean(motion)] *= 1 + 0.08 * rng.normal(0, 1, k)
    return t, np.abs(amp)


def test_motion_score_is_about_one_when_still():
    t, amp = synthetic(motion=None, breathing_on=False)
    _, x, _ = breathing.prepare(t, amp)
    assert 0.7 < np.median(breathing.motion_score(x)) < 1.4


def test_motion_mask_covers_the_fidgeting_only():
    r = breathing.analyse(*synthetic())
    grid, moving = r["grid"], r["moving"]
    assert moving[(grid > 40.5) & (grid < 44.5)].all()
    assert moving[(grid > 5) & (grid < 35)].mean() < 0.1


def test_jump_during_movement_becomes_a_flat_join():
    x = np.concatenate([np.zeros(100), np.ones(100)])[:, None]
    moving = np.zeros(200, bool)
    moving[90:110] = True
    out = breathing.remove_steps(x, moving)
    assert np.abs(out).max() < 1e-9


def test_finds_breathing_rate_despite_fidgeting_and_posture_shift():
    est = breathing.analyse(*synthetic())["estimate"]
    assert est.steady, est.verdict()
    assert abs(est.rate_bpm - 15) <= 1


def test_slow_breathing_at_5_per_minute():
    est = breathing.analyse(*synthetic(bpm=5.0, duration=120.0, motion=(60.0, 65.0)))["estimate"]
    assert est.steady, est.verdict()
    assert abs(est.rate_bpm - 5) <= 0.7


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("motion", [None, (40.0, 45.0)])
def test_no_breathing_is_not_called_breathing(seed, motion):
    est = breathing.analyse(*synthetic(seed=seed, breathing_on=False, motion=motion))["estimate"]
    assert not est.steady, est.verdict()


def test_too_few_cycles_is_not_a_rhythm():
    est = breathing.analyse(*synthetic(bpm=4.0, duration=30.0, motion=None))["estimate"]
    assert not est.steady
    assert "too few cycles" in est.verdict()


def test_main_peak_skips_the_drift_edge():
    f = np.linspace(0, 1, 101)
    p = 5 * np.exp(-8 * f) + np.exp(-((f - 0.5) / 0.03) ** 2)  # drift falling from the edge + a bump
    assert breathing.main_peak(p) == 50


def test_half_frequency_energy_is_noted_not_decided():
    t = np.arange(0, 120, 1 / breathing.FS)
    gate = np.ones_like(t)
    both = np.cos(2 * np.pi * 16 / 60 * t) + 0.7 * np.cos(2 * np.pi * 8 / 60 * t)
    est = breathing.estimate_rate(both, gate)
    assert abs(est.rate_bpm - 16) < 0.5 and est.maybe_half
    assert "or 8.0/min if the signal shows two bumps per breath" in est.verdict()
    assert not breathing.estimate_rate(np.cos(2 * np.pi * 16 / 60 * t), gate).maybe_half
