"""Z-Y-X Euler-rate and body-rate conversion.

Engines usually integrate Euler angles; DIS dead-reckoning parameters carry
angular velocity about the body axes.  Both directions live here so the
conversion happens once, at the protocol boundary.
"""

from __future__ import annotations

import math

from .model import Vec3

_GIMBAL_TOLERANCE = 1e-9


def euler_rates_to_body_rates(euler: Vec3, euler_rates: Vec3) -> Vec3:
    """Convert Z-Y-X Euler-angle rates to body-frame angular rates.

    ``euler`` is ``(roll, pitch, yaw)`` in radians and ``euler_rates`` is
    ``(roll_dot, pitch_dot, yaw_dot)`` in radians per second.  The result is
    ``(p, q, r)`` about body axes ``x`` forward, ``y`` right, ``z`` down.
    """

    roll, pitch = float(euler[0]), float(euler[1])
    roll_dot, pitch_dot, yaw_dot = (float(value) for value in euler_rates)
    sin_roll, cos_roll = math.sin(roll), math.cos(roll)
    sin_pitch, cos_pitch = math.sin(pitch), math.cos(pitch)

    p = roll_dot - yaw_dot * sin_pitch
    q = pitch_dot * cos_roll + yaw_dot * sin_roll * cos_pitch
    r = -pitch_dot * sin_roll + yaw_dot * cos_roll * cos_pitch
    return (p, q, r)


def body_rates_to_euler_rates(euler: Vec3, body_rates: Vec3) -> Vec3:
    """Convert body-frame angular rates to Z-Y-X Euler-angle rates.

    This is the exact inverse of :func:`euler_rates_to_body_rates`.
    ``ValueError`` is raised within :data:`_GIMBAL_TOLERANCE` of pitch
    ``+/-90`` degrees, where roll and yaw rates cannot be separated.
    """

    roll, pitch = float(euler[0]), float(euler[1])
    p, q, r = (float(value) for value in body_rates)
    sin_roll, cos_roll = math.sin(roll), math.cos(roll)
    cos_pitch = math.cos(pitch)
    if abs(cos_pitch) < _GIMBAL_TOLERANCE:
        raise ValueError(
            "Euler rates are undefined at pitch = +/-90 degrees (gimbal lock)"
        )

    roll_dot = p + (q * sin_roll + r * cos_roll) * math.tan(pitch)
    pitch_dot = q * cos_roll - r * sin_roll
    yaw_dot = (q * sin_roll + r * cos_roll) / cos_pitch
    return (roll_dot, pitch_dot, yaw_dot)
