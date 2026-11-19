"""Dead reckoning between sparse entity updates.

Only the three algorithms the hub contract supports are implemented:
DIS algorithm 1 (static), 2 (linear, world-frame velocity) and 4 (linear,
body-frame velocity, rotating).  They are pure functions over
:class:`~pysos_interop.model.EntityState`.
"""

from __future__ import annotations

from dataclasses import replace

from .model import EntityState, Vec3
from .rates import body_rates_to_euler_rates

STATIC = 1
LINEAR = 2
ROTATING = 4
SUPPORTED_ALGORITHMS = frozenset({STATIC, LINEAR, ROTATING})


def dead_reckon(state: EntityState, dt: float, algorithm: int = 4) -> EntityState:
    """Propagate ``state`` by ``dt`` seconds with DIS ``algorithm``.

    Algorithms 1, 2 and 4 are supported; any other value raises
    ``ValueError``.  Position always advances with the ENU velocity already
    stored in the state.  Algorithm 4 additionally integrates attitude using
    the body-frame angular velocity, converted to Euler rates at the current
    orientation.
    """

    algorithm = int(algorithm)
    if algorithm not in SUPPORTED_ALGORITHMS:
        raise ValueError(f"Unsupported dead-reckoning algorithm: {algorithm}")

    delta = float(dt)
    timestamp = state.timestamp + delta
    if algorithm == STATIC:
        return replace(state, timestamp=timestamp)

    position: Vec3 = tuple(  # type: ignore[assignment]
        float(p) + float(v) * delta
        for p, v in zip(state.position_enu_m, state.velocity_enu_mps, strict=True)
    )
    if algorithm == LINEAR:
        return replace(state, timestamp=timestamp, position_enu_m=position)

    euler_rates = body_rates_to_euler_rates(
        state.orientation_rps, state.angular_velocity_rps
    )
    orientation: Vec3 = tuple(  # type: ignore[assignment]
        float(angle) + float(rate) * delta
        for angle, rate in zip(state.orientation_rps, euler_rates, strict=True)
    )
    return replace(
        state,
        timestamp=timestamp,
        position_enu_m=position,
        orientation_rps=orientation,
    )


def is_stale(state: EntityState, now: float, threshold: float) -> bool:
    """Return whether ``state`` is older than ``threshold`` seconds at ``now``.

    The comparison is strict: an age exactly equal to the threshold is fresh.
    """

    return (float(now) - float(state.timestamp)) > float(threshold)
