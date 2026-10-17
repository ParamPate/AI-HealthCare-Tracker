# Waiting-room monitor page

The landing page (`/`) introduces the project: a 3D line drawing of the waiting room and a grid of
animated tiles. The monitor (`/monitor`) is the Next.js page that shows one waiting-room chair live: status, level, breathing rate or
seconds without a breath, and a 30 s breathing wave. It reads the backend's WebSocket
(`backend/main.py`, default `ws://localhost:8000/ws`; override with `NEXT_PUBLIC_WS_URL`).

```bash
npm install      # first time
npm run dev      # http://localhost:3000 (landing), http://localhost:3000/monitor (monitor)
```

Start the backend first (see the main README). Files:

- `app/page.tsx`: the landing page; `app/monitor/page.tsx`: the monitor
- `app/ui/room/`: the 3D waiting room (three.js), drawn as hand-sketched lines; the card and the full-screen explorer
- `app/ui/gallery/`: the animated tiles and their zoom lightbox; tiles are drawn at 502 px wide and scaled to the column
- `app/ui/use-stream.ts`: WebSocket connection, reconnects every second; frame type mirrors `StreamFrame` in `backend/main.py`
- `app/ui/chair-monitor.tsx`: the monitor page
- `app/ui/wave.tsx`: the breathing wave, drawn on a canvas every animation frame so it scrolls smoothly
