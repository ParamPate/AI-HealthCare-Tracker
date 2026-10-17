from copy import deepcopy
from dataclasses import replace
import json

import numpy as np
import pyarrow.parquet as pq
import pytest

from backend.classifier import (CLASSES, CONFIG, FEATURES, InvalidWindow, Model, binary_label,
                                event_metrics, extract_features, feature_scores, fit, interior_annotation,
                                load_model, main, predict_window, read_recording, save_json, train,
                                validate, window_metrics, windows)
from backend.csi_format import CsiPacket
from backend.label import Annotation, Labels, fingerprint, save_labels
from backend.record import to_table
from backend.serial_io import Sample


def samples(duration=71, rate=40, seed=7, channel=11):
    rng = np.random.default_rng(seed)
    result = []
    spatial = np.linspace(-1, 1, 16)
    for i, t in enumerate(np.arange(0, duration, 1 / rate)):
        active = not 20 <= t < 40
        wave = 6 * np.sin(2 * np.pi * 0.25 * t) if active else 0
        real = np.rint(45 + spatial * wave + rng.normal(0, 0.6, 16)).astype(np.int8)
        iq = np.zeros(32, dtype=np.int8)
        iq[0::2], iq[1::2] = 20, real
        packet = CsiPacket("1a:00:00:00:00:00", i, -60, -97, 0, channel, 0,
                           int((100 + t) * 1e6), False, iq)
        result.append(Sample(1000 + t, int((100 + t) * 1e6), 0, packet))
    return result


def recording(root, name="one", split="train", participant="P01", seed=7):
    path = root / f"{name}.parquet"
    packets = samples(seed=seed)
    pq.write_table(to_table(packets), path)
    duration = (packets[-1].device_time_us - packets[0].device_time_us) / 1e6
    labels = Labels(recording_sha256=fingerprint(path), participant_id=participant, session_id=name,
                    split=split, duration_s=duration, annotations=[
                        Annotation(start_s=0, end_s=20, label="breathing"),
                        Annotation(start_s=20, end_s=40, label="breath_hold"),
                        Annotation(start_s=40, end_s=duration, label="breathing")])
    save_labels(path, labels)
    return path, labels


@pytest.fixture
def fitted(tmp_path):
    path, labels = recording(tmp_path)
    model, report = train(tmp_path)
    return model, report, path, labels


def test_windows_respect_label_boundaries_and_margin():
    annotations = [Annotation(start_s=0, end_s=20, label="breathing"),
                   Annotation(start_s=20, end_s=40, label="breath_hold")]
    assert interior_annotation(annotations, 10) is None
    assert interior_annotation(annotations, 11).label == "breathing"
    assert interior_annotation(annotations, 19).label == "breathing"
    assert interior_annotation(annotations, 20) is None
    assert interior_annotation(annotations, 25) is None
    assert interior_annotation(annotations, 30) is None
    assert interior_annotation(annotations, 31).label == "breath_hold"
    assert interior_annotation(annotations, 40) is None
    for end, batch, absolute_end in windows(samples(duration=42)):
        annotation = interior_annotation(annotations, end)
        if annotation is not None:
            assert end - 10 >= annotation.start_s + 1
            assert end <= annotation.end_s - 1
        assert max(s.device_time_us / 1e6 for s in batch) <= absolute_end


def test_features_use_raw_iq_flags_and_only_the_supplied_window():
    batch = samples(duration=10.025)
    features, signature = extract_features(batch)
    assert features.shape == (len(FEATURES),) and np.isfinite(features).all()
    assert signature["channel"] == 11
    flagged = [replace(s, packet=replace(s.packet, first_word_invalid=True)) for s in batch]
    corrupted = []
    for i, sample in enumerate(flagged):
        iq = sample.packet.csi.copy()
        iq[:4] = 127 if i % 2 else -128
        corrupted.append(replace(sample, packet=replace(sample.packet, csi=iq)))
    np.testing.assert_array_equal(extract_features(flagged)[0], extract_features(corrupted)[0])
    # A future posture shift cannot affect features for an earlier window.
    full = samples(duration=12)
    early = list(windows(full))[0]
    future_changed = [replace(s, packet=replace(s.packet, csi=np.full(32, 127, dtype=np.int8)))
                      if s.device_time_us > 110_000_000 else s for s in full]
    changed = list(windows(future_changed))[0]
    np.testing.assert_array_equal(extract_features(early[1], early[2])[0],
                                  extract_features(changed[1], changed[2])[0])


