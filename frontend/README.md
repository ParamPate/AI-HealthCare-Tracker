# Waiting-room monitor page

Next.js page that shows one waiting-room chair live: status, level, breathing rate or
seconds without a breath, and a 30 s breathing wave. It reads the backend's WebSocket
(`backend/main.py`, default `ws://localhost:8000/ws`; override with `NEXT_PUBLIC_WS_URL`).

```bash
npm install      # first time
npm run dev      # http://localhost:3000
```

Start the backend first (see the main README). Files:

- `app/ui/use-stream.ts`: WebSocket connection, reconnects every second; frame type mirrors `StreamFrame` in `backend/main.py`
- `app/ui/chair-monitor.tsx`: the page
- `app/ui/wave.tsx`: the breathing wave, drawn on a canvas every animation frame so it scrolls smoothly
