import asyncio
from functools import partial

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.alert_app import AlertService, create_app
from backend.services.alerts import AlertState, classify


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "healthcare.db")


@pytest.mark.parametrize("status,rr,gap,expected", [
    ("breathing", 15, None, ("normal", "normal")),
    ("breathing", 24, None, ("fast_breathing", "warning")),
    ("breathing", 29, None, ("fast_breathing", "critical")),
    ("breathing", 7, None, ("slow_breathing", "critical")),
    ("breathing", None, None, ("no_signal", "unknown")),
    ("pause", None, 9, ("breathing_pause", "warning")),
    ("pause", None, 11, ("breathing_pause", "critical")),
    ("pause", None, None, ("no_signal", "unknown")),
    ("motion", 7, 20, ("motion", "unknown")),
    ("no_signal", 7, 20, ("no_signal", "unknown")),
])
def test_classification_requires_usable_breathing(status, rr, gap, expected):
    assert classify(status, rr, gap) == expected


@pytest.mark.parametrize("ml_label,expected", [
    ("breath_hold", ("breath_hold", "critical")),
    ("breathing", ("normal", "normal")),
    ("checking", ("checking", "unknown")),
    ("motion", ("motion", "unknown")),
    ("no_signal", ("no_signal", "unknown")),
])
def test_model_labels_override_dsp_values(ml_label, expected):
    assert classify("pause", 7, 15, ml_label=ml_label) == expected


def test_confirmation_is_elapsed_time_and_requires_continuous_updates():
    state = AlertState()
    for t in (0, 0.01, 0.02, 0.2, 1, 1.99):
        assert not state.evaluate("breathing_pause", "critical", t)
    assert state.evaluate("breathing_pause", "critical", 2)
    state = AlertState()
    assert not state.evaluate("breathing_pause", "critical", 0)
    assert not state.evaluate("breathing_pause", "critical", 10)  # missing updates reset
    assert not state.evaluate("fast_breathing", "critical", 11)  # changed reason resets
    assert not state.evaluate("fast_breathing", "critical", 12)
    assert state.evaluate("fast_breathing", "critical", 13)


def test_motion_loss_and_low_confidence_interrupt_pending_alert():
    async def scenario():
        for status, confidence in (("motion", None), ("no_signal", None), ("pause", 0.1)):
            service = AlertService()
            service.start()
            await service.publish("A", "pause", None, 11, "serial", now=0)
            await service.publish("A", status, None, 12, "serial", now=1, confidence=confidence)
            for t in (2, 3):
                result = await service.publish("A", "pause", None, 11 + t, "serial", now=t)
                assert "alert" not in result
            # Interrupt without a new sequence (the serial adapter's stale snapshot).
            service.interrupt("A")
            assert "alert" not in await service.publish("A", "pause", None, 15, "serial", now=4)
    asyncio.run(scenario())


@pytest.mark.parametrize("use_ml", [False, True])
def test_phone_event_ack_reconnect_recovery_and_restart(use_ml):
    app = create_app()
    with TestClient(app) as client:
        service = app.state.alerts

        def publish(status, t):
            ml_label = {"pause": "breath_hold", "breathing": "breathing", "motion": "motion"}[status] if use_ml else None
            return client.portal.call(partial(service.publish, "A", status,
                                              15 if status == "breathing" else None,
                                              12 if status == "pause" else None, "serial", t,
                                              ml_label=ml_label))

        hold = 5 if use_ml else 3  # model holds need HOLD_CRITICAL_S (4 s), DSP pauses CRITICAL_S (2 s)
        with client.websocket_connect("/ws/dashboard") as phone:
            assert phone.receive_json() == {"type": "snapshot", "alerts": []}
            for t in range(hold):
                result = publish("pause", t)
                assert phone.receive_json()["type"] == "vitals"
            alert = phone.receive_json()
            assert alert == result["alert"]
            assert alert["pattern"] == ("breath_hold" if use_ml else "breathing_pause")
            assert alert["max_gap_s"] == (None if use_ml else 12)
            assert alert["source"] == "serial"
        with client.websocket_connect("/ws/dashboard") as phone:
            assert phone.receive_json()["alerts"] == [alert]
            assert client.post(f"/api/alerts/{alert['alert_id']}/ack").status_code == 200
            assert phone.receive_json() == {"type": "ack", "alert_id": alert["alert_id"]}
        for t in range(hold, hold + 4):
            assert "alert" not in publish("pause", t)  # acknowledge doesn't rearm
        publish("motion", hold + 4)
        for t in range(hold + 5, hold + 8):
            assert "alert" not in publish("pause", t)  # neither does motion
        for t in range(hold + 8, hold + 12):
            publish("breathing", t)
        for t in range(hold + 12, 2 * hold + 12):
            result = publish("pause", t)
        second = result["alert"]
        assert second["alert_id"] != alert["alert_id"]
    with TestClient(create_app()) as client:
        with client.websocket_connect("/ws/dashboard") as phone:
            assert phone.receive_json()["alerts"] == [second]
        assert client.post("/api/alerts/999/ack").status_code == 404


def test_external_api_validates_input_and_does_not_trust_severity():
    with TestClient(create_app()) as client:
        assert client.post("/api/vitals", json={"seat_id": "A", "max_gap_s": -1}).status_code == 422
        assert client.post("/api/vitals", json={"seat_id": "A", "csi_confidence": 2}).status_code == 422
        response = client.post("/api/vitals", json={"seat_id": "A", "breathing_severity": "critical"})
        assert response.json()["severity"] == "unknown"
        assert client.get("/phone").status_code == 200


def test_database_upgrade_preserves_existing_alerts():
    conn = db.get_conn()
    conn.execute("""CREATE TABLE alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, seat_id TEXT, rr REAL, severity TEXT,
        breathing_pattern TEXT, acknowledged INTEGER DEFAULT 0)""")
    conn.execute("INSERT INTO alerts (seat_id, rr, severity, breathing_pattern) VALUES ('A', 7, 'critical', 'slow_breathing')")
    conn.commit()
    conn.close()
    service = AlertService()
    service.start()
    service.start()  # migration can run again safely
    assert len(service.active) == 1
    assert service.active[1]["rr"] == 7 and service.active[1]["source"] is None
