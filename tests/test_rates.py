"""Euler-rate and body-rate conversion tests."""

import math

import pytest

from pysos_interop.rates import body_rates_to_euler_rates, euler_rates_to_body_rates

ORIENTATIONS = [
    pytest.param((0.0, 0.0, 0.0), id="level"),
    pytest.param((0.1, -0.3, 0.6), id="typical"),
]
RATES = [
    pytest.param((0.0, 0.0, 0.0), id="still"),
    pytest.param((0.1, -0.2, 0.3), id="mixed"),
]


@pytest.mark.parametrize("euler", ORIENTATIONS)
@pytest.mark.parametrize("rates", RATES)
def test_round_trip_is_exact_inverse(euler, rates):
    body = euler_rates_to_body_rates(euler, rates)
    recovered = body_rates_to_euler_rates(euler, body)
    assert recovered == pytest.approx(rates, abs=1e-12)


def test_level_pure_yaw_is_a_body_z_rate():
    body = euler_rates_to_body_rates((0.0, 0.0, 0.0), (0.0, 0.0, 0.35))
    assert body == pytest.approx((0.0, 0.0, 0.35), abs=1e-12)


def test_pure_roll_is_unchanged_by_bank():
    body = euler_rates_to_body_rates((0.4, 0.0, 0.0), (0.3, 0.0, 0.0))
    assert body == pytest.approx((0.3, 0.0, 0.0), abs=1e-12)


@pytest.mark.parametrize("pitch", [math.pi / 2.0, -math.pi / 2.0])
def test_inverse_raises_at_pitch_singularity(pitch):
    euler = (0.0, pitch, 0.2)
    with pytest.raises(ValueError, match="gimbal lock"):
        body_rates_to_euler_rates(euler, (0.1, 0.2, 0.3))
    # The forward map stays defined there; a pure pitch rate is body-y.
    body = euler_rates_to_body_rates(euler, (0.0, 0.5, 0.0))
    assert body == pytest.approx((0.0, 0.5, 0.0), abs=1e-12)
