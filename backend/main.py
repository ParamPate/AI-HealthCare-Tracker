"""Run: python -m backend.main --source serial (or --source replay --file recordings/<file>.parquet,
or --source fake). The page (frontend/, Next.js) connects to ws://localhost:8000/ws; the phone
alarm page is /phone."""
import argparse
import asyncio
from contextlib import asynccontextmanager, suppress
import time
import logging
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, FiniteFloat
import uvicorn

from backend.alert_app import AlertService, create_router
from backend import config
from backend.live_source import CHAIR, FakeSource, ReplaySource, SerialSource, empty_frame
from backend.services.alerts import classify


class WavePoint(BaseModel):
    t: FiniteFloat
    breath: FiniteFloat | None


class AlertPlaceholder(BaseModel):
    id: str
    kind: Literal["simulated_pause"]


class StreamFrame(BaseModel):
    t: FiniteFloat | None
    sent_at: FiniteFloat
    breath: FiniteFloat | None
    rate_bpm: FiniteFloat | None = Field(ge=0)
    status: Literal["no_signal", "motion", "breathing", "pause"]
    reason: str | None
    source: Literal["fake", "serial", "replay"]
    seq: int = Field(ge=0)
    waveform: list[WavePoint] = Field(max_length=300)
    waveform_delay_s: FiniteFloat = Field(ge=0)
    pause_s: FiniteFloat | None = Field(default=None, ge=0)  # seconds without a breath while status is "pause"
    alert: AlertPlaceholder | None
    chair: str = CHAIR
    # services/alerts.py classify(), the same rules that ring the phone; None while unknown.
    level: Literal["normal", "warning", "critical"] | None = None
    calm_s: FiniteFloat | None = None  # calm seconds in the analysed window (MEASURING needs about 30)
    rssi: int | None = None
    packets_per_s: FiniteFloat | None = None
    ml_label: Literal["breathing", "breath_hold", "checking", "motion", "no_signal"] | None = None
    ml_hold_score: FiniteFloat | None = Field(default=None, ge=0, le=1)
    ml_model_version: str | None = None


def create_app(source=None):
    source = source if source is not None else FakeSource()

    alerts = AlertService()
    latest = empty_frame(getattr(source, "name", "serial"), "starting")

    async def publish_source():
        nonlocal latest
        last_key, last_publish = None, None
        while True:
            try:
                frame = {**source.get_latest(), "sent_at": time.time()}
                # The model only knows breathing vs hold; panting uses the fast-breathing rate rule.
                ml_label = (None if frame["source"] == "fake" or frame["reason"] == "panting"
                            else frame["ml_label"] or "no_signal")
                severity = classify(frame["status"], frame["rate_bpm"], frame["pause_s"],
                                    ml_label=ml_label)[1]
                frame["level"] = None if severity == "unknown" else severity
                latest = StreamFrame.model_validate(frame).model_dump()
                now = time.monotonic()
                # Invalid status can replace a snapshot without incrementing its sequence.
                if severity == "unknown":
                    alerts.interrupt("CHAIR_01")
                key = (latest["seq"], latest["status"], ml_label)
                interval = 0.5 if ml_label is not None else 1
                if key != last_key and (last_publish is None or now - last_publish >= interval):
                    await alerts.publish("CHAIR_01", latest["status"], latest["rate_bpm"],
                                         latest["pause_s"], latest["source"], now=now, ml_label=ml_label)
                    last_key, last_publish = key, now
            except Exception:
                logging.getLogger(__name__).exception("Breathing alert update failed")
                alerts.interrupt("CHAIR_01")
                latest = empty_frame(latest["source"], "processing_error")
            await asyncio.sleep(1 / 15)

    @asynccontextmanager
    async def lifespan(app):
        alerts.start()
        source.start()
        publisher = asyncio.create_task(publish_source())
        try:
            yield
        finally:
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
            await asyncio.to_thread(source.stop)

    app = FastAPI(title="Breathing monitor", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(create_router(alerts))
    app.state.alerts = alerts

    @app.get("/health")
    async def health():
        frame = latest
        return {"server": "ok", "source": frame["source"],
                "status": frame["status"], "reason": frame["reason"]}

    @app.get("/api/integrations")
    async def integrations():
        return {
            "phone_alerts": {"status": "connected", "transport": "websocket",
                             "endpoint": "/ws/dashboard", "page": "/phone",
                             "acknowledgement_endpoint": "/api/alerts/{alert_id}/ack"},
            "video": {"status": "placeholder", "url": None},
        }

    @app.websocket("/ws")
    async def websocket_stream(websocket: WebSocket):
        await websocket.accept()

        async def send():
            while True:
                frame = StreamFrame.model_validate({**latest, "sent_at": time.time()})
                await asyncio.wait_for(websocket.send_json(frame.model_dump()), timeout=2.0)
                await asyncio.sleep(1 / 15)

        async def disconnected():
            while (await websocket.receive())["type"] != "websocket.disconnect":
                pass

        tasks = [asyncio.create_task(send()), asyncio.create_task(disconnected())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, TimeoutError, asyncio.CancelledError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(websocket.close(), timeout=1)

    return app


app = create_app()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=["fake", "serial", "replay"], default="fake")
    parser.add_argument("--file", help="recording to loop with --source replay (recordings/<file>.parquet)")
    parser.add_argument("--port", default=config.SERIAL_PORT, help="ESP32 serial port; default: auto-detect")
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 to allow phones on your LAN")
    parser.add_argument("--http-port", type=int, default=8000)
    args = parser.parse_args()
    if args.baud <= 0 or not 1 <= args.http_port <= 65535:
        parser.error("baud must be positive and HTTP port must be between 1 and 65535")
    if args.source == "replay" and not args.file:
        parser.error("--source replay needs --file recordings/<file>.parquet")
    source = (FakeSource() if args.source == "fake" else ReplaySource(args.file) if args.source == "replay"
              else SerialSource(args.port, args.baud))
    uvicorn.run(create_app(source), host=args.host, port=args.http_port, workers=1)


if __name__ == "__main__":
    main()
