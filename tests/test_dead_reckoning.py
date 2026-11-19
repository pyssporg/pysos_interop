"""Dead reckoning and staleness tests."""

import math

import pytest

from pysos_interop.dead_reckoning import dead_reckon, is_stale
from pysos_interop.model import EntityKey, EntityState

KEY = EntityKey(1, 1, 7)
START = 10.0
DT = 4.5
POSITION = (100.0, -50.0, 25.0)
ORIENTATION = (0.1, 0.2, 0.3)
VELOCITY = (3.0, -4.0, 2.0)


def make_state(**changes):
    fields = {
        "key": KEY,
        "timestamp": START,
        "position_enu_m": POSITION,
        "velocity_enu_mps": VELOCITY,
        "orientation_rps": ORIENTATION,
        "angular_velocity_rps": (0.0, 0.0, 0.0),
        "marking": "DR-7",
    }
    fields.update(changes)
    return EntityState(**fields)


def test_timestamp_advances_for_every_algorithm():
    for algorithm in (1, 2, 4):
        out = dead_reckon(make_state(), DT, algorithm)
        assert out.timestamp == pytest.approx(START + DT)


def test_algorithm_one_is_static():
    state = make_state(angular_velocity_rps=(0.1, 0.2, 0.3))
    out = dead_reckon(state, 100.0, 1)
    assert out.position_enu_m == POSITION
    assert out.orientation_rps == ORIENTATION
    assert out.velocity_enu_mps == VELOCITY


def test_algorithm_two_is_linear_and_ignores_rotation():
    state = make_state(angular_velocity_rps=(0.5, 0.0, 0.0))
    out = dead_reckon(state, DT, 2)
    assert out.position_enu_m == pytest.approx(
        tuple(p + v * DT for p, v in zip(POSITION, VELOCITY, strict=True))
    )
    assert out.orientation_rps == ORIENTATION


def test_algorithm_four_integrates_position_and_attitude():
    state = make_state(orientation_rps=(0.0, 0.0, 0.0), angular_velocity_rps=(0.0, 0.0, 0.5))
    out = dead_reckon(state, 2.0, 4)
    assert out.position_enu_m == pytest.approx(
        tuple(p + v * 2.0 for p, v in zip(POSITION, VELOCITY, strict=True))
    )
    assert out.orientation_rps == pytest.approx((0.0, 0.0, 1.0))


def test_algorithm_four_converts_body_rates_before_integrating():
    pitch = 0.3
    state = make_state(
        orientation_rps=(0.0, pitch, 0.0),
        angular_velocity_rps=(0.2, 0.0, 0.4),
    )
    dt = 0.5
    out = dead_reckon(state, dt, 4)

    expected_roll = (0.2 + 0.4 * math.tan(pitch)) * dt
    expected_yaw = (0.4 / math.cos(pitch)) * dt
    assert out.orientation_rps == pytest.approx((expected_roll, pitch, expected_yaw))


def test_zero_rates_leave_attitude_alone():
    state = make_state()
    out = dead_reckon(state, 100.0, 4)
    assert out.orientation_rps == ORIENTATION


@pytest.mark.parametrize("algorithm", [0, 3])
def test_unsupported_algorithm_raises(algorithm):
    with pytest.raises(ValueError, match="Unsupported dead-reckoning algorithm"):
        dead_reckon(make_state(), DT, algorithm)


def test_is_stale_is_strict_at_the_threshold():
    state = make_state(timestamp=10.0)
    assert not is_stale(state, now=15.0, threshold=5.0)
    assert is_stale(state, now=15.001, threshold=5.0)


def test_input_state_is_not_mutated():
    state = make_state(angular_velocity_rps=(0.1, 0.2, 0.3))
    for algorithm in (1, 2, 4):
        dead_reckon(state, 999.0, algorithm)
    is_stale(state, 999.0, 5.0)
    assert state.position_enu_m == POSITION
    assert state.orientation_rps == ORIENTATION
    assert state.timestamp == START
