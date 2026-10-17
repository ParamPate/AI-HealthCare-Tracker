"""Run: python -m backend.main --source fake (or --source serial --port PORT)."""
import argparse
import asyncio
from contextlib import asynccontextmanager
import time
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, FiniteFloat
import uvicorn

from backend import config
from backend.live_source import FakeSource, SerialSource


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
    alert: AlertPlaceholder | None


def create_app(source=None):
    source = source if source is not None else FakeSource()

    @asynccontextmanager
    async def lifespan(app):
        source.start()
        try:
            yield
        finally:
            await asyncio.to_thread(source.stop)

    app = FastAPI(title="Breathing monitor", lifespan=lifespan)

    @app.get("/health")
    async def health():
        frame = source.get_latest()
        return {"server": "ok", "source": frame["source"],
                "status": frame["status"], "reason": frame["reason"]}

    @app.get("/api/integrations")
    async def integrations():
        return {
            "phone_alerts": {"status": "placeholder", "transport": "websocket",
                             "endpoint": "/ws", "field": "alert", "acknowledgement_endpoint": None},
            "video": {"status": "placeholder", "url": None},
        }

    @app.websocket("/ws")
    async def websocket_stream(websocket: WebSocket):
        await websocket.accept()

        async def send():
            while True:
                frame = StreamFrame.model_validate({**source.get_latest(), "sent_at": time.time()})
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
        except (WebSocketDisconnect, TimeoutError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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
