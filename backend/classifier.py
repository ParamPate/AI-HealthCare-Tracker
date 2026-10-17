"""Offline binary CSI prototype: train, predict, and independently validate.

    python -m backend.classifier train --data recordings --output models/breathing-v1.json
    python -m backend.classifier predict --model models/breathing-v1.json --file FILE.parquet
    python -m backend.classifier validate --data recordings --model models/breathing-v1.json --output REPORT.json
"""
import argparse
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Literal

import numpy as np
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator
from scipy import optimize, signal, special

from backend import breathing
from backend.csi_format import CsiPacket, amplitudes
from backend.label import check_dataset, fingerprint, load_labels, sidecar
from backend.serial_io import Sample

ROOT = Path(__file__).resolve().parent.parent
CLASSES = ["breathing", "breath_hold"]
FEATURES = ["log_variance", "log_breathing_power", "log_movement_power",
            "breathing_power_fraction", "spectral_peak_concentration"]
CONFIG = {"window_s": 10.0, "step_s": 1.0, "label_margin_s": 1.0, "fs_hz": 20.0,
          "max_packet_gap_s": 2.0, "edge_tolerance_s": 0.1, "min_packets": 200,
          "min_subcarriers": 4, "breathing_band_hz": [0.05, 0.5], "movement_band_hz": [1.0, 5.0],
          "total_band_hz": [0.05, 5.0], "periodogram_nfft": 256, "epsilon": 1e-12,
          "detrend": "linear", "periodogram_window": "hann", "spike_filter_packets": 5,
          "null_carrier_fraction": 0.1, "gain_normalization": "packet_mean"}
RATE_LABELS = {"breathing", "normal_breathing", "slow_breathing", "fast_breathing"}
L2 = 0.1


class InvalidWindow(ValueError):
    """Input cannot support a prediction; never translate this into a breath hold."""


def source_hashes():
    return {name: fingerprint(ROOT / name) for name in
            ("backend/classifier.py", "backend/breathing.py", "backend/csi_format.py")}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    pipeline_version: Literal["csi-window-v1"] = "csi-window-v1"
    status: Literal["prototype; independent validation pending"] = "prototype; independent validation pending"
    classes: list[str]
    feature_order: list[str]
    preprocessing: dict
    feature_mean: list[FiniteFloat]
    feature_scale: list[FiniteFloat]
    coefficients: list[FiniteFloat]
    intercept: FiniteFloat
    threshold: FiniteFloat = Field(default=0.5, gt=0, lt=1)
    training: dict

    @model_validator(mode="after")
    def compatible(self):
        if self.classes != CLASSES or self.feature_order != FEATURES or self.preprocessing != CONFIG:
            raise ValueError("unsupported model preprocessing or feature order")
        if any(len(values) != len(FEATURES) for values in
               (self.feature_mean, self.feature_scale, self.coefficients)) or min(self.feature_scale) <= 0:
            raise ValueError("model feature dimensions/scales are invalid")
        if self.training.get("preprocessing_source_sha256") != source_hashes():
            raise ValueError("preprocessing source differs from the saved model; use its matching code revision")
        sources = self.training.get("recordings", [])
        if not sources or any(not all(s.get(key) for key in
                                     ("participant_id", "recording_sha256", "annotation_sha256"))
                              or s.get("split") != "train" for s in sources):
            raise ValueError("model is missing training provenance")
        signatures = self.training.get("radio_signatures")
        if not isinstance(signatures, list) or not signatures:
            raise ValueError("model is missing radio configuration")
        for signature in signatures:
            if (not isinstance(signature, dict)
                    or set(signature) != {"csi_values", "channel", "bandwidth", "secondary_channel"}
                    or not isinstance(signature["csi_values"], int) or signature["csi_values"] < 12
                    or signature["csi_values"] % 2 or not isinstance(signature["channel"], int)
                    or not 1 <= signature["channel"] <= 14 or signature["bandwidth"] not in (None, 0, 1)
                    or signature["secondary_channel"] not in (None, 0, 1, 2)):
                raise ValueError("model has invalid radio configuration")
        return self


