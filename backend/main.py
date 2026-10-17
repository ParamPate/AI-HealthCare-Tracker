"""Run: python -m backend.main --source fake (or --source serial --port PORT)."""
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
from backend.live_source import FakeSource, SerialSource, empty_frame


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
    source: Literal["fake", "serial"]
    seq: int = Field(ge=0)
    waveform: list[WavePoint] = Field(max_length=300)
    waveform_delay_s: FiniteFloat = Field(ge=0)
    pause_s: FiniteFloat | None = Field(default=None, ge=0)
    alert: AlertPlaceholder | None


def create_app(source=None):
    source = source if source is not None else FakeSource()

    alerts = AlertService()
    latest = empty_frame("fake" if isinstance(source, FakeSource) else "serial", "starting")

    async def publish_source():
        nonlocal latest
        last_key, last_publish = None, None
        while True:
            try:
                latest = StreamFrame.model_validate({**source.get_latest(), "sent_at": time.time()}).model_dump()
                now = time.monotonic()
                # Invalid status can replace a snapshot without incrementing its sequence.
                if latest["status"] in ("motion", "no_signal"):
                    alerts.interrupt("CHAIR_01")
                key = (latest["seq"], latest["status"])
                if key != last_key and (last_publish is None or now - last_publish >= 1):
                    await alerts.publish("CHAIR_01", latest["status"], latest["rate_bpm"],
                                         latest["pause_s"], latest["source"], now=now)
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
    parser.add_argument("--source", choices=["fake", "serial"], default="fake")
    parser.add_argument("--port", default=config.SERIAL_PORT, help="ESP32 serial port; default: auto-detect")
    parser.add_argument("--baud", type=int, default=config.SERIAL_BAUD)
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 to allow phones on your LAN")
    parser.add_argument("--http-port", type=int, default=8000)
    args = parser.parse_args()
    if args.baud <= 0 or not 1 <= args.http_port <= 65535:
        parser.error("baud must be positive and HTTP port must be between 1 and 65535")
    source = FakeSource() if args.source == "fake" else SerialSource(args.port, args.baud)
    uvicorn.run(create_app(source), host=args.host, port=args.http_port, workers=1)


if __name__ == "__main__":
    main()
