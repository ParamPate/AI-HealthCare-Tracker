import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.label import Annotation, add_label, check_dataset, load_labels, main, sidecar, timing


def recording(tmp_path, name="session", t=None, segment=None):
    t = np.arange(0, 61, 0.1) if t is None else np.asarray(t)
    path = tmp_path / f"{name}.parquet"
    pq.write_table(pa.table({"device_time_us": np.rint((100 + t) * 1e6).astype(np.int64),
                            "segment": [0] * len(t) if segment is None else segment,
                            "mac": ["tx"] * len(t)}), path)
    return path


def label(start=5, end=35, kind="normal_breathing", rr=16):
    return Annotation(start_s=start, end_s=end, label=kind, reference_rr_bpm=rr)


def test_cli_saves_independent_labels_and_shows_unlabeled_time(tmp_path, capsys):
    path = recording(tmp_path)
    main(["show", str(path)])
    assert "No labels yet" in capsys.readouterr().out
    main(["add", str(path), "--participant", "P01", "--session", "S01", "--split", "train",
          "--start", "5", "--end", "35", "--label", "normal_breathing", "--reference-rr", "16",
          "--note", "Observer counted 8 breaths in these 30 seconds"])
    labels = load_labels(path)
    assert labels.participant_id == "P01" and labels.session_id == "S01"
    assert labels.annotations[0].reference_rr_bpm == 16
    assert labels.time_basis == "seconds_from_first_device_packet"
    assert labels.duration_s == pytest.approx(60.9)
    assert timing(path)[0] == 0
    main(["check", str(tmp_path)])
    output = capsys.readouterr().out
    assert '"normal_breathing": 30.0' in output and '"validation"' in output
    main(["show", str(path)])
    assert "Observer counted" in capsys.readouterr().out


@pytest.mark.parametrize("start,end,kind,rr", [
    (10, 5, "movement", None), (-1, 5, "movement", None),
    (0, float("nan"), "movement", None), (0, 5, "apnea", None),
    (0, 5, "normal_breathing", None), (0, 5, "fast_breathing", 15),
    (0, 5, "normal_breathing", 30), (0, 5, "slow_breathing", -1),
    (0, 5, "movement", 15),
])
def test_rejects_unusable_or_unsubstantiated_labels(start, end, kind, rr):
    with pytest.raises(ValueError):
        label(start, end, kind, rr)


def test_overlap_out_of_range_and_metadata_changes_preserve_existing_file(tmp_path):
    path = recording(tmp_path)
    add_label(path, label(), "P01", "S01", "train")
    before = sidecar(path).read_bytes()
    for interval, metadata in ((label(20, 40), {}), (label(40, 90), {}),
                               (label(35, 45), {"participant": "P02"}),
                               (label(35, 45), {"split": "test"})):
        with pytest.raises(ValueError):
            add_label(path, interval, **metadata)
        assert sidecar(path).read_bytes() == before
    add_label(path, label(35, 45, "movement", None))  # touching endpoints are allowed
    assert len(load_labels(path).annotations) == 2


def test_missing_metadata_and_changed_recording_are_rejected(tmp_path):
    path = recording(tmp_path)
    with pytest.raises(ValueError, match="first label"):
        add_label(path, label())
    add_label(path, label(), "P01", "S01", "train")
    recording(tmp_path, t=np.arange(0, 50, 0.1))
    with pytest.raises(ValueError, match="changed since labeling"):
        load_labels(path)


def test_gaps_cannot_be_labeled_as_breath_holds(tmp_path):
    path = recording(tmp_path, t=[0, 1, 2, 3, 10, 11, 12, 13])
    for start, end in ((1, 12), (5, 6)):
        with pytest.raises(ValueError, match="packet coverage"):
            add_label(path, label(start, end, "breath_hold", None), "P01", "S01", "train")
        assert not sidecar(path).exists()
    add_label(path, label(3, 10, "uncertain", None), "P01", "S01", "train")
    assert load_labels(path).annotations[0].label == "uncertain"


def test_restart_and_clock_disorder_are_rejected(tmp_path):
    path = recording(tmp_path, t=[0, 1, 0, 1], segment=[0, 0, 1, 1])
    with pytest.raises(ValueError, match="multiple segment"):
        timing(path)
    path = recording(tmp_path, t=[0, 2, 1, 3])
    with pytest.raises(ValueError, match="continuous device clock"):
        timing(path)


def test_same_participant_cannot_leak_between_train_and_validation(tmp_path):
    one, two = recording(tmp_path, "one"), recording(tmp_path, "two", t=np.arange(0, 61, 0.2))
    add_label(one, label(), "P01", "S01", "train")
    add_label(two, label(), "P01", "S02", "validation")
    with pytest.raises(ValueError, match="participant P01 appears in multiple splits"):
        check_dataset(tmp_path)


def test_copied_recording_cannot_enter_dataset_twice(tmp_path):
    one, two = recording(tmp_path, "one"), tmp_path / "two.parquet"
    two.write_bytes(one.read_bytes())
    add_label(one, label(), "P01", "S01", "train")
    add_label(two, label(), "P02", "S02", "validation")
    with pytest.raises(ValueError, match="duplicate recording"):
        check_dataset(tmp_path)


def test_hand_edited_labels_still_get_validated(tmp_path):
    path = recording(tmp_path)
    add_label(path, label(), "P01", "S01", "train")
    data = json.loads(sidecar(path).read_text())
    data["annotations"][0]["end_s"] = 100
    sidecar(path).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="outside the recording"):
        check_dataset(tmp_path)


def test_check_empty_directory_reports_missing_data(tmp_path):
    with pytest.raises(ValueError, match="no .labels.json"):
        check_dataset(tmp_path)


def test_observed_breathing_needs_no_rate_and_can_complete_binary_timeline(tmp_path):
    path = recording(tmp_path)
    main(["add", str(path), "--participant", "P01", "--session", "S01", "--split", "train",
          "--start", "0", "--end", "20", "--label", "breathing",
          "--note", "Participant confirmed continuous breathing"])
    add_label(path, label(20, 40, "breath_hold", None))
    end = float(timing(path)[-1])
    add_label(path, label(40, end, "breathing", None))
    labels = load_labels(path)
    assert [a.label for a in labels.annotations] == ["breathing", "breath_hold", "breathing"]
    assert all(a.reference_rr_bpm is None for a in labels.annotations)
    totals = check_dataset(tmp_path)["labeled_seconds"]["train"]
    assert totals["breathing"] == pytest.approx(end - 20)
    assert totals["breath_hold"] == 20
    assert sum(totals.values()) == pytest.approx(end)


def test_generic_breathing_accepts_an_optional_independent_rate():
    assert label(kind="breathing", rr=16).reference_rr_bpm == 16
