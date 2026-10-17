# Waiting-room monitor page

The landing page (`/`) is the waiting room in 3D: two ESP32 boards 1 m apart at chest height, the seated
person in chair 1 about 30 cm behind the line between them, and WiFi waves that bow out away from the person;
each breath out pushes them a little further. The person breathes at the backend's live rate, and stops during a detected pause. With no
backend running they breathe at a simulated 14/min. The monitor (`/monitor`) is the Next.js page that shows one waiting-room chair live: status, level, breathing rate or
seconds without a breath, and a 30 s breathing wave. It reads the backend's WebSocket
(`backend/main.py`, default `ws://localhost:8000/ws`; override with `NEXT_PUBLIC_WS_URL`).

```bash
npm install      # first time
npm run dev      # http://localhost:3000 (landing), http://localhost:3000/monitor (monitor)
```

Start the backend first (see the main README). Files:

- `app/page.tsx`: the landing page; `app/monitor/page.tsx`: the monitor
- `app/ui/room/`: the 3D waiting room (three.js), drawn as hand-sketched lines. `models.ts` has the objects (the boards,
  the chair and the person), `room-view.ts` the camera, breathing and radio link, `waiting-room.tsx` the page
- `app/ui/use-stream.ts`: WebSocket connection, reconnects every second; frame type mirrors `StreamFrame` in `backend/main.py`
- `app/ui/chair-monitor.tsx`: the monitor page
- `app/ui/wave.tsx`: the breathing wave, drawn on a canvas every animation frame so it scrolls smoothly
