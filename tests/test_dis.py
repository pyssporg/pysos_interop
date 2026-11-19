"""Entity State PDU codec tests, including an independent golden fixture."""

import math
import struct
from pathlib import Path

import pytest

pytest.importorskip("opendis")

from opendis.PduFactory import createPdu  # noqa: E402

from pysos_interop.dis import (  # noqa: E402
    ENTITY_STATE_PDU_TYPE,
    decode_entity_state,
    dis_timestamp,
    encode_entity_state,
)
from pysos_interop.geo import GeoOrigin, enu_velocity_to_ecef  # noqa: E402
from pysos_interop.model import EntityKey, EntityState  # noqa: E402

ORIGIN = GeoOrigin(57.7, 12.0, 100.0)
FIXTURE = Path(__file__).parent / "fixtures" / "entity_state_v7.hex"


def make_state(**changes):
    values = {
        "key": EntityKey(1, 2, 3),
        "timestamp": 12.5,
        "position_enu_m": (1000.0, -500.0, 250.0),
        "velocity_enu_mps": (12.0, 3.0, -0.5),
        "orientation_rps": tuple(math.radians(v) for v in (10.0, -5.0, 123.0)),
        "angular_velocity_rps": (0.01, -0.02, 0.03),
        "marking": "AC-3",
        "force_id": 3,
        "exercise_id": 7,
    }
    values.update(changes)
    return EntityState(**values)


def close_vec(actual, expected, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(actual, expected, strict=True))


def test_golden_entity_state_decodes_known_conventions():
    data = bytes.fromhex(FIXTURE.read_text(encoding="ascii").strip())
    assert len(data) == 144
    assert data[0] == 7
    assert data[1] == 3
    assert data[2] == ENTITY_STATE_PDU_TYPE
    assert struct.unpack_from(">I", data, 4)[0] == 0x01020304

    state = decode_entity_state(data, origin=ORIGIN)
    assert state.key == EntityKey(1, 1, 7)
    assert state.marking == "GOLD-7"
    assert state.force_id == 2
    assert state.exercise_id == 3
    assert close_vec(state.position_enu_m, (1000.0, -500.0, 250.0), 1e-3)
    assert close_vec(
        state.orientation_rps,
        tuple(math.radians(v) for v in (10.0, -5.0, 123.0)),
        1e-5,
    )
    assert close_vec(state.velocity_enu_mps, (12.0, 3.0, -0.5), 1e-3)


def test_encode_sets_header_identity_and_length():
    data = encode_entity_state(make_state(), origin=ORIGIN, timestamp=0x01020304)
    assert len(data) == 144
    assert data[0] == 7
    assert data[1] == 7
    assert data[2] == ENTITY_STATE_PDU_TYPE
    assert struct.unpack_from(">I", data, 4)[0] == 0x01020304
    assert struct.unpack_from(">H", data, 8)[0] == 144


def test_encode_decode_reencode_is_stable():
    state = make_state()
    encoded = encode_entity_state(state, origin=ORIGIN)
    decoded = decode_entity_state(encoded, origin=ORIGIN)

    assert decoded.key == state.key
    assert decoded.marking == state.marking
    assert decoded.force_id == state.force_id
    assert decoded.exercise_id == state.exercise_id
    assert decoded.timestamp == pytest.approx(state.timestamp, abs=2e-3)
    assert close_vec(decoded.position_enu_m, state.position_enu_m, 1e-3)
    assert close_vec(decoded.orientation_rps, state.orientation_rps, 1e-6)
    assert close_vec(decoded.velocity_enu_mps, state.velocity_enu_mps, 1e-3)
    assert close_vec(decoded.angular_velocity_rps, state.angular_velocity_rps, 1e-6)

    assert encode_entity_state(decoded, origin=ORIGIN) == encoded


def test_algorithm_four_velocity_is_body_frame():
    state = make_state(
        orientation_rps=(0.0, 0.0, 0.0),
        velocity_enu_mps=(10.0, 0.0, 0.0),
    )
    pdu = createPdu(encode_entity_state(state, origin=ORIGIN, dr_algorithm=4))
    wire = pdu.entityLinearVelocity
    assert (wire.x, wire.y, wire.z) == pytest.approx((0.0, 10.0, 0.0), abs=1e-5)
    decoded = decode_entity_state(encode_entity_state(state, origin=ORIGIN), origin=ORIGIN)
    assert decoded.velocity_enu_mps == pytest.approx(state.velocity_enu_mps, abs=1e-4)


def test_algorithm_two_velocity_is_ecef():
    state = make_state()
    pdu = createPdu(encode_entity_state(state, origin=ORIGIN, dr_algorithm=2))
    wire = pdu.entityLinearVelocity
    expected = enu_velocity_to_ecef(state.velocity_enu_mps, ORIGIN)
    assert (wire.x, wire.y, wire.z) == pytest.approx(expected, abs=1e-4)
    encoded = encode_entity_state(state, origin=ORIGIN, dr_algorithm=2)
    decoded = decode_entity_state(encoded, origin=ORIGIN)
    assert decoded.velocity_enu_mps == pytest.approx(state.velocity_enu_mps, abs=1e-3)


def test_wire_angular_velocity_is_body_rates_only_when_rotating():
    state = make_state(orientation_rps=(0.2, 0.1, 0.7))
    rotating = createPdu(encode_entity_state(state, origin=ORIGIN, dr_algorithm=4))
    wire = rotating.deadReckoningParameters.entityAngularVelocity
    assert (wire.x, wire.y, wire.z) == pytest.approx(state.angular_velocity_rps, abs=1e-6)
    decoded = decode_entity_state(encode_entity_state(state, origin=ORIGIN), origin=ORIGIN)
    assert decoded.angular_velocity_rps == pytest.approx(state.angular_velocity_rps, abs=1e-6)

    linear = createPdu(encode_entity_state(make_state(), origin=ORIGIN, dr_algorithm=2))
    wire = linear.deadReckoningParameters.entityAngularVelocity
    assert (wire.x, wire.y, wire.z) == (0.0, 0.0, 0.0)


def test_dis_timestamp_ticks_hour_wrap_and_absolute_bit():
    assert dis_timestamp(0.0) == 0
    assert dis_timestamp(3600.0) == 0
    assert dis_timestamp(1800.0) == 1 << 30
    assert dis_timestamp(1800.0, relative=False) == (1 << 30) | 0x80000000


def test_unsupported_encode_algorithm_raises():
    with pytest.raises(ValueError, match="Unsupported dead-reckoning algorithm"):
        encode_entity_state(make_state(), dr_algorithm=3)


def test_invalid_buffers_are_rejected():
    comment = struct.pack(">BBBBLH", 7, 1, 22, 0, 0, 12) + b"\x00\x00"
    with pytest.raises(ValueError, match="Not an Entity State PDU"):
        decode_entity_state(comment)
    with pytest.raises(ValueError, match="shorter than a DIS PDU header"):
        decode_entity_state(b"\x07\x01")
