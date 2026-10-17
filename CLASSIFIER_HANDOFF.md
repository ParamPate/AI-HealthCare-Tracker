# Breathing classifier handoff

## What is complete

Implementation commit: `9e08655`. Trained model/report commit: `93bb1b4`.
Both were pushed to `origin/main` before this handoff was created.

- `backend/classifier.py`: train, JSON model loading, prediction, and validation.
- `models/breathing-v1.json`: portable logistic regression and its preprocessing.
- `models/breathing-v1.training.json`: training fit and reproducibility information.
- `models/validation-v1.json`: **pending**, with no independent accuracy metrics.
- Tests: **126 passed** on the development computer, including 18 classifier tests.

The first model uses participant P01/session S01: 137.115 seconds of breathing and
40.4 seconds of two observed breath holds. Its 119 overlapping training windows
contain 102 breathing windows and 17 hold windows. Training fit classified 101/102
breathing windows and 16/17 hold windows correctly. These are training results,
not independent accuracy estimates or 17 independent hold trials.

The current server still uses `LiveAnalyser` and its breathing rules. It does not
load the trained model. Live model integration, independent validation, dashboard
ML fields, and phone alarm integration are the remaining work.

## 1. Pull and smoke-test on the ESP computer

From the repository root, with Python 3.11+ and uv installed:

```bash
git pull origin main
uv sync
uv run pytest
uv run python -m backend.classifier predict --model models/breathing-v1.json --file recordings/20261017-013311_hold.parquet
```

The replay runs once as fast as it can compute, printing one JSON object for each
one-second update after the first ten seconds. There should be 168 objects, with
relative recording time `end_s`, `label`, `hold_score`, and `reason`. This smoke
check reuses training data; it is not a validation experiment.

`hold_score` is an uncalibrated logistic-model score. It is not CSI confidence,
a breathing rate, or a clinical-risk probability. Threshold is 0.5. The labels
are `breathing`, `breath_hold`, or `no_signal`; invalid input gets a null score
and an explanatory reason.

The artifact includes feature order, learned mean/scale, weights, preprocessing
settings, class mapping, raw/annotation hashes, source revision and dependency
versions. Its source revision was recorded from the clean implementation commit.
Loading checks preprocessing source hashes for `classifier.py`, `breathing.py`,
and `csi_format.py`. Use matching code; do not bypass that check after editing
these files. A pipeline change needs a regenerated bundle and renewed validation.
JSON loading does not execute pickle or serialized Python objects.

## 2. Collect independent validation data

Keep the original file and all P01 sessions in `train`. Use a genuinely different
participant, such as P02, for `validation`. Do not rename P01 to bypass the split
check. Use `test` for a further untouched participant when one is available.

Keep TX powered and RX connected by USB. Close `idf.py monitor` and other serial
readers, then run:

```bash
uv run python -m serial.tools.list_ports
uv run python -m backend.live --label P02_S01
```

Port selection is automatic. Add `--port COM4` only if the listed RX port is COM4.
The default baud is 921600. Press Enter at observed activity transitions and keep
notes identifying each mark. Ctrl+C saves the Parquet recording and its text log.
Record observed continuous breathing and marked voluntary holds, plus movement
and empty-chair trials. Use a new file after an RX restart or transmitter change.

Inspect the saved filename, then add labels using actual observed times. The
following example assumes continuous breathing from seconds 0 to 30:

```bash
uv run python -m backend.label show recordings/NEW_SESSION.parquet
uv run python -m backend.label add recordings/NEW_SESSION.parquet --participant P02 --session S01 --split validation --start 0 --end 30 --label breathing --note "Observer confirmed continuous breathing"
```

For later intervals in that file, reuse the metadata:

```bash
uv run python -m backend.label add recordings/NEW_SESSION.parquet --start 35 --end 55 --label breath_hold --note "Observed hold bounded by recorded Enter marks"
```

Replace these example intervals with the observed ones. Other permitted challenge
labels are `movement` and `empty_chair`. Use `uncertain` for transitions/ambiguous
intervals. `breathing` does not require a measured rate. Never derive ground-truth
labels from this model or the existing DSP detector's output.

