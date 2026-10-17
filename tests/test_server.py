import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np

from backend import db, main
from backend.live import LiveState
from backend.live_source import SerialSource, empty_frame


def test_adapter_carries_pause_duration_and_clears_held_rate():
    state = LiveState(75, "pause", None, False, 60, 60, np.array([0.01]), -60, 70, None,
                      np.array([72]), 12)
    sample = SimpleNamespace(host_time=1000, device_time_us=75_000_000)
    frame = SerialSource._state_frame(state, sample)
    assert frame["status"] == "pause" and frame["pause_s"] == 12
    assert frame["t"] == 997 and frame["rate_bpm"] is None
    state = LiveState(75, "moving", 15, True, 60, 60, np.array([]), -60, 70, None)
    assert SerialSource._state_frame(state, sample)["rate_bpm"] is None


def test_shared_publisher_reaches_two_phones_without_waveform_clients(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    class Source:
        tick = 0
        stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True

        def get_latest(self):
            self.tick += 1
            frame = empty_frame("serial", None, self.tick)
            frame.update(t=time.time(), status="pause", pause_s=11 + self.tick / 10,
                         ml_label="breath_hold", ml_model_version="prototype")
            return frame

    source = Source()
    monkeypatch.setattr(main, "time", SimpleNamespace(time=time.time, monotonic=lambda: source.tick / 10))
    app = main.create_app(source)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/dashboard") as first, client.websocket_connect("/ws/dashboard") as second:
            assert first.receive_json()["type"] == "snapshot"
            assert second.receive_json()["type"] == "snapshot"
            alerts = []
            for phone in (first, second):
                for _ in range(16):
                    event = phone.receive_json()
                    if event["type"] == "alert":
                        alerts.append(event)
                        break
            assert len(alerts) == 2 and alerts[0] == alerts[1]
            assert alerts[0]["pattern"] == "breath_hold" and alerts[0]["max_gap_s"] is None
            assert source.tick >= 41  # many messages cannot shorten the 4 s hold confirmation
            with client.websocket_connect("/ws") as waveform:
                assert waveform.receive_json()["pause_s"] >= 11
            assert client.get("/api/alerts/active").json() == [alerts[0]]
            preflight = client.options("/api/alerts/active", headers={
                "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
            assert preflight.headers["access-control-allow-origin"] == "*"
            assert client.get("/api/integrations").json()["phone_alerts"]["endpoint"] == "/ws/dashboard"
            assert client.post("/api/vitals", json={"seat_id": "A"}).status_code == 409
    assert source.stopped


def test_duplicate_snapshot_cannot_confirm_an_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")

    class Source:
        tick = 0
        def start(self): pass
        def stop(self): pass
        def get_latest(self):
            self.tick += 1
            frame = empty_frame("serial", None, 1)
            frame.update(status="pause", pause_s=12,
                         ml_label="breath_hold", ml_model_version="prototype")
            return frame

    source = Source()
    monkeypatch.setattr(main, "time", SimpleNamespace(time=time.time, monotonic=lambda: source.tick))
    app = main.create_app(source)
    with TestClient(app) as client:
        deadline = time.monotonic() + 3
        while source.tick < 6 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert source.tick >= 6
        assert client.get("/api/alerts/active").json() == []
        conn = db.get_conn()
        try:
            assert conn.execute("SELECT count(*) FROM vitals").fetchone()[0] == 1
        finally:
            conn.close()
