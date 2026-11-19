"""RPR-derived protobuf frame codec and UDP channel adapter.

This module is the optional bridge between the neutral :class:`EntityState`
and the RPR-derived vocabulary in :mod:`pysos_rpr.messages`.  It never changes
``EntityState`` and it never imports the DIS codec.

Frame contract
--------------
A frame is one encoded protobuf message of type ``PhysicalEntity``,
``Platform`` or ``Aircraft`` from ``pysos_rpr.messages``.  The payload carries
no transport header, so it has no sequence number and no timestamp.  Callers
that need either supply it explicitly:

* :func:`decode_frame` accepts ``timestamp`` (default ``0.0``) for the decoded
  :class:`EntityState`.
* :class:`RprJsonlRecorder` records optional ``sequence`` and ``timestamp``
  next to the payload bytes.

Spatial conventions, from ``pysos_rpr``:

* position (``Spatial.world_location``) is geocentric ECEF metres;
* linear velocity and acceleration are body-frame metres per second and
  metres per second squared;
* orientation is Euler ``(psi, theta, phi)`` = ``(yaw, pitch, roll)`` radians;
* angular velocity is body-frame radians per second;
* ``Spatial.dead_reckoning`` carries the algorithm selector and its 15-octet
  parameter block.

Origin contract
---------------
RPR position is ECEF, while :class:`EntityState` position is local ENU.  There
is no way to infer the local frame from a frame, so every encode and decode
requires an explicit :class:`RprOrigin`.  The origin is a WGS84 geodetic point
or an ECEF reference point (:meth:`RprOrigin.from_ecef`); it defines the local
east-north-up frame through :mod:`pysos_interop.geo`.  There is deliberately no
default and no process-wide origin.

Preserved versus dropped data
-----------------------------
Preserved across a round trip: identity ``(site, application, entity)``,
position, velocity, orientation, angular velocity, marking, force, the
dead-reckoning algorithm and parameter bytes, body acceleration,
``is_frozen``, entity type, platform kind, and marking character set.  Those
live in :class:`RprExtras`, because :class:`EntityState` has no field for them.

Dropped: ``EntityState.exercise_id`` and ``EntityState.timestamp``.  The RPR
vocabulary has no exercise or time field, so encode ignores both and decode
returns ``exercise_id=1`` plus the explicit decode timestamp.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .geo import (
    GeoOrigin,
    ecef_to_enu,
    ecef_to_geodetic,
    enu_to_ecef,
    geodetic_to_ecef,
)
from .model import EntityKey, EntityState, Vec3
from .transport import Channel

try:  # pragma: no cover - exercised by the optional-extra import test
    from google.protobuf.message import Message
    from pysos_rpr import messages as _rpr
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(
        "pysos_interop.rpr requires the optional 'pysos-rpr' package; "
        "install 'pysos-interop[rpr]'"
    ) from exc

DEFAULT_ENTITY_TYPE = (1, 2, 0, 0, 0, 0, 0)
DEFAULT_DR_ALGORITHM = 4

Vec3Matrix = tuple[Vec3, Vec3, Vec3]


@dataclass(frozen=True)
class RprOrigin:
    """WGS84 point that defines the local east-north-up frame.

    The three fields are latitude and longitude in degrees and altitude in
    metres.  :meth:`from_ecef` converts an ECEF reference point first.
    """

    latitude_deg: float
    longitude_deg: float
    altitude_m: float

    @classmethod
    def from_ecef(cls, ecef_m: Vec3) -> RprOrigin:
        """Build the origin from an ECEF reference point in metres."""

        latitude_deg, longitude_deg, altitude_m = ecef_to_geodetic(ecef_m)
        return cls(latitude_deg, longitude_deg, altitude_m)

    @property
    def geo(self) -> GeoOrigin:
        """Return the equivalent :class:`~pysos_interop.geo.GeoOrigin`."""

        return GeoOrigin(self.latitude_deg, self.longitude_deg, self.altitude_m)

    @property
    def ecef_m(self) -> Vec3:
        """Return the origin as an ECEF point in metres."""

        return geodetic_to_ecef(self.latitude_deg, self.longitude_deg, self.altitude_m)


@dataclass(frozen=True)
class RprExtras:
    """RPR data that has no field in :class:`EntityState`."""

    algorithm: int = DEFAULT_DR_ALGORITHM
    parameters: bytes = b""
    acceleration_body_mps2: Vec3 = (0.0, 0.0, 0.0)
    is_frozen: bool = False
    entity_type: tuple[int, ...] | None = None
    platform_kind: int = 0
    marking_character_set: int = 1


@dataclass(frozen=True)
class RprFrame:
    """One decoded frame: neutral state plus the RPR-only remainder."""

    state: EntityState
    extras: RprExtras
    message: Message


@dataclass(frozen=True)
class RprRecord:
    """One recorded RPR payload and its optional out-of-band metadata."""

    payload: bytes
    sequence: int | None = None
    timestamp: float | None = None


def _body_to_enu_rotation(euler: Vec3) -> Vec3Matrix:
    roll, pitch, yaw = (float(value) for value in euler)
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    north = (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr)
    east = (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr)
    down = (-sp, cp * sr, cp * cr)
    return (east, north, tuple(-value for value in down))


def _apply(matrix: Vec3Matrix, vector: Vec3) -> Vec3:
    return tuple(  # type: ignore[return-value]
        row[0] * vector[0] + row[1] * vector[1] + row[2] * vector[2]
        for row in matrix
    )


def _apply_transpose(matrix: Vec3Matrix, vector: Vec3) -> Vec3:
    return tuple(  # type: ignore[return-value]
        matrix[0][i] * vector[0] + matrix[1][i] * vector[1] + matrix[2][i] * vector[2]
        for i in range(3)
    )


def _enu_velocity_to_body(velocity_enu: Vec3, euler: Vec3) -> Vec3:
    return _apply_transpose(_body_to_enu_rotation(euler), velocity_enu)


def _body_velocity_to_enu(velocity_body: Vec3, euler: Vec3) -> Vec3:
    return _apply(_body_to_enu_rotation(euler), velocity_body)


def _clean_marking(marking: str) -> str:
    printable = "".join(char for char in str(marking) if char.isprintable())
    encoded = printable.encode("utf-8")[:11]
    return encoded.decode("utf-8", "ignore")


def _check_message_type(message_type: type[Message]) -> None:
    if message_type not in (_rpr.PhysicalEntity, _rpr.Platform, _rpr.Aircraft):
        raise TypeError(
            "message_type must be PhysicalEntity, Platform or Aircraft"
        )


def _unwrap_physical(message: Message) -> tuple[Message, int]:
    if isinstance(message, _rpr.Aircraft):
        if not message.HasField("platform") or not message.platform.HasField("physical"):
            raise ValueError("RPR Aircraft is missing platform.physical")
        return message.platform.physical, int(message.platform.kind)
    if isinstance(message, _rpr.Platform):
        if not message.HasField("physical"):
            raise ValueError("RPR Platform is missing physical")
        return message.physical, int(message.kind)
    if isinstance(message, _rpr.PhysicalEntity):
        return message, 0
    raise TypeError(f"Cannot read RPR state from {type(message).__name__}")


def _spatial_from_entity(
    state: EntityState,
    origin: RprOrigin,
    extras: RprExtras,
) -> Message:
    position_ecef = enu_to_ecef(state.position_enu_m, origin.geo)
    velocity_body = _enu_velocity_to_body(state.velocity_enu_mps, state.orientation_rps)
    roll, pitch, yaw = (float(value) for value in state.orientation_rps)
    angular_x, angular_y, angular_z = (
        float(value) for value in state.angular_velocity_rps
    )
    acceleration_x, acceleration_y, acceleration_z = (
        float(value) for value in extras.acceleration_body_mps2
    )
    return _rpr.spatial_ecef(
        x=position_ecef[0],
        y=position_ecef[1],
        z=position_ecef[2],
        psi=yaw,
        theta=pitch,
        phi=roll,
        vx=velocity_body[0],
        vy=velocity_body[1],
        vz=velocity_body[2],
        ax=acceleration_x,
        ay=acceleration_y,
        az=acceleration_z,
        wx=angular_x,
        wy=angular_y,
        wz=angular_z,
        is_frozen=bool(extras.is_frozen),
        algorithm=int(extras.algorithm),
        parameters=bytes(extras.parameters),
    )


def _entity_type_from_extras(
    extras: RprExtras,
    entity_type: tuple[int, ...] | None,
) -> Message:
    values = entity_type
    if values is None and extras.entity_type is not None:
        values = extras.entity_type
    if values is None:
        values = DEFAULT_ENTITY_TYPE
    values = tuple(int(value) for value in values)
    if len(values) != 7:
        raise ValueError("entity_type must have seven octets")
    return _rpr.entity_type(
        kind=values[0],
        domain=values[1],
        country=values[2],
        category=values[3],
        subcategory=values[4],
        specific=values[5],
        extra=values[6],
    )


def to_rpr_message(
    state: EntityState,
    *,
    origin: RprOrigin,
    extras: RprExtras | None = None,
    message_type: type[Message] = _rpr.PhysicalEntity,
    entity_type: tuple[int, ...] | None = None,
) -> Message:
    """Build an RPR message from a neutral state.

    ``entity_type`` overrides :attr:`RprExtras.entity_type` and the neutral
    default.  ``message_type`` selects ``PhysicalEntity``, ``Platform`` or
    ``Aircraft``.  The output velocity is body-frame and the position is ECEF,
    both defined by ``origin``.
    """

    _check_message_type(message_type)
    values = RprExtras() if extras is None else extras
    identifier = _rpr.entity_identifier(
        site=int(state.key.site),
        application=int(state.key.application),
        entity=int(state.key.entity),
    )
    marking = _rpr.marking(
        _clean_marking(state.marking),
        character_set=int(values.marking_character_set),
    )
    physical = _rpr.entity_state(
        entity_identifier=identifier,
        entity_type=_entity_type_from_extras(values, entity_type),
        force=int(state.force_id),
        marking=marking,
        spatial=_spatial_from_entity(state, origin, values),
    )
    if message_type is _rpr.PhysicalEntity:
        return physical
    platform = _rpr.platform(physical=physical, kind=int(values.platform_kind))
    if message_type is _rpr.Platform:
        return platform
    return _rpr.aircraft(platform=platform)


def encode_entity_state(
    state: EntityState,
    *,
    origin: RprOrigin,
    extras: RprExtras | None = None,
    message_type: type[Message] = _rpr.PhysicalEntity,
    entity_type: tuple[int, ...] | None = None,
) -> bytes:
    """Encode a neutral state as one deterministic RPR payload."""

    return _rpr.encode(
        to_rpr_message(
            state,
            origin=origin,
            extras=extras,
            message_type=message_type,
            entity_type=entity_type,
        )
    )


def _extract_state(
    message: Message,
    origin: RprOrigin,
    timestamp: float,
) -> RprFrame:
    physical, platform_kind = _unwrap_physical(message)
    if not physical.HasField("base"):
        raise ValueError("RPR PhysicalEntity is missing base")
    if not physical.HasField("spatial"):
        raise ValueError("RPR PhysicalEntity is missing spatial")

    base = physical.base
    spatial = physical.spatial
    if not base.HasField("entity_identifier"):
        raise ValueError("RPR BaseEntity is missing entity_identifier")
    identifier = base.entity_identifier
    key = EntityKey(
        int(identifier.site),
        int(identifier.application),
        int(identifier.entity),
    )

    if not spatial.HasField("world_location"):
        raise ValueError("RPR Spatial is missing world_location")
    location = spatial.world_location
    position_enu = ecef_to_enu((location.x, location.y, location.z), origin.geo)

    if spatial.HasField("orientation"):
        orientation = (
            float(spatial.orientation.phi),
            float(spatial.orientation.theta),
            float(spatial.orientation.psi),
        )
    else:
        orientation = (0.0, 0.0, 0.0)

    if spatial.HasField("velocity"):
        velocity_body = (
            float(spatial.velocity.x),
            float(spatial.velocity.y),
            float(spatial.velocity.z),
        )
        velocity_enu = _body_velocity_to_enu(velocity_body, orientation)
    else:
        velocity_enu = (0.0, 0.0, 0.0)

    if spatial.HasField("angular_velocity"):
        angular_velocity = (
            float(spatial.angular_velocity.x),
            float(spatial.angular_velocity.y),
            float(spatial.angular_velocity.z),
        )
    else:
        angular_velocity = (0.0, 0.0, 0.0)

    if spatial.HasField("acceleration"):
        acceleration = (
            float(spatial.acceleration.x),
            float(spatial.acceleration.y),
            float(spatial.acceleration.z),
        )
    else:
        acceleration = (0.0, 0.0, 0.0)

    algorithm = 0
    parameters = b""
    if spatial.HasField("dead_reckoning"):
        algorithm = int(spatial.dead_reckoning.algorithm)
        parameters = bytes(spatial.dead_reckoning.parameters)

    entity_type = None
    if base.HasField("entity_type"):
        record = base.entity_type
        entity_type = (
            int(record.kind),
            int(record.domain),
            int(record.country),
            int(record.category),
            int(record.subcategory),
            int(record.specific),
            int(record.extra),
        )

    marking = ""
    character_set = 1
    if base.HasField("marking"):
        marking = str(base.marking.characters)
        character_set = int(base.marking.character_set)

    state = EntityState(
        key=key,
        timestamp=float(timestamp),
        position_enu_m=position_enu,
        velocity_enu_mps=velocity_enu,
        orientation_rps=orientation,
        angular_velocity_rps=angular_velocity,
        marking=marking,
        force_id=int(base.force),
    )
    extras = RprExtras(
        algorithm=algorithm,
        parameters=parameters,
        acceleration_body_mps2=acceleration,
        is_frozen=bool(spatial.is_frozen),
        entity_type=entity_type,
        platform_kind=platform_kind,
        marking_character_set=character_set,
    )
    return RprFrame(state=state, extras=extras, message=message)


def decode_frame(
    data: bytes | bytearray | memoryview,
    *,
    origin: RprOrigin,
    message_type: type[Message] = _rpr.PhysicalEntity,
    strict: bool = True,
    timestamp: float = 0.0,
) -> RprFrame:
    """Decode one RPR payload into a neutral state plus RPR-only extras.

    ``strict`` is forwarded to :func:`pysos_rpr.messages.decode`: ``True``
    rejects unknown fields, ``False`` preserves them on ``RprFrame.message``
    so re-encoding is byte-identical.  The RPR vocabulary has no time field;
    ``timestamp`` supplies the value placed on the returned state.
    """

    _check_message_type(message_type)
    message = _rpr.decode(message_type, data, strict=strict)
    return _extract_state(message, origin, timestamp)


def decode_entity_state(
    data: bytes | bytearray | memoryview,
    *,
    origin: RprOrigin,
    message_type: type[Message] = _rpr.PhysicalEntity,
    strict: bool = True,
    timestamp: float = 0.0,
) -> EntityState:
    """Decode one RPR payload and return only its neutral state."""

    return decode_frame(
        data,
        origin=origin,
        message_type=message_type,
        strict=strict,
        timestamp=timestamp,
    ).state


class RprChannel:
    """Synchronous RPR source/sink over one :class:`~pysos_interop.transport.Channel`.

    The adapter owns no socket and starts no thread.  :meth:`send` encodes one
    state and forwards the datagram; :meth:`recv` reads one datagram and
    decodes it.  Open and close are delegated to the wrapped channel.
    """

    def __init__(
        self,
        channel: Channel,
        *,
        origin: RprOrigin,
        message_type: type[Message] = _rpr.PhysicalEntity,
        strict: bool = True,
    ) -> None:
        _check_message_type(message_type)
        self.channel = channel
        self.origin = origin
        self.message_type = message_type
        self.strict = strict

    def open(self) -> RprChannel:
        self.channel.open()
        return self

    def close(self) -> None:
        self.channel.close()

    def recv(
        self,
        timeout: float | None = None,
        *,
        timestamp: float = 0.0,
    ) -> RprFrame:
        """Receive and decode one frame."""

        return decode_frame(
            self.channel.recv(timeout),
            origin=self.origin,
            message_type=self.message_type,
            strict=self.strict,
            timestamp=timestamp,
        )

    def send(
        self,
        state: EntityState,
        *,
        extras: RprExtras | None = None,
    ) -> int:
        """Encode and send one state, returning the datagram length."""

        return self.channel.send(
            encode_entity_state(
                state,
                origin=self.origin,
                extras=extras,
                message_type=self.message_type,
            )
        )

    def __enter__(self) -> RprChannel:
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class RprJsonlRecorder:
    """Append RPR payloads as JSON Lines with optional sequence and timestamp.

    This is a separate file format from :class:`pysos_interop.jsonl.JsonlRecorder`.
    It records the encoded payload, not a decoded state, so replay goes back
    through the same decoder and unknown fields survive.  The DIS recording
    format is untouched.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file = self.path.open("w", encoding="utf-8")

    def write(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        sequence: int | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Write one payload as a single line and flush it."""

        record: dict[str, Any] = {
            "kind": "rpr",
            "payload_hex": bytes(payload).hex(),
        }
        if sequence is not None:
            record["sequence"] = int(sequence)
        if timestamp is not None:
            record["timestamp"] = float(timestamp)
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._file.flush()

    def write_frame(
        self,
        frame: RprFrame,
        *,
        sequence: int | None = None,
        timestamp: float | None = None,
    ) -> None:
        """Re-encode and write a decoded frame, keeping unknown fields."""

        self.write(_rpr.encode(frame.message), sequence=sequence, timestamp=timestamp)

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()

    def __enter__(self) -> RprJsonlRecorder:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def iter_rpr_jsonl(path: str | Path) -> Iterator[RprRecord]:
    """Yield the RPR records in ``path``, in file order."""

    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                if data.get("kind") != "rpr":
                    raise ValueError("not an RPR record")
                sequence = data.get("sequence")
                timestamp = data.get("timestamp")
                record = RprRecord(
                    payload=bytes.fromhex(data["payload_hex"]),
                    sequence=None if sequence is None else int(sequence),
                    timestamp=None if timestamp is None else float(timestamp),
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid RPR record on line {line_number} of {path}: {exc}"
                ) from exc
            yield record


def iter_rpr_frames(
    path: str | Path,
    *,
    origin: RprOrigin,
    message_type: type[Message] = _rpr.PhysicalEntity,
    strict: bool = True,
) -> Iterator[RprFrame]:
    """Decode the recorded payloads, using each record's timestamp when present."""

    for record in iter_rpr_jsonl(path):
        timestamp = 0.0 if record.timestamp is None else record.timestamp
        yield decode_frame(
            record.payload,
            origin=origin,
            message_type=message_type,
            strict=strict,
            timestamp=timestamp,
        )


def replay_rpr_jsonl(
    path: str | Path,
    channel: Channel,
    *,
    origin: RprOrigin,
    message_type: type[Message] = _rpr.PhysicalEntity,
    strict: bool = True,
) -> int:
    """Decode and send every recorded payload, returning the frame count.

    The original payload bytes are sent, not a re-encoding, so the receiver
    sees exactly what was recorded.
    """

    count = 0
    for record in iter_rpr_jsonl(path):
        decode_frame(
            record.payload,
            origin=origin,
            message_type=message_type,
            strict=strict,
            timestamp=0.0 if record.timestamp is None else record.timestamp,
        )
        channel.send(record.payload)
        count += 1
    return count


__all__ = [
    "DEFAULT_DR_ALGORITHM",
    "DEFAULT_ENTITY_TYPE",
    "RprChannel",
    "RprExtras",
    "RprFrame",
    "RprJsonlRecorder",
    "RprOrigin",
    "RprRecord",
    "decode_entity_state",
    "decode_frame",
    "encode_entity_state",
    "iter_rpr_frames",
    "iter_rpr_jsonl",
    "replay_rpr_jsonl",
    "to_rpr_message",
]
