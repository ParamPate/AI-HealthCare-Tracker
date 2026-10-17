"""Label observed time ranges in closed CSI recordings for model training.

Run `python -m backend.label --help` for add, show, and dataset checks.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Literal

import numpy as np
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from backend.services.alerts import classify

LABELS = ("normal_breathing", "slow_breathing", "fast_breathing", "breath_hold",
          "movement", "empty_chair", "uncertain")
SPLITS = ("train", "validation", "test")


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_s: FiniteFloat = Field(ge=0)
    end_s: FiniteFloat = Field(gt=0)
    label: Literal["normal_breathing", "slow_breathing", "fast_breathing", "breath_hold",
                   "movement", "empty_chair", "uncertain"]
    reference_rr_bpm: FiniteFloat | None = Field(default=None, gt=0)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end_s <= self.start_s:
            raise ValueError("end must be later than start")
        if self.label.endswith("_breathing"):
            if self.reference_rr_bpm is None:
                raise ValueError("breathing labels need --reference-rr from an independent breath count or reference")
            pattern, _ = classify("breathing", self.reference_rr_bpm)
            expected = "normal_breathing" if pattern == "normal" else pattern
            if self.label != expected:
                raise ValueError(f"reference RR {self.reference_rr_bpm:g} belongs to {expected}")
        elif self.reference_rr_bpm is not None:
            raise ValueError("reference RR is only used for breathing rate labels")
        return self


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    recording_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    participant_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    split: Literal["train", "validation", "test"]
    time_basis: Literal["seconds_from_first_device_packet"] = "seconds_from_first_device_packet"
    duration_s: FiniteFloat = Field(gt=0)
    annotations: list[Annotation]

    @model_validator(mode="after")
    def validate_intervals(self):
        previous_end = 0.0
        for a in sorted(self.annotations, key=lambda a: a.start_s):
            if a.start_s < previous_end:
                raise ValueError("annotation ranges overlap")
            if a.end_s > self.duration_s:
                raise ValueError(f"annotation ends outside the recording ({self.duration_s:g} s)")
            previous_end = a.end_s
        return self


def sidecar(path):
    return path.with_suffix(".labels.json")


def fingerprint(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def timing(path):
    if path.suffix != ".parquet":
        raise ValueError("choose a closed .parquet CSI recording")
    recording = pq.ParquetFile(path)
    names = recording.schema_arrow.names
    columns = [name for name in ("device_time_us", "segment", "mac") if name in names]
    if "device_time_us" not in columns:
        raise ValueError("recording has no device_time_us column")
    table = recording.read(columns=columns)
    # shortcut: label one uninterrupted recording; record a new file after an RX restart.
    for name in ("segment", "mac"):
        if name in columns and len(table[name].unique()) > 1:
            raise ValueError(f"multiple {name} values: use an uninterrupted recording from one transmitter")
    t = table["device_time_us"].to_numpy().astype(float) / 1e6
    if len(t) < 2 or not np.isfinite(t).all() or np.any(np.diff(t) < 0) or t[-1] <= t[0]:
        raise ValueError("recording needs at least two packets with a continuous device clock")
    return t - t[0]


def load_labels(path):
    labels = Labels.model_validate_json(sidecar(path).read_text(encoding="utf-8"))
    if labels.recording_sha256 != fingerprint(path):
        raise ValueError(f"{path}: recording changed since labeling; labels cannot be reused")
    t = timing(path)
    if abs(labels.duration_s - t[-1]) > 1e-6:
        raise ValueError(f"{path}: duration does not match labels")
    validate_packet_coverage(t, labels.annotations)
    return labels


def validate_packet_coverage(t, annotations):
    for a in annotations:
        if a.label == "uncertain":
            continue
        left = max(0, int(np.searchsorted(t, a.start_s, side="right")) - 1)
        right = min(len(t) - 1, int(np.searchsorted(t, a.end_s, side="left")))
        inside = np.count_nonzero((t >= a.start_s) & (t < a.end_s))
        # A radio outage is missing input, not evidence of a breath hold.
        if inside < 2 or np.any(np.diff(t[left:right + 1]) > 2.0):
            raise ValueError("range lacks packet coverage or crosses a gap > 2 s; mark it uncertain")


def save_labels(path, labels):
    text = labels.model_dump_json(indent=2) + "\n"
    target = sidecar(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def add_label(path, annotation, participant=None, session=None, split=None):
    t = timing(path)
    if sidecar(path).exists():
        labels = load_labels(path)
        for field, value in (("participant_id", participant), ("session_id", session), ("split", split)):
            if value is not None and value != getattr(labels, field):
                raise ValueError(f"{field} differs from existing labels; review the sidecar before changing it")
    else:
        if not all((participant, session, split)):
            raise ValueError("first label needs --participant, --session, and --split")
        labels = Labels(recording_sha256=fingerprint(path), participant_id=participant,
                        session_id=session, split=split, duration_s=float(t[-1]), annotations=[])
    candidate = Labels.model_validate({**labels.model_dump(), "annotations":
                                       sorted([*labels.annotations, annotation], key=lambda a: a.start_s)})
    validate_packet_coverage(t, candidate.annotations)
    save_labels(path, candidate)
    return candidate


def check_dataset(root):
    files = sorted(root.rglob("*.labels.json"))
    if not files:
        raise ValueError("no .labels.json files found; record and label a session first")
    subjects, hashes, totals = {}, set(), defaultdict(Counter)
    for file in files:
        path = file.with_name(file.name.removesuffix(".labels.json") + ".parquet")
        labels = load_labels(path)
        if labels.recording_sha256 in hashes:
            raise ValueError(f"{path}: duplicate recording; copies must not enter different dataset splits")
        hashes.add(labels.recording_sha256)
        if subjects.setdefault(labels.participant_id, labels.split) != labels.split:
            raise ValueError(f"participant {labels.participant_id} appears in multiple splits")
        for a in labels.annotations:
            totals[labels.split][a.label] += a.end_s - a.start_s
    return {"recordings": len(files), "participants": len(subjects),
            "labeled_seconds": dict(totals),
            "missing_splits": [split for split in SPLITS if split not in subjects.values()]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="add an observed interval to a recording")
    add.add_argument("recording", type=Path)
    add.add_argument("--participant", help="anonymous ID, e.g. P01 (required for the first label)")
    add.add_argument("--session", help="session ID, e.g. S01 (required for the first label)")
    add.add_argument("--split", choices=SPLITS)
    add.add_argument("--start", type=float, required=True, help="seconds from the first recorded packet")
    add.add_argument("--end", type=float, required=True)
    add.add_argument("--label", choices=LABELS, required=True)
    add.add_argument("--reference-rr", type=float, help="independently measured breaths/min; never the CSI estimate")
    add.add_argument("--note", default="", help="observations/reference method; no identifying patient details")
    show = commands.add_parser("show", help="show duration and existing annotations")
    show.add_argument("recording", type=Path)
    check = commands.add_parser("check", help="validate all labels and participant splits before training")
    check.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            print(json.dumps(check_dataset(args.directory), indent=2))
        elif args.command == "show":
            t = timing(args.recording)
            print(f"{args.recording.name}: {len(t)} packets, label range 0 to {t[-1]:.3f} seconds")
            print(load_labels(args.recording).model_dump_json(indent=2) if sidecar(args.recording).exists()
                  else "No labels yet. Unlabeled time is excluded from training.")
        else:
            annotation = Annotation(start_s=args.start, end_s=args.end, label=args.label,
                                    reference_rr_bpm=args.reference_rr, note=args.note)
            add_label(args.recording, annotation, args.participant, args.session, args.split)
            print(f"Saved {sidecar(args.recording)}; run `python -m backend.label check recordings` before training.")
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
