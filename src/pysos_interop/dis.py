"""IEEE 1278.1 Entity State PDU codec.

Mapping at the protocol boundary:

* model position/velocity are local ENU; DIS location is WGS84 ECEF;
* model orientation is ``(roll, pitch, yaw)`` radians; the wire Euler angles
  are ``(psi, theta, phi)`` = ``(yaw, pitch, roll)`` radians;
* wire linear velocity follows the dead-reckoning algorithm: ECEF for
  algorithms 1 and 2, body axes for algorithm 4;
* wire angular velocity is always about the body axes, which is exactly what
  :attr:`~pysos_interop.model.EntityState.angular_velocity_rps` stores.

The optional ``opendis`` dependency is imported here, so importing
``pysos_interop`` never needs it.
"""

from __future__ import annotations

import io
import math
import struct

from .geo import (
    GeoOrigin,
    ecef_to_enu,
    ecef_velocity_to_enu,
    enu_to_ecef,
    enu_velocity_to_ecef,
)
from .model import EntityKey, EntityState, Vec3

try:  # pragma: no cover - exercised by the optional-extra test
    from opendis.dis7 import (
        DeadReckoningParameters,
        EntityMarking,
        EntityStatePdu,
    )
    from opendis.dis7 import (
        EntityType as DisEntityType,
    )
    from opendis.PduFactory import createPdu
    from opendis.record.common import (
        EntityIdentifier,
        EulerAngles,
        SimulationAddress,
        Vector3Float,
        WorldCoordinates,
    )
    from opendis.stream import DataOutputStream
except ImportError as exc:  # pragma: no cover - depends on the environment
    raise ImportError(
        "pysos_interop.dis requires the optional 'opendis' package; "
        "install 'pysos-interop[dis]'"
    ) from exc

ENTITY_STATE_PDU_TYPE = 1
PROTOCOL_VERSION = 7
PDU_HEADER_LEN = 12
TICKS_PER_HOUR = 1 << 31
RELATIVE_TIMESTAMP_MASK = 0x7FFFFFFF

STATIC = 1
LINEAR = 2
ROTATING = 4
ENCODE_ALGORITHMS = frozenset({STATIC, LINEAR, ROTATING})
BODY_FRAME_ALGORITHMS = frozenset({4, 7, 8})

# Entity type is identity metadata outside this hub contract.  A neutral
# platform/air entry keeps the PDU well formed for every producer.
DEFAULT_ENTITY_TYPE = (1, 2, 0, 0, 0, 0, 0)

Vec3Matrix = tuple[Vec3, Vec3, Vec3]


def dis_timestamp(timestamp_s: float, *, relative: bool = True) -> int:
    """Return a DIS header timestamp for ``timestamp_s`` seconds.

    The low 31 bits are hour-relative ticks of ``2**-31`` hour.  With
    ``relative=False`` the absolute-time bit (31) is set.
    """

    seconds = float(timestamp_s) % 3600.0
    ticks = int(seconds * TICKS_PER_HOUR / 3600.0) & RELATIVE_TIMESTAMP_MASK
    return ticks if relative else ticks | 0x80000000


def _seconds_from_dis_timestamp(raw: int) -> float:
    ticks = int(raw) & RELATIVE_TIMESTAMP_MASK
    return ticks * 3600.0 / TICKS_PER_HOUR


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
    return str(marking).encode("ascii", "ignore").decode("ascii")[:11]


def _marking_record(marking: str) -> EntityMarking:
    record = EntityMarking(characterSet=1)
    record.setString(_clean_marking(marking))
    return record


