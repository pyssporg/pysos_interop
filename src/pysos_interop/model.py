"""Neutral entity state shared by every participant in a system-of-systems run.

This module is the vocabulary of the communication hub.  Producers and
consumers agree on these two dataclasses, not on each other's frames,
schemas, or transport formats.
"""

from __future__ import annotations

from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass(frozen=True, order=True)
class EntityKey:
    """DIS entity identity: site, application and entity number."""

    site: int
    application: int
    entity: int

    def __str__(self) -> str:
        return f"{self.site}:{self.application}:{self.entity}"


@dataclass(frozen=True)
class EntityState:
    """One entity's state in a local east-north-up frame.

    ``orientation_rps`` is the Z-Y-X Euler attitude ``(roll, pitch, yaw)`` in
    radians: yaw about the local vertical, then pitch, then roll.  The name
    follows the protocol field it feeds; it is an angle, not a rate.

    ``angular_velocity_rps`` is angular velocity about the body axes
    ``(x forward, y right, z down)`` in radians per second.

    Position and linear velocity are always ENU metres and metres per second.
    Protocol-specific frames are converted at the protocol boundary.
    """

    key: EntityKey
    timestamp: float
    position_enu_m: Vec3
    velocity_enu_mps: Vec3
    orientation_rps: Vec3
    angular_velocity_rps: Vec3
    marking: str
    force_id: int = 1
    exercise_id: int = 1
