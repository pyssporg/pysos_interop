"""WGS84 geodetic, ECEF and local ENU conversions.

The neutral model stores ENU metres; DIS carries geocentric ECEF metres.  All
helpers are plain standard-library maths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Vec3

WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


@dataclass(frozen=True)
class GeoOrigin:
    """Geodetic origin of the local ENU frame."""

    latitude_deg: float = 0.0
    longitude_deg: float = 0.0
    altitude_m: float = 0.0


def geodetic_to_ecef(latitude_deg: float, longitude_deg: float, altitude_m: float) -> Vec3:
    """Convert WGS84 geodetic coordinates to ECEF metres."""

    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + altitude_m) * cos_lat * cos_lon
    y = (n + altitude_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + altitude_m) * sin_lat
    return (x, y, z)


def ecef_to_geodetic(ecef_m: Vec3) -> tuple[float, float, float]:
    """Convert ECEF metres to ``(latitude_deg, longitude_deg, altitude_m)``."""

    x, y, z = (float(value) for value in ecef_m)
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    altitude = 0.0
    for _ in range(5):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        altitude = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1.0 - WGS84_E2 * n / (n + altitude)))
    return (math.degrees(lat), math.degrees(lon), altitude)


def _enu_basis(origin: GeoOrigin) -> tuple[Vec3, Vec3, Vec3]:
    lat = math.radians(origin.latitude_deg)
    lon = math.radians(origin.longitude_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    east = (-sin_lon, cos_lon, 0.0)
    north = (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)
    up = (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat)
    return (east, north, up)


def _origin_ecef(origin: GeoOrigin) -> Vec3:
    return geodetic_to_ecef(origin.latitude_deg, origin.longitude_deg, origin.altitude_m)


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def enu_to_ecef(enu_m: Vec3, origin: GeoOrigin) -> Vec3:
    """Convert local ENU metres to ECEF metres."""

    east, north, up = _enu_basis(origin)
    ref = _origin_ecef(origin)
    e, n, u = (float(value) for value in enu_m)
    return tuple(  # type: ignore[return-value]
        ref[i] + east[i] * e + north[i] * n + up[i] * u for i in range(3)
    )


def ecef_to_enu(ecef_m: Vec3, origin: GeoOrigin) -> Vec3:
    """Convert ECEF metres to local ENU metres."""

    east, north, up = _enu_basis(origin)
    ref = _origin_ecef(origin)
    delta = (
        float(ecef_m[0]) - ref[0],
        float(ecef_m[1]) - ref[1],
        float(ecef_m[2]) - ref[2],
    )
    return (_dot(east, delta), _dot(north, delta), _dot(up, delta))


def enu_velocity_to_ecef(velocity_enu_mps: Vec3, origin: GeoOrigin) -> Vec3:
    """Rotate an ENU velocity into ECEF axes."""

    east, north, up = _enu_basis(origin)
    e, n, u = (float(value) for value in velocity_enu_mps)
    return tuple(  # type: ignore[return-value]
        east[i] * e + north[i] * n + up[i] * u for i in range(3)
    )


def ecef_velocity_to_enu(velocity_ecef_mps: Vec3, origin: GeoOrigin) -> Vec3:
    """Rotate an ECEF velocity into ENU axes."""

    east, north, up = _enu_basis(origin)
    v = tuple(float(value) for value in velocity_ecef_mps)
    return (_dot(east, v), _dot(north, v), _dot(up, v))