def save_json(path, data):
    """Atomic replacement prevents an interrupted save from corrupting an existing bundle."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_model(path):
    return Model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def binary_label(label):
    return "breathing" if label in RATE_LABELS else "breath_hold" if label == "breath_hold" else None


def radio_signature(packets):
    for name in ("mac", "channel", "bandwidth", "secondary_channel"):
        if len({getattr(p, name) for p in packets}) != 1:
            raise InvalidWindow(f"mixed radio configuration: {name}")
    lengths = {len(p.csi) for p in packets}
    if len(lengths) != 1:
        raise InvalidWindow("mixed CSI lengths")
    p = packets[0]
    if not 1 <= p.channel <= 14 or p.bandwidth not in (-1, 0, 1) or p.secondary_channel not in (-1, 0, 1, 2):
        raise InvalidWindow("invalid radio configuration")
    # Old Parquet files did not store these fields; -1 preserves unknown instead of guessing.
    return {"csi_values": len(p.csi), "channel": p.channel,
            "bandwidth": None if p.bandwidth == -1 else p.bandwidth,
            "secondary_channel": None if p.secondary_channel == -1 else p.secondary_channel}


def extract_features(samples, end_s=None):
    """One trailing window of serial_io.Sample; device seconds, no future context."""
    if len(samples) < CONFIG["min_packets"]:
        raise InvalidWindow("incomplete window: insufficient packets")
    packets = [s.packet for s in samples]
    signature = radio_signature(packets)
    if len({s.segment for s in samples}) != 1:
        raise InvalidWindow("clock segment changed")
    t = np.asarray([s.device_time_us / 1e6 for s in samples], dtype=float)
    if not np.isfinite(t).all() or np.any(np.diff(t) <= 0):
        raise InvalidWindow("device timestamps must be finite and strictly increasing")
    end_s = t[-1] if end_s is None else float(end_s)
    start_s = end_s - CONFIG["window_s"]
    tolerance = CONFIG["edge_tolerance_s"]
    if (not np.isfinite(end_s) or t[0] < start_s - 1e-6 or t[-1] > end_s + 1e-6
            or t[0] > start_s + tolerance or t[-1] < end_s - tolerance):
        raise InvalidWindow("incomplete window or packets outside the trailing window")
    if np.diff(t).max() > CONFIG["max_packet_gap_s"]:
        raise InvalidWindow("packet gap exceeds two seconds")
    try:
        iq = np.asarray([p.csi for p in packets], dtype=float)
    except (TypeError, ValueError) as error:
        raise InvalidWindow("invalid CSI matrix") from error
    if (iq.ndim != 2 or iq.shape[1] % 2 or iq.shape[1] < 12 or not np.isfinite(iq).all()
            or np.any(iq < -128) or np.any(iq > 127) or np.any(iq != np.rint(iq))):
        raise InvalidWindow("CSI must contain finite interleaved int8 imaginary/real values")
    if any(p.first_word_invalid not in (False, True) for p in packets):
        raise InvalidWindow("invalid first-word flag")
    amp = amplitudes(iq, first_word_invalid=False)
    invalid = np.asarray([p.first_word_invalid for p in packets], dtype=bool)
    amp[invalid, :2] = 0
    if np.any(amp.mean(axis=1) <= 0):
        raise InvalidWindow("no usable signal")
    with np.errstate(divide="raise", invalid="raise", over="raise"):
        try:
            _, x, kept = breathing.prepare(t - t[0], amp, fs=CONFIG["fs_hz"])
        except FloatingPointError as error:
            raise InvalidWindow("no usable subcarrier signal") from error
    if len(kept) < CONFIG["min_subcarriers"] or not np.isfinite(x).all():
        raise InvalidWindow("too few usable subcarriers")
    x = signal.detrend(x, type=CONFIG["detrend"], axis=0)
    f, power = signal.periodogram(x, fs=CONFIG["fs_hz"], window=CONFIG["periodogram_window"],
                                  nfft=CONFIG["periodogram_nfft"], detrend=False, axis=0)
    df = f[1] - f[0]
    band = (f >= CONFIG["breathing_band_hz"][0]) & (f <= CONFIG["breathing_band_hz"][1])
    movement = (f >= CONFIG["movement_band_hz"][0]) & (f <= CONFIG["movement_band_hz"][1])
    total = (f >= CONFIG["total_band_hz"][0]) & (f <= CONFIG["total_band_hz"][1])
    bp, mp, total_power = (power[mask].sum(axis=0) * df for mask in (band, movement, total))
    eps = CONFIG["epsilon"]
    features = np.asarray([np.log10(np.median(x.var(axis=0)) + eps), np.log10(np.median(bp) + eps),
                           np.log10(np.median(mp) + eps), np.median(bp / (total_power + eps)),
                           np.median(power[band].max(axis=0) * df / (bp + eps))])
    if not np.isfinite(features).all():
        raise InvalidWindow("non-finite features")
    return features, signature


def read_recording(path):
    rows = pq.read_table(path).to_pylist()
    required = {"device_time_us", "segment", "mac", "channel", "seq", "timestamp_us", "rssi",
                "noise_floor", "first_word_invalid", "csi", "host_time"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"{path}: not a complete CSI recording")
    samples = []
    for row in rows:
        p = CsiPacket(mac=row["mac"], seq=row["seq"], rssi=row["rssi"], noise_floor=row["noise_floor"],
                      bandwidth=row.get("bandwidth", -1), channel=row["channel"],
                      secondary_channel=row.get("secondary_channel", -1), timestamp_us=row["timestamp_us"],
                      first_word_invalid=row["first_word_invalid"], csi=np.asarray(row["csi"]))
        samples.append(Sample(row["host_time"], row["device_time_us"], row["segment"], p))
    return samples


def windows(samples):
    times = np.asarray([s.device_time_us / 1e6 for s in samples])
    if len(times) < 2 or not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("recording needs strictly increasing device times")
    origin = times[0]
    for relative_end in np.arange(CONFIG["window_s"], times[-1] - origin + 1e-6, CONFIG["step_s"]):
        end = origin + relative_end
        left = np.searchsorted(times, end - CONFIG["window_s"], side="left")
        right = np.searchsorted(times, end, side="right")
        yield float(relative_end), samples[left:right], float(end)


def interior_annotation(annotations, end):
    start, margin = end - CONFIG["window_s"], CONFIG["label_margin_s"]
    return next((a for a in annotations if start >= a.start_s + margin and end <= a.end_s - margin), None)


def inventory(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"dataset directory does not exist: {root}")
    files = sorted(root.rglob("*.labels.json"))
    if not files:
        return []
    check_dataset(root)
    return [(file.with_name(file.name.removesuffix(".labels.json") + ".parquet"),
             load_labels(file.with_name(file.name.removesuffix(".labels.json") + ".parquet")))
            for file in files]


def provenance(path, labels):
    return {"file": path.name, "participant_id": labels.participant_id, "session_id": labels.session_id,
            "split": labels.split, "recording_sha256": labels.recording_sha256,
            "annotation_sha256": fingerprint(sidecar(path))}


def fit(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=int)
    if x.ndim != 2 or x.shape[1] != len(FEATURES) or not np.isfinite(x).all() or set(y) != {0, 1} or len(x) != len(y):
        raise ValueError("training needs finite features and examples of both classes")
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-12] = 1.0
    z = (x - mean) / scale
    sample_weight = np.asarray([1 / (2 * np.count_nonzero(y == value)) for value in y])

    def objective(theta):
        scores = z @ theta[:-1] + theta[-1]
        loss = np.sum(sample_weight * (np.logaddexp(0, scores) - y * scores)) + L2 / 2 * np.dot(theta[:-1], theta[:-1])
        residual = sample_weight * (special.expit(scores) - y)
        gradient = np.r_[z.T @ residual + L2 * theta[:-1], residual.sum()]
        return loss, gradient

    result = optimize.minimize(objective, np.zeros(len(FEATURES) + 1), method="L-BFGS-B", jac=True,
                               options={"maxiter": 1000, "ftol": 1e-12, "gtol": 1e-9})
    if not result.success or not np.isfinite(result.x).all():
        raise ValueError(f"classifier optimization failed: {result.message}")
    return mean, scale, result.x[:-1], float(result.x[-1])


def window_metrics(truth, predicted):
    truth, predicted = np.asarray(truth, dtype=int), np.asarray(predicted, dtype=int)
    if len(truth) != len(predicted) or not set(truth).issubset({0, 1}) or not set(predicted).issubset({0, 1}):
        raise ValueError("metrics require matching binary labels")
    tn, fp, fn, tp = (int(np.count_nonzero((truth == a) & (predicted == b)))
                      for a, b in ((0, 0), (0, 1), (1, 0), (1, 1)))
    return {"windows": len(truth), "confusion": {"breathing_as_breathing": tn, "breathing_as_hold": fp,
            "hold_as_breathing": fn, "hold_as_hold": tp}, "hold_precision": tp / (tp + fp) if tp + fp else None,
            "hold_recall": tp / (tp + fn) if tp + fn else None,
            "false_hold_fraction_during_breathing": fp / (tn + fp) if tn + fp else None}


def feature_scores(model, x):
    x = np.asarray(x, dtype=float)
    if x.ndim != 2 or x.shape[1] != len(FEATURES) or not np.isfinite(x).all():
        raise InvalidWindow("invalid feature matrix")
    with np.errstate(over="raise", invalid="raise", divide="raise"):
        return special.expit(((x - model.feature_mean) / model.feature_scale) @ model.coefficients + model.intercept)


def predict_window(model, samples, end_s=None):
    """Return label and uncalibrated P(hold) score, or no_signal with a null score."""
    try:
        features, signature = extract_features(samples, end_s)
        signatures = model.training["radio_signatures"]
        if not any(all(expected[k] is None or expected[k] == signature[k] for k in expected)
                   for expected in signatures):
            raise InvalidWindow("radio configuration differs from training")
        score = float(feature_scores(model, features[None, :])[0])
    except (ValueError, TypeError, FloatingPointError) as error:
        return {"label": "no_signal", "hold_score": None, "reason": str(error)}
    return {"label": CLASSES[int(score >= model.threshold)], "hold_score": score, "reason": None}


def train(root):
    examples, targets, sources, signatures, rejected = [], [], [], [], Counter()
    for path, labels in inventory(root):
        if labels.split != "train":
            continue
        samples = read_recording(path)
        # Reject mixed configurations across a recording, even when a window misses the transition.
        signature = radio_signature([s.packet for s in samples])
        if signature not in signatures:
            signatures.append(signature)
        count = 0
        for end, batch, absolute_end in windows(samples):
            annotation = interior_annotation(labels.annotations, end)
            target = binary_label(annotation.label) if annotation else None
            if target is None:
                continue
            try:
                features, _ = extract_features(batch, absolute_end)
            except InvalidWindow as error:
                rejected[str(error)] += 1
                continue
            examples.append(features)
            targets.append(CLASSES.index(target))
            count += 1
        sources.append({**provenance(path, labels), "training_windows": count})
    if not examples:
        raise ValueError("no usable training windows")
    x, y = np.asarray(examples), np.asarray(targets)
    mean, scale, coefficients, intercept = fit(x, y)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    training = {"recordings": sources, "radio_signatures": signatures,
                "source_revision": revision.stdout.strip() or None, "source_dirty": bool(dirty.stdout.strip()),
                "preprocessing_source_sha256": source_hashes(),
                "dependencies": {name: version(name) for name in ("numpy", "scipy", "pyarrow", "pydantic")},
                "python": platform.python_version(), "class_counts": dict(Counter(CLASSES[i] for i in targets)),
                "rejected_windows": dict(rejected), "optimizer": {"method": "L-BFGS-B", "l2": L2,
                "class_weight": "balanced", "converged": True}}
    model = Model(classes=CLASSES, feature_order=FEATURES, preprocessing=CONFIG, feature_mean=mean.tolist(),
                  feature_scale=scale.tolist(), coefficients=coefficients.tolist(), intercept=intercept,
                  training=training)
    report = {"evaluation": "training_fit_only", "status": model.status,
              "note": "Overlapping windows from one training dataset are not independent validation.",
              "training": training, "window_metrics": window_metrics(y, feature_scores(model, x) >= model.threshold)}
    return model, report


def event_metrics(predictions, annotations):
    """Episodes start on the first positive window; invalid/missing updates break continuity."""
    holds = [a for a in annotations if a.label == "breath_hold"]
    matched, delays, false_starts = set(), [], []
    previous_end, previous_label = None, None
    for end, label in predictions:
        continuous = previous_end is not None and 0 < end - previous_end <= CONFIG["step_s"] * 1.5
        if label == "breath_hold" and (not continuous or previous_label != "breath_hold"):
            match = next((i for i, a in enumerate(holds) if a.start_s <= end < a.end_s), None)
            if match is None:
                # Unlabeled/uncertain time cannot establish a false detection.
                if any(a.start_s <= end < a.end_s and a.label != "uncertain" for a in annotations):
                    false_starts.append(end)
            elif match in matched:
                false_starts.append(end)
            else:
                matched.add(match)
                delays.append({"hold_start_s": holds[match].start_s, "first_detection_s": end,
                               "delay_s": end - holds[match].start_s})
        previous_end, previous_label = end, label
    return {"annotated_holds": len(holds), "detected_holds": len(matched), "missed_holds": len(holds) - len(matched),
            "false_hold_episodes": len(false_starts), "false_episode_starts_s": false_starts, "detections": delays}


def validate(model, root):
    entries = inventory(root)
    selected = [(p, labels) for p, labels in entries if labels.split == "validation"]
    if not selected:
        return {"evaluation": "independent_validation", "status": "pending",
                "reason": "No labeled validation recordings. Training data is not reused for validation.",
                "window_metrics": None, "recordings": [],
                "challenges": {name: {"status": "unavailable"} for name in ("movement", "empty_chair")}}
    training = model.training["recordings"]
    participants = {s["participant_id"] for s in training}
    hashes = {s["recording_sha256"] for s in training}
    truth, predicted, records = [], [], []
    challenges = {name: [] for name in ("movement", "empty_chair")}
    for path, labels in selected:
        if labels.participant_id in participants or labels.recording_sha256 in hashes:
            raise ValueError(f"{path}: validation overlaps training participant or recording")
        samples = read_recording(path)
        radio_signature([s.packet for s in samples])
        timeline, invalid, eligible, used = [], 0, Counter(), Counter()
        for end, batch, absolute_end in windows(samples):
            result = predict_window(model, batch, absolute_end)
            timeline.append((end, result["label"]))
            invalid += result["label"] == "no_signal"
            annotation = interior_annotation(labels.annotations, end)
            if annotation is None:
                continue
            target = binary_label(annotation.label)
            eligible[annotation.label] += 1
            if result["label"] == "no_signal":
                continue
            used[annotation.label] += 1
            if target is not None:
                truth.append(CLASSES.index(target))
                predicted.append(CLASSES.index(result["label"]))
            elif annotation.label in challenges:
                challenges[annotation.label].append(result["label"] == "breath_hold")
        records.append({**provenance(path, labels), "invalid_windows": invalid,
                        "eligible_windows_by_label": dict(eligible), "scored_windows_by_label": dict(used),
                        "events": event_metrics(timeline, labels.annotations)})
    missing = [CLASSES[i] for i in range(2) if i not in truth]
    status = "complete" if not missing else "incomplete_class_coverage" if truth else "insufficient_usable_windows"
    return {"evaluation": "independent_validation", "status": status, "missing_binary_classes": missing,
            "threshold": model.threshold, "window_metrics": window_metrics(truth, predicted) if truth else None,
            "recordings": records, "challenges": {name: {"status": "measured", "windows": len(values),
            "false_hold_windows": sum(values), "false_hold_fraction": sum(values) / len(values)} if values else
            {"status": "unavailable"} for name, values in challenges.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--data", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    validation = commands.add_parser("validate")
    validation.add_argument("--data", type=Path, required=True)
    validation.add_argument("--model", type=Path, required=True)
    validation.add_argument("--output", type=Path, required=True)
    prediction = commands.add_parser("predict", help="replay once, printing chronological JSONL predictions")
    prediction.add_argument("--model", type=Path, required=True)
    prediction.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "train":
            model, report = train(args.data)
            save_json(args.output, model.model_dump())
            report_path = args.output.with_suffix(".training.json")
            report.update(model_file=args.output.name, model_sha256=fingerprint(args.output))
            save_json(report_path, report)
            print(json.dumps({"model": str(args.output), "training_report": str(report_path),
                              "status": model.status, "training_window_metrics": report["window_metrics"]}, indent=2))
        elif args.command == "validate":
            model = load_model(args.model)
            report = {"model_sha256": fingerprint(args.model), **validate(model, args.data)}
            save_json(args.output, report)
            print(json.dumps(report, indent=2))
        else:
            model = load_model(args.model)
            samples = read_recording(args.file)
            radio_signature([s.packet for s in samples])
            for end, batch, absolute_end in windows(samples):
                print(json.dumps({"end_s": end, **predict_window(model, batch, absolute_end)}, allow_nan=False))
    except (ValueError, OSError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
