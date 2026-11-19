"""JSONL record and replay round-trip tests."""

import json

from pysos_interop.jsonl import JsonlRecorder, iter_jsonl
from pysos_interop.model import EntityKey, EntityState


def full_state(key, timestamp):
    return EntityState(
        key=key,
        timestamp=timestamp,
        position_enu_m=(123.5, -456.25, 789.125),
        velocity_enu_mps=(10.0, -20.0, 0.5),
        orientation_rps=(1.5, -2.5, 6.25),
        angular_velocity_rps=(0.01, -0.02, 0.03),
        marking="AC-007",
        force_id=3,
        exercise_id=4,
    )


def test_round_trip_preserves_every_field(tmp_path):
    state = full_state(EntityKey(2, 4, 8), 12.5)
    path = tmp_path / "recording.jsonl"

    with JsonlRecorder(path) as recorder:
        recorder.write(state)

    assert list(iter_jsonl(path)) == [state]


def test_multiple_states_replay_in_file_order(tmp_path):
    first = full_state(EntityKey(1, 1, 1), 1.0)
    second = full_state(EntityKey(1, 1, 2), 1.1)
    path = tmp_path / "pair.jsonl"

    with JsonlRecorder(path) as recorder:
        recorder.write(first)
        recorder.write(second)

    assert list(iter_jsonl(path)) == [first, second]


def test_blank_lines_and_optional_fields_are_tolerated(tmp_path):
    state = full_state(EntityKey(1, 1, 1), 2.0)
    path = tmp_path / "legacy.jsonl"
    payload = {
        "key": {"site": 1, "application": 1, "entity": 1},
        "timestamp": 2.0,
        "position_enu_m": [1.0, 2.0, 3.0],
        "velocity_enu_mps": [0.0, 0.0, 0.0],
        "orientation_rps": [0.0, 0.0, 0.0],
        "marking": "LEGACY",
    }
    path.write_text("\n" + json.dumps(payload) + "\n\n", encoding="utf-8")

    replayed = list(iter_jsonl(path))
    assert len(replayed) == 1
    assert replayed[0].force_id == 1
    assert replayed[0].exercise_id == 1
    assert replayed[0].angular_velocity_rps == (0.0, 0.0, 0.0)
    assert replayed[0] != state
