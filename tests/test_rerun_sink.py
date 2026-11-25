"""Rerun sink tests: recorded stream to ``.rrd``, paths and lazy import."""

import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pysos_interop import EntityKey, EntityState, JsonlRecorder
from pysos_interop.rerun_sink import (
    ENTITY_LEAVES,
    RerunSink,
    entity_path,
    entity_slug,
    recordings_to_rrd,
    rpy_rad_to_quaternion,
)

rr = pytest.importorskip("rerun")
RrdReader = pytest.importorskip("rerun.chunk").RrdReader

KEYS = (EntityKey(1, 1, 7), EntityKey(1, 1, 8))


def state_at(key, sample, east_offset=0.0):
    return EntityState(
        key=key,
        timestamp=sample * 0.1,
        position_enu_m=(east_offset + sample * 10.0, sample * 20.0, 1000.0 + sample),
        velocity_enu_mps=(10.0, 20.0, 1.0),
        orientation_rps=(0.01 * sample, 0.02 * sample, 0.03 * sample),
        angular_velocity_rps=(0.001, 0.002, 0.003),
        marking=f"AC-{key.entity}",
    )


def write_stream(path, samples=10):
    with JsonlRecorder(path) as recorder:
        for sample in range(samples):
            recorder.write(state_at(KEYS[0], sample, east_offset=0.0))
            recorder.write(state_at(KEYS[1], sample, east_offset=5.0))
    return path


def entity_paths_in(rrd_path):
    summary = RrdReader(str(rrd_path)).store().summary()
    return {line.split(" rows=", 1)[0].lstrip("/") for line in summary.splitlines()}


def component_values_in(rrd_path, entity_path, column):
    """Return one component column for an entity, or ``None`` if absent."""

    wanted = entity_path.lstrip("/")
    for chunk in RrdReader(str(rrd_path)).store().stream():
        if chunk.entity_path.lstrip("/") == wanted:
            batch = chunk.to_record_batch()
            if column in batch.schema.names:
                return batch.column(column).to_pylist()
    return None


def test_two_entity_ten_sample_stream_writes_a_non_trivial_rrd(tmp_path):
    stream = write_stream(tmp_path / "run.jsonl", samples=10)
    rrd_path = recordings_to_rrd(stream, tmp_path / "run.rrd", app_id="pysos-test")

    assert rrd_path == tmp_path / "run.rrd"
    assert rrd_path.exists()
    size = rrd_path.stat().st_size
    assert size > 1000, f"{rrd_path} is only {size} bytes"

    logged = entity_paths_in(rrd_path)
    for key in KEYS:
        for leaf in ENTITY_LEAVES:
            assert entity_path(key, leaf) in logged, (key, leaf, sorted(logged))


def test_labels_are_logged_only_for_supplied_slugs(tmp_path):
    stream = write_stream(tmp_path / "run.jsonl", samples=2)
    labelled = entity_slug(KEYS[0])
    rrd_path = recordings_to_rrd(
        stream, tmp_path / "labels.rrd", labels={labelled: "ALPHA"}
    )

    logged = entity_paths_in(rrd_path)
    assert entity_path(KEYS[0], "label") in logged
    assert entity_path(KEYS[1], "label") not in logged

    text = component_values_in(
        rrd_path, entity_path(KEYS[0], "label"), "TextDocument:text"
    )
    assert text == [["ALPHA"]]


def test_supplied_colour_tints_marker_and_trail(tmp_path):
    stream = write_stream(tmp_path / "run.jsonl", samples=3)
    slug = entity_slug(KEYS[0])
    rrd_path = recordings_to_rrd(
        stream, tmp_path / "colour.rrd", colors={slug: (0, 128, 255)}
    )

    logged = entity_paths_in(rrd_path)
    assert entity_path(KEYS[0], "marker") in logged
    assert entity_path(KEYS[0], "trail") in logged
    assert entity_path(KEYS[1], "marker") in logged

    marker_colours = component_values_in(
        rrd_path, entity_path(KEYS[0], "marker"), "Boxes3D:colors"
    )
    assert marker_colours is not None and marker_colours[0]
    assert (
        component_values_in(rrd_path, entity_path(KEYS[1], "marker"), "Boxes3D:colors")
        is None
    )