def test_invalid_input_is_rejected_instead_of_classified_as_hold(fitted):
    model = fitted[0]
    normal = samples(duration=10.025)
    invalid = [normal[:20], normal[:-20], normal + [normal[-1]],
               [replace(s, packet=replace(s.packet, csi=np.zeros(32))) for s in normal]]
    for field, value in (("channel", 6), ("bandwidth", 1), ("mac", "other")):
        altered = normal.copy()
        altered[-1] = replace(altered[-1], packet=replace(altered[-1].packet, **{field: value}))
        invalid.append(altered)
    altered = normal.copy()
    altered[-1] = replace(altered[-1], segment=1)
    invalid.append(altered)
    altered = normal.copy()
    altered[20] = replace(altered[20], packet=replace(altered[20].packet, csi=np.full(32, np.nan)))
    invalid.append(altered)
    invalid.append([s for s in normal if not 103 < s.device_time_us / 1e6 < 106])
    for batch in invalid:
        result = predict_window(model, batch)
        assert result["label"] == "no_signal" and result["hold_score"] is None, result
    assert predict_window(model, samples(duration=10.025, channel=6))["label"] == "no_signal"


def test_save_load_and_retraining_preserve_predictions(fitted, tmp_path):
    model, report, path, _ = fitted
    destination = tmp_path / "bundle.json"
    save_json(destination, model.model_dump())
    loaded = load_model(destination)
    assert loaded.preprocessing == CONFIG and loaded.feature_order == FEATURES
    batch = next(windows(read_recording(path)))
    assert predict_window(loaded, batch[1], batch[2]) == predict_window(model, batch[1], batch[2])
    second, second_report = train(tmp_path)
    assert second.feature_mean == model.feature_mean and second.feature_scale == model.feature_scale
    assert second.coefficients == model.coefficients and second.intercept == model.intercept
    assert second_report["window_metrics"] == report["window_metrics"]
    assert report["evaluation"] == "training_fit_only"
    assert report["training"]["class_counts"].keys() == {"breathing", "breath_hold"}
    assert report["training"]["recordings"][0]["annotation_sha256"]


def test_model_contract_rejects_incompatible_or_nonfinite_artifacts(fitted):
    data = fitted[0].model_dump()
    changes = ({"feature_order": list(reversed(FEATURES))}, {"coefficients": [float("nan")] * 5},
               {"feature_scale": [0] * 5}, {"schema_version": 99},
               {"preprocessing": {**CONFIG, "window_s": 20}})
    for change in changes:
        with pytest.raises(ValueError):
            Model.model_validate({**data, **change})
    changed = deepcopy(data)
    changed["training"]["preprocessing_source_sha256"]["backend/breathing.py"] = "wrong"
    with pytest.raises(ValueError, match="source differs"):
        Model.model_validate(changed)


def test_validation_data_cannot_change_training_standardization(fitted, tmp_path):
    first, _, _, _ = fitted
    recording(tmp_path, "validation", "validation", "P02", seed=99)
    after, _ = train(tmp_path)
    assert after.feature_mean == first.feature_mean and after.feature_scale == first.feature_scale
    assert after.coefficients == first.coefficients
    assert [s["participant_id"] for s in after.training["recordings"]] == ["P01"]
    before = after.model_dump()
    report = validate(after, tmp_path)
    assert report["status"] == "complete" and report["window_metrics"]["windows"] > 0
    assert [s["participant_id"] for s in report["recordings"]] == ["P02"]
    assert after.model_dump() == before
    assert report["challenges"]["movement"]["status"] == "unavailable"


def test_validation_without_independent_recordings_is_pending(fitted, tmp_path):
    report = validate(fitted[0], tmp_path)
    assert report["status"] == "pending" and report["window_metrics"] is None
    assert report["recordings"] == []


def test_external_validation_rejects_training_participant_or_copy(fitted, tmp_path):
    model, _, path, labels = fitted
    other = tmp_path / "separate"
    other.mkdir()
    recording(other, "sameperson", "validation", "P01", seed=99)
    with pytest.raises(ValueError, match="overlaps training"):
        validate(model, other)
    second = tmp_path / "copy"
    second.mkdir()
    copy = second / path.name
    copy.write_bytes(path.read_bytes())
    save_labels(copy, labels.model_copy(update={"split": "validation", "participant_id": "P02"}))
    with pytest.raises(ValueError, match="overlaps training"):
        validate(model, second)


def test_metrics_count_misses_false_episodes_and_delay():
    annotations = [Annotation(start_s=0, end_s=20, label="breathing"),
                   Annotation(start_s=20, end_s=40, label="breath_hold"),
                   Annotation(start_s=40, end_s=60, label="breathing"),
                   Annotation(start_s=60, end_s=80, label="breath_hold")]
    timeline = [(float(t), "breath_hold" if 12 <= t < 15 or 25 <= t < 35 else "breathing")
                for t in range(10, 81)]
    events = event_metrics(timeline, annotations)
    assert events["annotated_holds"] == 2 and events["detected_holds"] == 1
    assert events["missed_holds"] == 1 and events["false_hold_episodes"] == 1
    assert events["detections"] == [{"hold_start_s": 20, "first_detection_s": 25, "delay_s": 5}]
    metrics = window_metrics([0, 0, 0, 1, 1], [0, 0, 1, 0, 1])
    assert metrics["confusion"] == {"breathing_as_breathing": 2, "breathing_as_hold": 1,
                                     "hold_as_breathing": 1, "hold_as_hold": 1}
    assert metrics["hold_precision"] == metrics["hold_recall"] == 0.5
    assert metrics["false_hold_fraction_during_breathing"] == pytest.approx(1/3)
    assert window_metrics([], [])["hold_recall"] is None


