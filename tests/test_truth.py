"""Truth-stream, metadata and measurement-CSV export tests.

The CSV checks import ``pyssp_vv.measure`` itself and feed the exported
columns to its public ``Trajectory`` constructor; the export does not carry a
second parser that could drift from the measurement tool.
"""

import csv
import math

import pytest

from pysos_interop.jsonl import iter_jsonl
from pysos_interop.model import EntityKey, EntityState
from pysos_interop.truth import (
    FORMAT_VERSION,
    MEASURE_CHANNELS,
    TruthRecorder,
    entity_slug,
    export_measure_csv,
    iter_truth,
    measure_columns,
    read_truth_metadata,
)

KEYS = (EntityKey(1, 1, 7), EntityKey(1, 2, 8))


def state_at(key, sample, east_offset=0.0):
    return EntityState(
        key=key,
        timestamp=sample * 0.1,
        position_enu_m=(east_offset + sample * 10.0, sample * 20.0, 1000.0 + sample),
        velocity_enu_mps=(10.0, 20.0, 1.0),
        orientation_rps=(0.01 * sample, 0.02 * sample, 0.03 * sample),
        angular_velocity_rps=(0.001, 0.002, 0.003),
        marking=f"AC-{key.entity}",
        force_id=1,
        exercise_id=9,
    )


def record_run(path, samples=10):
    with TruthRecorder(
        path,
        run_id="run-42",
        origin=None,
        model_ids={"1_1_7": "aircraft", "1_2_8": "target"},
        sample_rate_hz=10.0,
    ) as recorder:
        for sample in range(samples):
            recorder.write_sample(
                [
                    state_at(KEYS[0], sample, east_offset=0.0),
                    state_at(KEYS[1], sample, east_offset=1.0),
                ]
            )
    return path


def load_csv(path):
    """Read the exported CSV into a header and numpy column arrays."""

    numpy = pytest.importorskip("numpy")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = [row for row in reader if row]
    values = numpy.asarray(rows, dtype=float)
    return header, {name: values[:, index] for index, name in enumerate(header)}


def test_truth_stream_is_one_row_per_entity_per_sample(tmp_path):
    path = record_run(tmp_path / "run.jsonl", samples=4)

    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 8
    assert [state.key for state in iter_truth(path)][::2] == [KEYS[0]] * 4
    assert all(state.exercise_id == 9 for state in iter_truth(path))
    # The truth row is a superset of the JSONL row, so the old reader works.
    assert len(list(iter_jsonl(path))) == 8


def test_metadata_sidecar_round_trip(tmp_path):
    path = record_run(tmp_path / "run.jsonl", samples=10)

    metadata = read_truth_metadata(path)
    assert metadata.run_id == "run-42"
    assert metadata.format_version == FORMAT_VERSION
    assert metadata.origin.latitude_deg == 0.0
    assert metadata.model_ids == {"1_1_7": "aircraft", "1_2_8": "target"}
    assert [entity["entity"] for entity in metadata.entities] == ["1_1_7", "1_2_8"]
    assert metadata.entities[0]["model_id"] == "aircraft"
    assert metadata.entities[1]["marking"] == "AC-8"
    assert metadata.rates == {"sample_hz": 10.0, "sample_period_s": 0.1}
    assert metadata.start_time_sim == 0.0
    assert metadata.sample_count == 10
    assert set(metadata.units) == set(MEASURE_CHANNELS)


def test_csv_header_is_the_exact_measurement_column_set(tmp_path):
    path = record_run(tmp_path / "run.jsonl", samples=3)
    csv_path = export_measure_csv(path, tmp_path / "run.csv")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header == measure_columns(["1_1_7", "1_2_8"])
    assert header[0] == "time"
    assert len(header) == 1 + 2 * len(MEASURE_CHANNELS)


def test_exported_columns_feed_pyssp_vv_trajectory_unchanged(tmp_path):
    numpy = pytest.importorskip("numpy")
    measure = pytest.importorskip("pyssp_vv.measure")

    path = record_run(tmp_path / "run.jsonl", samples=10)
    csv_path = export_measure_csv(path, tmp_path / "run.csv")
    header, data = load_csv(csv_path)

    assert header == measure_columns(["1_1_7", "1_2_8"])

    for key in KEYS:
        slug = entity_slug(key)
        channels = {
            name.split(".", 1)[1]: data[name]
            for name in header
            if name.startswith(f"{slug}.")
        }
        trajectory = measure.Trajectory(
            time=data["time"],
            channels=channels,
            label=slug,
        )
        assert len(trajectory) == 10
        assert set(trajectory.signals) == set(MEASURE_CHANNELS)
        assert numpy.all(numpy.diff(trajectory.time) >= 0)


def test_record_export_measure_smoke(tmp_path):
    numpy = pytest.importorskip("numpy")
    measure = pytest.importorskip("pyssp_vv.measure")

    path = record_run(tmp_path / "run.jsonl", samples=10)
    csv_path = export_measure_csv(path, tmp_path / "run.csv")
    header, data = load_csv(csv_path)

    def trajectory(slug):
        return measure.Trajectory(
            time=data["time"],
            channels={
                name.split(".", 1)[1]: data[name]
                for name in header
                if name.startswith(f"{slug}.")
            },
            label=slug,
        )

    comparison = measure.compare(
        trajectory("1_1_7"),
        trajectory("1_2_8"),
        signals=("position_east_m",),
    )
    (signal,) = comparison.signals
    assert signal.signal == "position_east_m"
    assert math.isclose(signal.max_abs_error, 1.0, rel_tol=0.0, abs_tol=1e-12)
    assert signal.coverage == 1.0
    assert numpy.allclose(data["1_1_7.position_up_m"], data["1_2_8.position_up_m"])
