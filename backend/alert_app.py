"""Phone routes shared by the live server and the standalone external-vitals app."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
from pathlib import Path
import time
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, FiniteFloat

from backend.db import get_conn, init_db
from backend.services.alerts import AlertState, classify

STATIC = Path(__file__).parent / "static"


class Checkin(BaseModel):
    seat_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    age: int | None = Field(default=None, ge=0, le=130)
    sex: str | None = None
    chief_complaint: str | None = None
    symptoms: dict = Field(default_factory=dict)


class Vitals(BaseModel):
    seat_id: str = Field(min_length=1, max_length=100)
    resp_rate_bpm: FiniteFloat | None = Field(default=None, ge=0)
    csi_confidence: FiniteFloat | None = Field(default=None, ge=0, le=1)
    breathing_pattern: str | None = None
    breathing_severity: Literal["normal", "warning", "critical"] | None = None
    max_gap_s: FiniteFloat | None = Field(default=None, ge=0)


class AlertService:
    # shortcut: timers belong to one process; use shared state before adding server workers.
    def __init__(self):
        self.clients = {}
        self.states = {}
        self.active = {}

    def start(self):
        init_db()
        conn = get_conn()
        try:
            for row in conn.execute("SELECT * FROM alerts WHERE acknowledged = 0 ORDER BY id"):
                alert = {"type": "alert", "alert_id": row["id"], "seat_id": row["seat_id"],
                         "severity": row["severity"], "pattern": row["breathing_pattern"],
                         "rr": row["rr"], "max_gap_s": row["max_gap_s"], "source": row["source"]}
                self.active[alert["alert_id"]] = alert
                self.states.setdefault(row["seat_id"], AlertState()).fired = True
        finally:
            conn.close()

    async def broadcast(self, msg):
        for ws, queue in tuple(self.clients.items()):
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                self.clients.pop(ws, None)
                # A reconnect gets the current active alerts instead of an old backlog.
                try:
                    await asyncio.wait_for(ws.close(code=1013), 1)
                except Exception:
                    pass

    def interrupt(self, seat_id):
        self.states.setdefault(seat_id, AlertState()).interrupt()

    async def publish(self, seat_id, status, rr, pause_s, source, now=None, confidence=None):
        pattern, severity = classify(status, rr, pause_s)
        if confidence is not None and confidence < 0.5:
            pattern, severity = "no_signal", "unknown"
        # Unknown input must not carry a held rate into classification or storage.
        if severity == "unknown":
            rr, pause_s = None, None
        conn = get_conn()
        try:
            conn.execute("INSERT INTO vitals (seat_id, rr, confidence, breathing_pattern) VALUES (?,?,?,?)",
                         (seat_id, rr, confidence, pattern))
            conn.commit()
        finally:
            conn.close()
        await self.broadcast({"type": "vitals", "seat_id": seat_id, "resp_rate_bpm": rr,
                              "breathing_pattern": pattern, "severity": severity,
                              "max_gap_s": pause_s, "source": source})
        state = self.states.setdefault(seat_id, AlertState())
        fire = state.evaluate(pattern, severity, time.monotonic() if now is None else now)
        if fire and not any(a["seat_id"] == seat_id for a in self.active.values()):
            alert = await self.create_alert(seat_id, pattern, rr, pause_s, source)
            state.fired = True
            return {"ok": True, "severity": severity, "alert": alert}
        return {"ok": True, "severity": severity}

    async def create_alert(self, seat_id, pattern, rr, gap, source):
        conn = get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO alerts (seat_id, rr, severity, breathing_pattern, max_gap_s, source) VALUES (?,?,?,?,?,?)",
                (seat_id, rr, "critical", pattern, gap, source))
            conn.commit()
            alert_id = cur.lastrowid
        finally:
            conn.close()
        alert = {"type": "alert", "alert_id": alert_id, "seat_id": seat_id, "severity": "critical",
                 "pattern": pattern, "rr": rr, "max_gap_s": gap, "source": source}
        self.active[alert_id] = alert
        await self.broadcast(alert)
        return alert


def create_router(service, *, allow_vitals=False):
    router = APIRouter()

    @router.get("/phone")
    def phone():
        return FileResponse(STATIC / "phone.html")

    @router.post("/api/patients/checkin")
    def checkin(p: Checkin):
        conn = get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO patients (seat_id, name, age, sex, chief_complaint, symptoms) VALUES (?,?,?,?,?,?)",
                (p.seat_id, p.name, p.age, p.sex, p.chief_complaint, json.dumps(p.symptoms)))
            conn.commit()
            return {"id": cur.lastrowid, "seat_id": p.seat_id}
        finally:
            conn.close()

    @router.get("/api/patients")
    def list_patients():
        conn = get_conn()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM patients ORDER BY id DESC")]
        finally:
            conn.close()

    @router.post("/api/vitals")
    async def post_vitals(v: Vitals):
        if not allow_vitals:
            raise HTTPException(409, "Live source owns vitals; use backend.alert_app:app for external input")
        status = ("pause" if v.breathing_pattern in ("apnea", "breathing_pause", "pause")
                  else v.breathing_pattern if v.breathing_pattern in ("no_signal", "motion")
                  else "breathing" if v.resp_rate_bpm is not None else "no_signal")
        return await service.publish(v.seat_id, status, v.resp_rate_bpm, v.max_gap_s,
                                     "external", confidence=v.csi_confidence)

    @router.get("/api/alerts/active")
    async def active_alerts():
        return list(service.active.values())

    @router.post("/api/alerts/{alert_id}/ack")
    async def ack(alert_id: int):
        conn = get_conn()
        try:
            cur = conn.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
            conn.commit()
            if not cur.rowcount:
                raise HTTPException(404, "Alert not found")
        finally:
            conn.close()
        service.active.pop(alert_id, None)
        await service.broadcast({"type": "ack", "alert_id": alert_id})
        return {"ok": True}

    @router.post("/api/demo/alert")
    async def demo_alert(seat_id: str = "DEMO"):
        return await service.create_alert(seat_id, "breathing_pause", None, 12.0, "fake")

    @router.websocket("/ws/dashboard")
    async def ws_dashboard(ws: WebSocket):
        await ws.accept()
        queue = asyncio.Queue(maxsize=32)
        service.clients[ws] = queue
        queue.put_nowait({"type": "snapshot", "alerts": list(service.active.values())})

        async def send():
            while True:
                await asyncio.wait_for(ws.send_json(await queue.get()), timeout=2)

        async def receive():
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, RuntimeError, asyncio.CancelledError):
            pass
        finally:
            service.clients.pop(ws, None)
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(ws.close(), timeout=1)

    return router


def create_app():
    service = AlertService()

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        yield

    app = FastAPI(title="External breathing alerts", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(create_router(service, allow_vitals=True))
    app.state.alerts = service

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
