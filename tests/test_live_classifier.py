from dataclasses import replace
from types import SimpleNamespace
import time

from fastapi.testclient import TestClient
import numpy as np
import pytest

from backend import db, live_source, main
from backend.classifier import predict_window, read_recording
from backend.live import LiveState
from backend.live_source import LiveClassifier, ReplaySource, SerialSource, empty_frame


@pytest.fixture(scope="module")
def raw_window():
    samples = read_recording("recordings/20261017-013311_hold.parquet")
    end = samples[0].device_time_us + 10_250_000
    return [s for s in samples if s.device_time_us <= end]


def test_live_matches_offline_raw_window_and_limits_prediction_cadence(raw_window, monkeypatch):
    classifier = LiveClassifier()
    calls = []

    def predict(model, samples, end_s):
        calls.append(end_s)
        return predict_window(model, samples, end_s)

    monkeypatch.setattr(live_source, "predict_window", predict)
    first = raw_window[0].device_time_us
    assert classifier.update([s for s in raw_window if s.device_time_us < first + 10_000_000])["ml_hold_score"] is None
    remaining = [s for s in raw_window if s.device_time_us >= first + 10_000_000]
    result = classifier.update(remaining)
    end = raw_window[-1].device_time_us / 1e6
    expected = predict_window(classifier.model, [s for s in raw_window if s.device_time_us / 1e6 >= end - 10], end)
    assert result["ml_label"] == ("checking" if expected["label"] == "breath_hold" else expected["label"])
    assert result["ml_hold_score"] == expected["hold_score"] is not None
    assert classifier.update(raw_window[-1:]) == result
    assert len(classifier.votes) == 1
    classifier.update([replace(raw_window[-1], device_time_us=raw_window[-1].device_time_us + 200_000)])
    assert len(calls) == 1
    classifier.update([replace(raw_window[-1], device_time_us=raw_window[-1].device_time_us + 1_100_000)])
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["mac", "segment", "length", "channel", "bandwidth",
                                  "secondary_channel", "backward", "gap"])
def test_configuration_and_time_changes_clear_predictions(raw_window, change):
    classifier = LiveClassifier()
    assert classifier.update(raw_window)["ml_hold_score"] is not None
    last = raw_window[-1]
    sample = replace(last, device_time_us=last.device_time_us + 20_000)
    if change == "segment":
        sample = replace(sample, segment=last.segment + 1)
    elif change in ("backward", "gap"):
        sample = replace(sample, device_time_us=last.device_time_us + (-1 if change == "backward" else 2_000_001))
    else:
        value = {"mac": "1a:00:00:00:00:01", "length": last.packet.csi[:-2], "channel": 6,
                 "bandwidth": 1 - last.packet.bandwidth, "secondary_channel": 2}
        sample = replace(sample, packet=replace(last.packet, **{
            "csi" if change == "length" else change: value[change]}))
    result = classifier.update([sample])
    assert result["ml_label"] == "no_signal" and result["ml_hold_score"] is None
    assert len(classifier.samples) == 1


def test_sparse_input_is_unavailable(raw_window):
    classifier = LiveClassifier()
    sparse = raw_window[::10] + raw_window[-1:]
    assert len(sparse) < 200
    assert classifier.update(sparse)["ml_hold_score"] is None


@pytest.mark.parametrize("reason", ["stale_input", "disconnected", "processing_delayed"])
def test_host_failures_never_keep_a_model_score(reason):
    source = SerialSource()
    source._last_input = source._last_result = time.monotonic()
    source._frame.update(ml_label="breath_hold", ml_hold_score=0.99)
    if reason == "disconnected":
        source._error = reason
    elif reason == "stale_input":
        source._last_input -= 3
    else:
        source._last_result -= 6
    frame = source.get_latest()
    assert frame["reason"] == reason
    assert frame["ml_hold_score"] is None


def test_processing_thread_scores_quiet_data_without_a_dsp_rate(raw_window, monkeypatch):
    source = SerialSource()
    source._pending.extend(raw_window)
    stops = iter([False, True])
    source._stop = SimpleNamespace(wait=lambda _: next(stops))
    state = LiveState(10.25, "no_rhythm", None, False, 10, 10, np.array([]), -60, 70, None)
    monkeypatch.setattr(live_source, "LiveAnalyser", lambda **_: SimpleNamespace(
        add=lambda *args: None, update=lambda: state))
    source._process()
    assert source._frame["status"] == "no_signal"  # DSP contract stays independent.
    assert source._frame["ml_hold_score"] is not None
    assert source._frame["ml_model_version"].startswith("breathing-demo-v3:")


def test_replay_preserves_raw_metadata_and_resets_at_loop_boundary(raw_window, monkeypatch):
    samples = raw_window[:2]
    source = ReplaySource("unused")
    monkeypatch.setattr(live_source, "read_recording", lambda _: samples)
    times = iter([0, 0, 0, 0.1, 0.1])
    monkeypatch.setattr(live_source, "time", SimpleNamespace(monotonic=lambda: next(times), time=lambda: 1000))
    stops = iter([False, False, True])
    source._stop = SimpleNamespace(is_set=lambda: next(stops), wait=lambda _: None)
    source._acquire()
    pending = list(source._pending)
    assert pending[0].packet is samples[0].packet
    assert pending[1].packet is samples[1].packet
    assert pending[2].segment != pending[1].segment
    assert pending[2].packet is samples[0].packet


def test_websocket_carries_prototype_fields_without_triggering_phone_alerts(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "alerts.db")

    class Source:
        name = "serial"
        tick = 0
        def start(self): pass
        def stop(self): pass
        def get_latest(self):
            self.tick += 1
            return {**empty_frame("serial", None, self.tick), "status": "breathing", "rate_bpm": 15,
                    "ml_label": "breath_hold", "ml_hold_score": 0.99, "ml_model_version": "prototype"}

    source = Source()
    monkeypatch.setattr(main, "time", SimpleNamespace(time=time.time, monotonic=lambda: source.tick))
    with TestClient(main.create_app(source)) as client:
        deadline = time.monotonic() + 3
        while source.tick < 6 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert source.tick >= 6
        with client.websocket_connect("/ws") as ws:
            frame = ws.receive_json()
            assert frame["ml_label"] == "breath_hold" and frame["ml_hold_score"] == 0.99
        assert client.get("/api/alerts/active").json() == []
