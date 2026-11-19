"""Rerun sink over decoded RPR frames and neutral entity state.

The Rerun world frame is ENU: x=east, y=north, z=up.  ``EntityState``
orientation is Z-Y-X Euler ``(roll, pitch, yaw)`` in radians and is logged as
a quaternion in ``(x, y, z, w)`` order.

This module is optional.  ``rerun`` is imported lazily by
:class:`RerunSink.__init__`, never by the package ``__init__`` and never by a
core module.  Without the ``rerun-sdk`` package the sink raises ``ImportError``
with the extra to install; the pure path/rotation helpers keep working.

The sink is synchronous: it owns no thread, no socket and no run control.  It
turns a recorded JSONL stream into an ``.rrd`` file or logs live frames as
they are handed to :meth:`RerunSink.observe`.

Labels and colours are keyed by the documented wire slug
``<site>_<application>_<entity>`` (see :func:`entity_slug`), never by entity
marking.  A supplied label becomes a static ``TextDocument`` at
``world/entity/<slug>/label``; a supplied colour tints that entity's ``marker``
and ``trail``.  Slugs with no label or colour keep the previous output exactly,
so an existing call produces the same ``.rrd`` as before.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .geo import GeoOrigin
from .jsonl import iter_jsonl
from .model import EntityKey, EntityState, Vec3

if TYPE_CHECKING:
    from .rpr import RprFrame

_IMPORT_HINT = (
    "pysos_interop.rerun_sink requires the optional 'rerun-sdk' package; "
    "install 'pysos-interop[rerun]'"
)

_MARKER_SIZE_M: Vec3 = (15.0, 12.0, 4.0)

#: Status scalars logged for every entity, in path order.
STATUS_LEAVES: tuple[str, ...] = (
    "status/airspeed_mps",
    "status/altitude_m",
    "status/climb_rate_mps",
)

#: Leaves logged for every entity, in path order.
ENTITY_LEAVES: tuple[str, ...] = ("pose", "trail", "marker", *STATUS_LEAVES)


def _import_rerun() -> Any:
    try:
        import rerun as rr
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise ImportError(_IMPORT_HINT) from exc
    return rr


def entity_slug(key: EntityKey) -> str:
    """Documented slug form: ``<site>_<application>_<entity>``."""

    return f"{key.site}_{key.application}_{key.entity}"


def entity_path(key: EntityKey, leaf: str) -> str:
    """Rerun entity path for one leaf of an entity."""

    return f"world/entity/{entity_slug(key)}/{leaf}"


def _label_path(slug: str) -> str:
    return f"world/entity/{slug}/label"


def rpy_rad_to_quaternion(
    roll_rad: float, pitch_rad: float, yaw_rad: float
) -> tuple[float, float, float, float]:
    """Compose Z-Y-X Euler radians into a ``(x, y, z, w)`` quaternion."""

    half_roll = roll_rad * 0.5
    half_pitch = pitch_rad * 0.5
    half_yaw = yaw_rad * 0.5
    cr, sr = math.cos(half_roll), math.sin(half_roll)
    cp, sp = math.cos(half_pitch), math.sin(half_pitch)
    cy, sy = math.cos(half_yaw), math.sin(half_yaw)
    return (
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )


def _origin_text(origin: GeoOrigin) -> str:
    return (
        "ENU origin (WGS84): "
        f"latitude={origin.latitude_deg:.9f} deg, "
        f"longitude={origin.longitude_deg:.9f} deg, "
        f"altitude={origin.altitude_m:.3f} m"
    )


def _state_of(item: EntityState | RprFrame) -> EntityState:
    state = getattr(item, "state", item)
    if not isinstance(state, EntityState):
        raise TypeError(
            f"observe expects EntityState or RprFrame, got {type(item).__name__}"
        )
    return state


class RerunSink:
    """Log entity states to an ``.rrd`` file.

    Constructing the sink imports ``rerun`` and opens the recording.  Call
    :meth:`observe` with any number of :class:`EntityState` or
    :class:`~pysos_interop.rpr.RprFrame` values, then :meth:`close` to flush
    the file.  It is a context manager.
    """

    def __init__(
        self,
        rrd_path: str | Path,
        *,
        app_id: str = "pysos_interop",
        origin: GeoOrigin | None = None,
        trail_points: int = 200,
        labels: Mapping[str, str] | None = None,
        colors: Mapping[str, tuple[int, int, int]] | None = None,
    ) -> None:
        rr = _import_rerun()
        self._rr = rr
        self.app_id = app_id
        self.rrd_path = Path(rrd_path)
        self.origin = origin or GeoOrigin()
        self.trail_points = max(1, int(trail_points))
        self.labels = dict(labels or {})
        self.colors = dict(colors or {})
        self._histories: dict[str, deque[Vec3]] = {}
        self._closed = False

        self._rec = rr.RecordingStream(app_id)
        self.rrd_path.parent.mkdir(parents=True, exist_ok=True)
        rr.save(str(self.rrd_path), recording=self._rec)
        self._rec.log(
            "world/origin", rr.TextDocument(_origin_text(self.origin)), static=True
        )
        if self.labels:
            self._rec.set_time("sim_time", duration=0.0)
            for slug, label in self.labels.items():
                self._rec.log(
                    _label_path(slug), rr.TextDocument(label), static=True
                )

    def observe(self, item: EntityState | RprFrame) -> None:
        """Log one entity state or decoded RPR frame at its simulation time."""

        if self._closed:
            raise RuntimeError("RerunSink is closed")
        state = _state_of(item)
        slug = entity_slug(state.key)
        self._rec.set_time("sim_time", duration=float(state.timestamp))

        quaternion = rpy_rad_to_quaternion(*state.orientation_rps)
        self._rec.log(
            entity_path(state.key, "pose"),
            self._rr.Transform3D(
                translation=state.position_enu_m, quaternion=quaternion
            ),
        )

        history = self._histories.get(slug)
        if history is None:
            history = deque(maxlen=self.trail_points)
            self._histories[slug] = history
        history.append(state.position_enu_m)
        color = self.colors.get(slug)
        if len(history) >= 2:
            trail_kwargs: dict[str, Any] = {}
            if color is not None:
                trail_kwargs["colors"] = [color]
            self._rec.log(
                entity_path(state.key, "trail"),
                self._rr.LineStrips3D([list(history)], **trail_kwargs),
            )

        marker_kwargs: dict[str, Any] = {}
        if color is not None:
            marker_kwargs["colors"] = [color]
        self._rec.log(
            entity_path(state.key, "marker"),
            self._rr.Boxes3D(
                sizes=[_MARKER_SIZE_M],
                centers=[state.position_enu_m],
                quaternions=[quaternion],
                **marker_kwargs,
            ),
        )

        airspeed = math.sqrt(sum(value * value for value in state.velocity_enu_mps))
        self._rec.log(
            entity_path(state.key, "status/airspeed_mps"),
            self._rr.Scalars(float(airspeed)),
        )
        self._rec.log(
            entity_path(state.key, "status/altitude_m"),
            self._rr.Scalars(float(state.position_enu_m[2])),
        )
        self._rec.log(
            entity_path(state.key, "status/climb_rate_mps"),
            self._rr.Scalars(float(state.velocity_enu_mps[2])),
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._rec.flush()
        disconnect = getattr(self._rec, "disconnect", None)
        if callable(disconnect):
            disconnect()

    def __enter__(self) -> RerunSink:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def recordings_to_rrd(
    jsonl_path: str | Path,
    rrd_path: str | Path,
    *,
    app_id: str = "pysos_interop",
    origin: GeoOrigin | None = None,
    trail_points: int = 200,
    labels: Mapping[str, str] | None = None,
    colors: Mapping[str, tuple[int, int, int]] | None = None,
) -> Path:
    """Turn a recorded JSONL stream into an ``.rrd`` file and return its path.

    The reader is :func:`pysos_interop.jsonl.iter_jsonl`, which also accepts a
    truth stream written by ``TruthRecorder`` because its rows are a superset.

    ``labels`` and ``colors`` are keyed by wire slug
    (``<site>_<application>_<entity>``).  Omit either to keep the previous
    output; no automatic label or palette is invented.
    """

    sink = RerunSink(
        rrd_path,
        app_id=app_id,
        origin=origin,
        trail_points=trail_points,
        labels=labels,
        colors=colors,
    )
    try:
        states: Iterable[EntityState] = iter_jsonl(jsonl_path)
        for state in states:
            sink.observe(state)
    finally:
        sink.close()
    return sink.rrd_path


__all__ = [
    "ENTITY_LEAVES",
    "STATUS_LEAVES",
    "RerunSink",
    "entity_path",
    "entity_slug",
    "recordings_to_rrd",
    "rpy_rad_to_quaternion",
]
