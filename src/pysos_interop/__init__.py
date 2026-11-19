"""Neutral entity state and protocol interop for system-of-systems simulation.

The core imports only the standard library.  DIS support lives in
:mod:`pysos_interop.dis` and needs the optional ``opendis`` package.
"""

from __future__ import annotations

from .dead_reckoning import dead_reckon, is_stale
from .geo import (
    GeoOrigin,
    ecef_to_enu,
    ecef_to_geodetic,
    enu_to_ecef,
    geodetic_to_ecef,
)
from .jsonl import JsonlRecorder, iter_jsonl
from .model import EntityKey, EntityState
from .rates import body_rates_to_euler_rates, euler_rates_to_body_rates
from .transport import (
    Channel,
    ChannelClosedError,
    ChannelTimeoutError,
    TransportError,
)

__version__ = "0.1.0"

__all__ = [
    "Channel",
    "ChannelClosedError",
    "ChannelTimeoutError",
    "EntityKey",
    "EntityState",
    "GeoOrigin",
    "JsonlRecorder",
    "TransportError",
    "__version__",
    "body_rates_to_euler_rates",
    "dead_reckon",
    "ecef_to_enu",
    "ecef_to_geodetic",
    "enu_to_ecef",
    "euler_rates_to_body_rates",
    "geodetic_to_ecef",
    "is_stale",
    "iter_jsonl",
]