def encode_entity_state(
    state: EntityState,
    *,
    origin: GeoOrigin | None = None,
    dr_algorithm: int = 4,
    timestamp: int | None = None,
) -> bytes:
    """Serialise one Entity State PDU.

    ``origin`` places the local ENU frame; it defaults to the WGS84 point at
    0 latitude, 0 longitude, 0 altitude.  ``timestamp`` overrides the raw DIS
    header timestamp; otherwise it is derived from ``state.timestamp``.
    """

    dr_algorithm = int(dr_algorithm)
    if dr_algorithm not in ENCODE_ALGORITHMS:
        raise ValueError(f"Unsupported dead-reckoning algorithm: {dr_algorithm}")
    frame = GeoOrigin() if origin is None else origin

    key = state.key
    position_ecef = enu_to_ecef(state.position_enu_m, frame)
    if dr_algorithm == ROTATING:
        velocity_wire = _enu_velocity_to_body(state.velocity_enu_mps, state.orientation_rps)
        angular_wire = tuple(float(value) for value in state.angular_velocity_rps)
    else:
        velocity_wire = enu_velocity_to_ecef(state.velocity_enu_mps, frame)
        angular_wire = (0.0, 0.0, 0.0)

    roll, pitch, yaw = (float(value) for value in state.orientation_rps)
    pdu = EntityStatePdu(
        entityID=EntityIdentifier(
            SimulationAddress(int(key.site), int(key.application)),
            int(key.entity),
        ),
        forceId=int(state.force_id) & 0xFF,
        entityType=DisEntityType(*DEFAULT_ENTITY_TYPE),
        entityLinearVelocity=Vector3Float(*velocity_wire),
        entityLocation=WorldCoordinates(*position_ecef),
        entityOrientation=EulerAngles(yaw, pitch, roll),
        deadReckoningParameters=DeadReckoningParameters(
            deadReckoningAlgorithm=dr_algorithm,
            entityLinearAcceleration=Vector3Float(),
            entityAngularVelocity=Vector3Float(*angular_wire),
        ),
        marking=_marking_record(state.marking),
    )
    pdu.protocolVersion = PROTOCOL_VERSION
    pdu.exerciseID = int(state.exercise_id) & 0xFF
    pdu.timestamp = (
        dis_timestamp(state.timestamp) if timestamp is None else int(timestamp) & 0xFFFFFFFF
    )

    buffer = io.BytesIO()
    pdu.serialize(DataOutputStream(buffer))
    data = bytearray(buffer.getvalue())
    if len(data) < PDU_HEADER_LEN:
        raise ValueError("opendis produced a truncated Entity State PDU")
    struct.pack_into(">H", data, 8, len(data))
    return bytes(data)


def _first_pdu(data: bytes) -> bytes:
    if len(data) < PDU_HEADER_LEN:
        raise ValueError("Data is shorter than a DIS PDU header")
    length = struct.unpack_from(">H", data, 8)[0]
    if length < PDU_HEADER_LEN or length > len(data):
        raise ValueError(f"Invalid DIS PDU length: {length}")
    return bytes(data[:length])


def decode_entity_state(data: bytes, *, origin: GeoOrigin | None = None) -> EntityState:
    """Decode the first Entity State PDU in ``data``.

    ``ValueError`` is raised when the buffer does not contain an Entity State
    PDU.  The state timestamp comes from the PDU header (hour-relative, so it
    wraps every hour), not from wall-clock receive time.
    """

    frame = GeoOrigin() if origin is None else origin
    pdu_bytes = _first_pdu(data)
    if pdu_bytes[2] != ENTITY_STATE_PDU_TYPE:
        raise ValueError(f"Not an Entity State PDU: type {pdu_bytes[2]}")
    pdu = createPdu(pdu_bytes)
    if pdu is None or getattr(pdu, "pduType", None) != ENTITY_STATE_PDU_TYPE:
        raise ValueError("opendis could not decode the Entity State PDU")

    location = pdu.entityLocation
    position_enu = ecef_to_enu((location.x, location.y, location.z), frame)
    orientation = (
        float(pdu.entityOrientation.phi),
        float(pdu.entityOrientation.theta),
        float(pdu.entityOrientation.psi),
    )

    velocity = pdu.entityLinearVelocity
    velocity_wire = (float(velocity.x), float(velocity.y), float(velocity.z))
    dr_algorithm = int(pdu.deadReckoningParameters.deadReckoningAlgorithm)
    if dr_algorithm in BODY_FRAME_ALGORITHMS:
        velocity_enu = _body_velocity_to_enu(velocity_wire, orientation)
    else:
        velocity_enu = ecef_velocity_to_enu(velocity_wire, frame)

    angular = pdu.deadReckoningParameters.entityAngularVelocity
    angular_velocity = (float(angular.x), float(angular.y), float(angular.z))
    identifier = pdu.entityID

    return EntityState(
        key=EntityKey(
            int(identifier.simulationAddress.site),
            int(identifier.simulationAddress.application),
            int(identifier.entityNumber),
        ),
        timestamp=_seconds_from_dis_timestamp(pdu.timestamp),
        position_enu_m=position_enu,
        velocity_enu_mps=velocity_enu,
        orientation_rps=orientation,
        angular_velocity_rps=angular_velocity,
        marking=pdu.marking.charactersString(),
        force_id=int(pdu.forceId),
        exercise_id=int(pdu.exerciseID),
    )
