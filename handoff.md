# Handoff: live demo, breath-hold and panting phone alerts

Status as of 2026-10-17 ~17:55. Changes are **not committed** yet (see "Changed files").

## Goal for the demo

Two alert paths, both live from the ESP32 boards (no replay), both ring the phone:

1. **Breath hold** -> phone alert `breath_hold`.
2. **Panting** (about 5 s of it) -> phone alert `fast_breathing` with the rate.

## How to run it

Two terminals from the project root. Close any other program using the RX port (COM4) first.

```bash
uv run python -m backend.main --source serial --host 0.0.0.0   # backend, live board, reachable by phones
cd frontend && npm run dev                                      # page
```

| What | Link |
|---|---|
| Monitor (laptop) | http://localhost:3000/monitor |
| Phone alarm | http://172.20.10.4:8000/phone (laptop's LAN IP; recheck if the network changes) |

The laptop is on an iPhone hotspot (172.20.10.x). The phone must be the hotspot phone or joined to it.
On the phone: open the link, tap **Enable alarm**, keep the screen on, Silent Mode off, volume up.
Sound check without the boards: `curl -X POST http://localhost:8000/api/demo/alert`, then acknowledge it.

## How each path works

| | Breath hold | Panting |
|---|---|---|
| Detected by | Trained model (`models/breathing-demo-v3.json`, `ml_label = breath_hold`) | Rule-based detector, `backend/panting.py` |
| Signal | Breathing movement goes flat | One sharp, steady rhythm at 60 to 150/min shared by most subcarriers |
| Confirmation | Model votes, then **4 s** of continued hold (`HOLD_CRITICAL_S`) | 2 updates in a row (`PANT_CONFIRM`), then 2 s (`CRITICAL_S`) |
| Phone alert after onset | about 10 s | about 6 s |
| Page | red POSSIBLE BREATH HOLD | red PANTING with the rate |

While panting is detected, the model's label is ignored (`main.py`), so the existing rate rule
(`classify()`: above 28/min is critical `fast_breathing`) drives the phone. One alert per episode; it
stays active until acknowledged and rearms after 3 s of normal breathing.

## Why panting was never detected before (root cause)

- The breathing filter only covers 3 to 30 breaths/min (`breathing.BAND`). Panting is 60 to 100+/min.
- Energy at 1 Hz and above counts as movement (`breathing.MOTION_BAND`), so panting read as MOVEMENT.
- The model only knows `breathing` vs `breath_hold`; panting flattens the slow wave, so it often read as a **hold**.
- For the live board the phone used the model label only, so the old fast-breathing rule never ran.

## Demo setup requirements (important)

Panting is only visible to the sensor when the setup is right. With the old placement and gentle
panting, the signal looked the same as sitting still, and no threshold could separate them.

1. **Board placement:** chest directly on the line between TX and RX, at chest height, about 0.5 to 1 m apart.
   This is the placement used for the successful rehearsal. Do not move the boards before the demo.
2. **Pant big:** mouth open, shoulders and chest visibly moving, at least 1 pant per second
   (rehearsal: 66 to 81/min). Below 60/min it is not detected.
3. **Breathe at a natural pace** (12 to 16/min) in the normal parts. Very slow breathing (about 7/min)
   made the model see short "holds"; the 4 s confirmation now filters those out.
4. **Suggested demo order:** normal 20 s -> pant 15 to 20 s (alert, acknowledge) -> normal 20 s, until the
   page shows green BREATHING -> hold 15 to 20 s (alert, acknowledge) -> normal.
5. Allow about 30 s after a backend restart before the first test (warm-up).

## Evidence

Rehearsal recording `recordings/20261017-174455_demo_rehearsal.parquet` (new placement, marked phases:
normal 17:45:20, pant 17:45:37, normal 17:46:03, hold 17:46:29, done 17:47:02), replayed offline through
the same steps as the live server (analyser, model, alert rules):

- PANTING detected 17:45:40 (3 s in); phone `fast_breathing RR 70` at 17:45:43 (6 s in). PANTING appeared
  only during the panting phase.
- Phone `breath_hold` at 17:46:39 (10 s into the hold).
- No alert during normal breathing (with 2 s confirmation there was a false hold alarm; 4 s removes it).

False-alarm sweep: no PANTING in any other recording (normal breathing, breath holds, arm waving).
`uv run pytest`: 152 passed.

Calibration recording `recordings/20261017-172315_panting_calib.parquet` (old placement): panting at
92 to 103/min detected for 12 s at 35 to 46 s; set the detector thresholds. Both recordings are local only
(`recordings/` is gitignored).

## Known risks

- **Panting depends on placement and effort.** Gentle panting, or panting below 60/min, is missed. It may
  then be read as a breath hold and ring the phone as `breath_hold` instead.
- **Right after panting** people often pause or breathe slowly; the model can call that a hold. Breathe
  normally until the page is green before starting the hold.
- **A hold with movement in it** (shifting in the chair) can split into two `breath_hold` alerts.
- Thresholds come from one person on one day. Re-run a rehearsal if the person, room or placement changes.
- The backend and frontend were running as background tasks of a Claude Code session; restarting that
  session stops them. Use the commands above in normal terminals for the demo.

## Changed files (uncommitted)

| File | Change |
|---|---|
| `backend/panting.py` (new) | Panting detector `panting_rate(x, fs)` and its thresholds |
| `backend/live.py` | New `panting` status, checked before movement, confirmed after 2 updates |
| `backend/live_source.py` | `panting` maps to status `breathing`, reason `panting`, with the rate |
| `backend/main.py` | Ignores the model label while panting, so the rate rule drives the phone |
| `backend/services/alerts.py` | `HOLD_CRITICAL_S = 4.0` for model holds (other critical patterns stay at 2 s) |
| `frontend/app/ui/chair-monitor.tsx` | Red PANTING view with the rate; turns on the alarm styling |
| `tests/test_alerts.py`, `tests/test_server.py` | Timings updated for the 4 s hold confirmation |

**Do not edit `backend/breathing.py`, `backend/classifier.py` or `backend/csi_format.py`.** The model stores
their SHA-256 and refuses to load if they change, which stops the live backend at startup. That is why the
detector is in its own file.

## Next steps

1. Live end-to-end check with the final code: run the demo order above while watching the page and phone.
2. If panting is missed live: check placement first, then pant faster or bigger. Only then consider
   lowering `CONC_MIN`/`AGREE_MIN` in `backend/panting.py`. Lowering `MIN_BPM` to 50 was tried and caused
   false PANTING during a hold with movement.
3. Commit the changes once the live check passes.