def test_recording_without_labels_or_colours_keeps_previous_output(tmp_path):
    stream = write_stream(tmp_path / "run.jsonl", samples=2)

    # The 0.2.x positional/keyword call must still work unchanged.
    old_path = recordings_to_rrd(stream, tmp_path / "old.rrd")
    new_path = recordings_to_rrd(
        stream,
        tmp_path / "new.rrd",
        app_id="pysos_interop",
        origin=None,
        trail_points=200,
    )

    for rrd_path in (old_path, new_path):
        logged = entity_paths_in(rrd_path)
        assert entity_path(KEYS[0], "marker") in logged
        assert entity_path(KEYS[0], "label") not in logged
        assert (
            component_values_in(
                rrd_path, entity_path(KEYS[0], "marker"), "Boxes3D:colors"
            )
            is None
        )


def test_observe_accepts_an_rpr_frame(tmp_path):
    rpr = pytest.importorskip("pysos_interop.rpr")
    origin = rpr.RprOrigin(57.7, 12.0, 100.0)
    state = state_at(KEYS[0], 3)
    payload = rpr.encode_entity_state(state, origin=origin)
    frame = rpr.decode_frame(payload, origin=origin, timestamp=state.timestamp)
    assert isinstance(frame, rpr.RprFrame)

    rrd_path = tmp_path / "frame.rrd"
    with RerunSink(rrd_path) as sink:
        sink.observe(frame)

    logged = entity_paths_in(rrd_path)
    assert entity_path(frame.state.key, "pose") in logged
    assert entity_path(frame.state.key, "marker") in logged


def test_observe_rejects_an_unknown_type(tmp_path):
    with RerunSink(tmp_path / "bad.rrd") as sink:
        with pytest.raises(TypeError, match="EntityState or RprFrame"):
            sink.observe(object())


def test_closed_sink_refuses_more_observations(tmp_path):
    sink = RerunSink(tmp_path / "closed.rrd")
    sink.close()
    with pytest.raises(RuntimeError, match="closed"):
        sink.observe(state_at(KEYS[0], 0))


def test_climb_angle_comes_from_successive_positions(tmp_path):
    stream = write_stream(tmp_path / "run.jsonl", samples=3)
    rrd_path = recordings_to_rrd(stream, tmp_path / "climb.rrd", app_id="pysos-test")

    values = component_values_in(
        rrd_path, entity_path(KEYS[0], "status/climb_angle_deg"), "Scalars:scalars"
    )
    assert values is not None
    expected = math.degrees(math.atan2(1.0, math.hypot(10.0, 20.0)))
    assert values[0][0] == pytest.approx(0.0)
    assert values[-1][0] == pytest.approx(expected)


def test_quaternion_helpers():
    assert rpy_rad_to_quaternion(0.0, 0.0, 0.0) == (0.0, 0.0, 0.0, 1.0)
    x, y, z, w = rpy_rad_to_quaternion(0.0, 0.0, math.pi / 2.0)
    assert math.isclose(z, math.sqrt(0.5), abs_tol=1e-12)
    assert math.isclose(w, math.sqrt(0.5), abs_tol=1e-12)
    assert entity_slug(EntityKey(2, 3, 4)) == "2_3_4"
    assert entity_path(EntityKey(2, 3, 4), "pose") == "world/entity/2_3_4/pose"


def _run(code):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_missing_rerun_fails_only_when_the_sink_is_constructed():
    code = """
import sys

class Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "rerun" or fullname.startswith("rerun."):
            raise ImportError("blocked for test")
        return None

sys.meta_path.insert(0, Blocker())
from pysos_interop.rerun_sink import RerunSink, entity_slug
from pysos_interop import EntityKey
assert entity_slug(EntityKey(1, 1, 1)) == "1_1_1"
try:
    RerunSink("/tmp/never-written.rrd")
except ImportError as exc:
    assert "pysos-interop[rerun]" in str(exc), exc
else:
    raise SystemExit("expected ImportError")
"""
    result = _run(code)
    assert result.returncode == 0, result.stderr
