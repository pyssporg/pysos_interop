"""WGS84 and ENU conversion tests."""

import math

import pytest

from pysos_interop.geo import (
    WGS84_A,
    WGS84_E2,
    GeoOrigin,
    ecef_to_enu,
    ecef_to_geodetic,
    ecef_velocity_to_enu,
    enu_to_ecef,
    enu_velocity_to_ecef,
    geodetic_to_ecef,
)

ORIGIN = GeoOrigin(45.0, 10.0, 100.0)


@pytest.mark.parametrize(
    "lat_deg,lon_deg,alt_m",
    [(0.0, 0.0, 0.0), (70.0, 20.0, 300.0)],
)
def test_geodetic_ecef_round_trip(lat_deg, lon_deg, alt_m):
    lat2, lon2, alt2 = ecef_to_geodetic(geodetic_to_ecef(lat_deg, lon_deg, alt_m))
    assert lat2 == pytest.approx(lat_deg, abs=1e-9)
    assert lon2 == pytest.approx(lon_deg, abs=1e-9)
    assert alt2 == pytest.approx(alt_m, abs=1e-3)


@pytest.mark.parametrize(
    "enu_m",
    [(0.0, 0.0, 0.0), (-5000.0, 3000.0, 100.0)],
)
def test_enu_ecef_enu_round_trip(enu_m):
    back = ecef_to_enu(enu_to_ecef(enu_m, ORIGIN), ORIGIN)
    assert math.dist(enu_m, back) < 1e-3


def test_velocity_conversion_round_trip():
    velocity = (12.0, -3.0, 0.5)
    back = ecef_velocity_to_enu(enu_velocity_to_ecef(velocity, ORIGIN), ORIGIN)
    assert back == pytest.approx(velocity, abs=1e-12)


def test_enu_axes_match_an_independent_first_order_offset():
    lat = math.radians(ORIGIN.latitude_deg)
    sin_lat = math.sin(lat)
    w = math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    meridional = WGS84_A * (1.0 - WGS84_E2) / (w**3)
    normal = WGS84_A / w

    north_deg = ORIGIN.latitude_deg + math.degrees(50.0 / meridional)
    east_deg = ORIGIN.longitude_deg + math.degrees(
        50.0 / (normal * math.cos(lat))
    )
    north_point = geodetic_to_ecef(north_deg, ORIGIN.longitude_deg, ORIGIN.altitude_m)
    east_point = geodetic_to_ecef(ORIGIN.latitude_deg, east_deg, ORIGIN.altitude_m)

    assert ecef_to_enu(north_point, ORIGIN) == pytest.approx((0.0, 50.0, 0.0), abs=1e-3)
    assert ecef_to_enu(east_point, ORIGIN) == pytest.approx((50.0, 0.0, 0.0), abs=1e-3)
