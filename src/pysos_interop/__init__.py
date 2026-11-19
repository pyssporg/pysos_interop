"""Neutral entity state and protocol interop for system-of-systems simulation.

The core imports only the standard library.  DIS support lives in
:mod:`pysos_interop.dis` and needs the optional ``opendis`` package.  RPR
support lives in :mod:`pysos_interop.rpr` and needs the optional
``pysos-rpr`` package; neither adapter is imported here.
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
from .truth import (
    TruthMetadata,
    TruthRecorder,
    export_measure_csv,
    iter_truth,
    read_truth_metadata,
)

__version__ = "0.2.0"

__all__ = [
    "Channel",
    "ChannelClosedError",
    "ChannelTimeoutError",
    "EntityKey",
    "EntityState",
    "GeoOrigin",
    "JsonlRecorder",
    "TransportError",
    "TruthMetadata",
    "TruthRecorder",
    "__version__",
    "body_rates_to_euler_rates",
    "dead_reckon",
    "ecef_to_enu",
    "ecef_to_geodetic",
    "enu_to_ecef",
    "euler_rates_to_body_rates",
    "export_measure_csv",
    "geodetic_to_ecef",
    "is_stale",
    "iter_jsonl",
    "iter_truth",
    "read_truth_metadata",
]