Times are seconds from the first recorded device packet. Keep each raw file with
its `.labels.json` sidecar. New raw captures remain gitignored, so a git push does
not transfer them to another computer. Label files can be committed separately.

## 3. Run and review validation

```bash
uv run python -m backend.label check recordings
uv run python -m backend.classifier validate --data recordings --model models/breathing-v1.json --output models/validation-v1.json
```

The validator uses only `validation` files. It checks source hashes and rejects
training participants and copied training recordings, even if the original raw
training files are not on this computer. It never refits normalization or weights.

Review the report, not just the exit code:

- `pending`: no validation recordings; no accuracy claim is available.
- `incomplete_class_coverage` or `insufficient_usable_windows`: the dataset cannot
  assess both breathing and holds yet.
- `complete`: both binary classes supplied usable windows; this is not a claim
  that the model passed a clinical or product accuracy target.
- `window_metrics`: confusion counts, hold precision/recall and false hold fraction
  during breathing, using windows one second inside an observed interval.
- Each recording's `events`: detected and missed holds, false predicted episodes,
  and delay from observed onset to the first positive episode start. Chronological
  replay includes transition windows, so latency does not use label-interior-only
  windows. This is before alarm persistence/debouncing.
- `challenges`: false hold windows during observed movement and an empty chair,
  or `unavailable` when there are no usable examples. These classes were not
  learned by the binary classifier.
- Coverage counters: invalid windows plus eligible/scored windows by label. Missing
  or rejected input must not be silently treated as correctly classified breathing.

Review errors on validation data before selecting a different threshold. Keep the
final test participant untouched during threshold or feature selection. Version
any threshold/model change and regenerate its report; do not silently overwrite
the meaning of the original training results.

## 4. Integrate live predictions using the existing serial reader

The reusable Python interface is:

```python
from backend.classifier import load_model, predict_window

model = load_model("models/breathing-v1.json")
# packet_buffer contains the last 10 seconds of backend.serial_io.Sample objects.
result = predict_window(model, list(packet_buffer),
                        end_s=packet_buffer[-1].device_time_us / 1e6)
# {"label": "breathing" | "breath_hold" | "no_signal",
#  "hold_score": float | None, "reason": str | None}
```

Implementation rules for the next agent:

1. Extend the existing source processing thread in `backend/live_source.py`; keep
   one reader owning the RX port. Feed it the original `Sample` objects, including
   each packet's invalid-first-word flag. Do not feed the displayed filtered wave.
2. Maintain a ten-second packet deque and predict at most once per second of new
   device time. Clear it on device restart, transmitter/CSI-length/radio change,
   backward time, or a gap exceeding two seconds. Until a full window is present,
   publish no signal. Keep the existing host-time staleness/error checks too.
3. Reuse `predict_window` unchanged. It enforces packet coverage, finite int8 I/Q,
   consistent configuration, at least 200 packets, and usable subcarriers. The
   current bundle expects 384 CSI values and channel 11. The old training file did
   not save bandwidth/secondary-channel fields, so those are explicitly unknown.
4. Gate known movement using the existing movement detection and treat missing
   input as unavailable. Lack of a steady DSP breathing-rate estimate alone is
   not proof of missing radio signal; a valid quiet window can contain a hold.
   Empty-chair/presence handling must be established using the challenge trials
   before connecting predictions to alerts.
5. Add optional `ml_label`, `ml_hold_score`, and `ml_model_version` fields through
   FastAPI `/ws` and the frontend stream type. Preserve the existing waveform/rate
   contract. Show unavailable/movement states without a hold score, and identify
   the model as a prototype. Do not map `hold_score` into `csi_confidence`.
6. Add integration checks for duplicate updates, disconnects, movement, warmup,
   clock/radio changes, and replay/live preprocessing parity. Rehearse with the
   actual boards and in the presentation room.

## 5. Revisit the phone alarm after live validation

Once live predictions behave acceptably, map confirmed hold episodes into the
existing timed alert service. Preserve acknowledgement, one alert per episode,
recovery/rearming, and the no-signal/movement interruptions. Phone networking and
browser sound still need a physical check. Keep this step out of initial model
validation so a model score alone cannot fire an alarm.
