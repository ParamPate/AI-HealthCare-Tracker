import json
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from db import get_conn, init_db
from services.alerts import classify, evaluate

app = FastAPI(title="AI HealthCare Tracker")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
init_db()
STATIC = Path(__file__).parent / "static"

class Manager:
    def __init__(self): self.clients = []
    async def connect(self, ws):
        await ws.accept(); self.clients.append(ws)
    def disconnect(self, ws):
        if ws in self.clients: self.clients.remove(ws)
    async def broadcast(self, msg: dict):
        for ws in list(self.clients):
            try: await ws.send_json(msg)
            except Exception: self.disconnect(ws)

manager = Manager()

class Checkin(BaseModel):
    seat_id: str
    name: str
    age: Optional[int] = None
    sex: Optional[str] = None
    chief_complaint: Optional[str] = None
    symptoms: dict = {}

class Vitals(BaseModel):
    seat_id: str
    resp_rate_bpm: Optional[float] = None
    heart_rate_bpm: Optional[float] = None
    csi_confidence: float = 1.0
    breathing_pattern: Optional[str] = None
    breathing_severity: Optional[str] = None
    max_gap_s: Optional[float] = None

def create_alert(v_seat, severity, pattern, hr, rr, gap):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO alerts (seat_id, hr, rr, severity, breathing_pattern) VALUES (?,?,?,?,?)",
        (v_seat, hr, rr, severity, pattern))
    conn.commit(); aid = cur.lastrowid; conn.close()
    return {"type": "alert", "alert_id": aid, "seat_id": v_seat, "severity": severity,
            "pattern": pattern, "hr": hr, "rr": rr, "max_gap_s": gap}

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/phone")
def phone(): return FileResponse(STATIC / "phone.html")

@app.post("/api/patients/checkin")
def checkin(p: Checkin):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO patients (seat_id, name, age, sex, chief_complaint, symptoms) VALUES (?,?,?,?,?,?)",
        (p.seat_id, p.name, p.age, p.sex, p.chief_complaint, json.dumps(p.symptoms)))
    conn.commit(); pid = cur.lastrowid; conn.close()
    return {"id": pid, "seat_id": p.seat_id}

@app.get("/api/patients")
def list_patients():
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM patients ORDER BY id DESC")]
    conn.close(); return rows

@app.post("/api/vitals")
async def post_vitals(v: Vitals):
    if v.csi_confidence < 0.5:
        return {"ok": True, "skipped": "low_confidence"}
    sev = classify(v.resp_rate_bpm, v.breathing_severity, v.heart_rate_bpm)
    conn = get_conn()
    conn.execute("INSERT INTO vitals (seat_id, hr, rr, confidence, breathing_pattern) VALUES (?,?,?,?,?)",
                 (v.seat_id, v.heart_rate_bpm, v.resp_rate_bpm, v.csi_confidence, v.breathing_pattern))
    conn.commit(); conn.close()
    await manager.broadcast({"type": "vitals", "severity": sev, **v.model_dump()})
    s, fire = evaluate(v.seat_id, sev)
    if fire:
        alert = create_alert(v.seat_id, sev, v.breathing_pattern, v.heart_rate_bpm, v.resp_rate_bpm, v.max_gap_s)
        s["alert_id"] = alert["alert_id"]
        await manager.broadcast(alert)
        return {"ok": True, "alert": alert}
    return {"ok": True, "severity": sev}

@app.post("/api/alerts/{alert_id}/ack")
async def ack(alert_id: int):
    conn = get_conn()
    conn.execute("UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
    conn.commit(); conn.close()
    await manager.broadcast({"type": "ack", "alert_id": alert_id})
    return {"ok": True}

@app.post("/api/demo/alert")
async def demo_alert(seat_id: str = "CHAIR_01"):
    alert = create_alert(seat_id, "critical", "apnea", None, None, 12.0)
    await manager.broadcast(alert)
    return alert

@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)