def test_missing_predictions_break_episode_continuity():
    annotation = [Annotation(start_s=0, end_s=50, label="breathing")]
    events = event_metrics([(10, "breath_hold"), (11, "no_signal"), (12, "breath_hold"),
                           (20, "breath_hold")], annotation)
    assert events["false_hold_episodes"] == 3


def test_cli_saves_reports_and_prediction_jsonl(fitted, tmp_path, capsys):
    model, _, path, _ = fitted
    output = tmp_path / "models" / "binary.json"
    main(["train", "--data", str(tmp_path), "--output", str(output)])
    assert json.loads(output.with_suffix(".training.json").read_text())["evaluation"] == "training_fit_only"
    capsys.readouterr()
    main(["predict", "--model", str(output), "--file", str(path)])
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[0]["end_s"] == 10 and all(line["label"] in CLASSES for line in lines)
    report_path = tmp_path / "validation.json"
    main(["validate", "--model", str(output), "--data", str(tmp_path), "--output", str(report_path)])
    assert json.loads(report_path.read_text())["status"] == "pending"


def test_training_needs_both_classes():
    with pytest.raises(ValueError, match="both classes"):
        fit(np.zeros((10, 5)), np.zeros(10))
    assert binary_label("normal_breathing") == "breathing"
    assert binary_label("movement") is None


def test_movement_and_empty_chair_challenges_are_reported(fitted, tmp_path):
    model = fitted[0]
    path, labels = recording(tmp_path, "challenge", "validation", "P02", seed=88)
    labels = labels.model_copy(update={"annotations": [
        Annotation(start_s=0, end_s=20, label="movement"),
        Annotation(start_s=20, end_s=40, label="empty_chair"),
        Annotation(start_s=40, end_s=labels.duration_s, label="uncertain")]})
    save_labels(path, labels)
    report = validate(model, tmp_path)
    assert report["status"] == "insufficient_usable_windows"
    assert report["window_metrics"] is None
    for label in ("movement", "empty_chair"):
        challenge = report["challenges"][label]
        assert challenge["status"] == "measured" and challenge["windows"] > 0
        assert 0 <= challenge["false_hold_fraction"] <= 1


def test_repeated_hold_episodes_only_match_a_ground_truth_hold_once():
    annotations = [Annotation(start_s=20, end_s=40, label="breath_hold")]
    report = event_metrics([(22, "breath_hold"), (23, "breathing"), (24, "breath_hold")], annotations)
    assert report["detected_holds"] == 1 and report["false_hold_episodes"] == 1


def test_single_class_validation_is_not_reported_as_complete(fitted, tmp_path):
    model = fitted[0]
    path, labels = recording(tmp_path, "onlybreathing", "validation", "P02", seed=88)
    save_labels(path, labels.model_copy(update={"annotations": [
        Annotation(start_s=0, end_s=labels.duration_s, label="breathing")]}))
    report = validate(model, tmp_path)
    assert report["status"] == "incomplete_class_coverage"
    assert report["missing_binary_classes"] == ["breath_hold"]


def test_empty_or_bad_model_radio_contract_is_rejected(fitted):
    data = fitted[0].model_dump()
    for signatures in ([], [{"channel": 11}], [{"csi_values": 31, "channel": 11,
                                               "bandwidth": 0, "secondary_channel": 0}]):
        changed = deepcopy(data)
        changed["training"]["radio_signatures"] = signatures
        with pytest.raises(ValueError, match="radio configuration"):
            Model.model_validate(changed)


def test_training_rejects_radio_changes_in_one_recording(tmp_path):
    path, _ = recording(tmp_path)
    packets = read_recording(path)
    packets[-1] = replace(packets[-1], packet=replace(packets[-1].packet, channel=6))
    pq.write_table(to_table(packets), path)
    # Refresh only the source hash so this specifically exercises the radio check.
    from backend.label import sidecar
    data = json.loads(sidecar(path).read_text())
    data["recording_sha256"] = fingerprint(path)
    sidecar(path).write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mixed radio configuration"):
        train(tmp_path)


def test_validation_on_an_empty_dataset_is_pending(fitted, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert validate(fitted[0], empty)["status"] == "pending"
