"""RPR frame codec, origin, channel adapter and recording tests."""

import math
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pysos_rpr")

from pysos_rpr import messages as rpr  # noqa: E402

from pysos_interop.geo import ecef_to_enu, enu_to_ecef  # noqa: E402
from pysos_interop.model import EntityKey, EntityState  # noqa: E402
from pysos_interop.rpr import (  # noqa: E402
    RprChannel,
    RprExtras,
    RprJsonlRecorder,
    RprOrigin,
    decode_frame,
    encode_entity_state,
    iter_rpr_frames,
    iter_rpr_jsonl,
    replay_rpr_jsonl,
    to_rpr_message,
)
from pysos_interop.transport import Channel  # noqa: E402

ORIGIN = RprOrigin(57.7, 12.0, 100.0)


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


def free_udp_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def test_entity_state_round_trip_at_non_zero_origin():
    state = make_state()
    extras = RprExtras(
        algorithm=4,
        parameters=bytes(range(15)),
        acceleration_body_mps2=(0.4, -0.5, 0.6),
        is_frozen=True,
        entity_type=(1, 2, 840, 1, 2, 3, 4),
        marking_character_set=1,
    )

    payload = encode_entity_state(state, origin=ORIGIN, extras=extras)
    frame = decode_frame(payload, origin=ORIGIN, timestamp=state.timestamp)

    assert frame.state.key == state.key
    assert frame.state.position_enu_m == pytest.approx(state.position_enu_m, abs=1e-4)
    assert frame.state.velocity_enu_mps == pytest.approx(state.velocity_enu_mps, abs=1e-4)
    assert frame.state.orientation_rps == pytest.approx(state.orientation_rps, abs=1e-5)
    assert frame.state.angular_velocity_rps == pytest.approx(
        state.angular_velocity_rps, abs=1e-6
    )
    assert frame.state.marking == state.marking
    assert frame.state.force_id == state.force_id
    assert frame.state.timestamp == state.timestamp
    assert frame.state.exercise_id == 1
    assert frame.extras.algorithm == extras.algorithm
    assert frame.extras.parameters == extras.parameters
    assert frame.extras.acceleration_body_mps2 == pytest.approx(
        extras.acceleration_body_mps2, abs=1e-6
    )
    assert frame.extras.is_frozen == extras.is_frozen
    assert frame.extras.entity_type == extras.entity_type
    assert frame.extras.marking_character_set == extras.marking_character_set


def test_velocity_is_body_frame_on_the_wire():
    state = make_state(
        orientation_rps=(0.0, 0.0, 0.0),
        velocity_enu_mps=(10.0, 0.0, 0.0),
    )
    message = to_rpr_message(state, origin=ORIGIN)
    velocity = message.spatial.velocity

    # Zero attitude: body x is north and body y is east, so east 10 m/s is
    # body y 10 m/s.  This is the same convention as DIS algorithm 4.
    assert (velocity.x, velocity.y, velocity.z) == pytest.approx(
        (0.0, 10.0, 0.0), abs=1e-5
    )


def test_ecef_enu_known_point_and_ecef_origin():
    equator = RprOrigin(0.0, 0.0, 0.0)
    assert enu_to_ecef((0.0, 0.0, 100.0), equator.geo) == pytest.approx(
        (6378237.0, 0.0, 0.0), abs=1e-6
    )
    assert ecef_to_enu((6378237.0, 0.0, 0.0), equator.geo) == pytest.approx(
        (0.0, 0.0, 100.0), abs=1e-6
    )

    converted = RprOrigin.from_ecef((6378237.0, 0.0, 0.0))
    assert (converted.latitude_deg, converted.longitude_deg, converted.altitude_m) == (
        pytest.approx(0.0, abs=1e-9),
        pytest.approx(0.0, abs=1e-9),
        pytest.approx(100.0, abs=1e-6),
    )

    message = rpr.entity_state(
        entity_identifier=rpr.entity_identifier(site=1, application=1, entity=1),
        entity_type=rpr.entity_type(kind=1, domain=2, country=0),
        force="FORCE_FRIENDLY",
        spatial=rpr.spatial_ecef(x=6378237.0, y=0.0, z=0.0),
    )
    frame = decode_frame(rpr.encode(message), origin=equator)
    assert frame.state.position_enu_m == pytest.approx((0.0, 0.0, 100.0), abs=1e-6)


def test_aircraft_wrapper_carries_platform_kind():
    state = make_state()
    extras = RprExtras(platform_kind=1, entity_type=(1, 2, 0, 0, 0, 0, 0))
    payload = encode_entity_state(
        state, origin=ORIGIN, extras=extras, message_type=rpr.Aircraft
    )
    frame = decode_frame(payload, origin=ORIGIN, message_type=rpr.Aircraft)

    assert frame.state.key == state.key
    assert frame.extras.platform_kind == 1
    assert frame.extras.entity_type == extras.entity_type


def test_lenient_decode_preserves_unknown_fields():
    payload = encode_entity_state(make_state(), origin=ORIGIN)
    unknown_field = b"\xc0\x3e\x01"  # field 1000, varint 1
    extended = payload + unknown_field

    with pytest.raises(rpr.RprUnknownFieldError):
        decode_frame(extended, origin=ORIGIN)

    frame = decode_frame(extended, origin=ORIGIN, strict=False)
    assert rpr.encode(frame.message) == extended
    assert frame.state.key == make_state().key


def test_channel_adapter_delivers_a_frame():
    port = free_udp_port()
    state = make_state()
    with (
        Channel("127.0.0.1", port, bind=True) as receiver,
        Channel("127.0.0.1", port) as sender,
    ):
        source = RprChannel(receiver, origin=ORIGIN)
        sink = RprChannel(sender, origin=ORIGIN)
        assert sink.send(state) > 0
        frame = source.recv(2.0)

    assert frame.state.key == state.key
    assert frame.state.position_enu_m == pytest.approx(state.position_enu_m, abs=1e-4)
    assert frame.state.marking == state.marking


def test_unix_channel_adapter_delivers_a_frame(tmp_path):
    path = str(tmp_path / "rpr.sock")
    state = make_state()
    with (
        RprChannel.from_unix(path, bind=True, origin=ORIGIN) as receiver,
        RprChannel.from_unix(path, origin=ORIGIN) as sender,
    ):
        assert sender.send(state) > 0
        frame = receiver.recv(2.0)

    assert frame.state.key == state.key
    assert frame.state.marking == state.marking


def test_recording_and_replay_reproduce_entity_state(tmp_path):
    state = make_state(timestamp=0.0, exercise_id=1)
    path = tmp_path / "rpr.jsonl"
    payload = encode_entity_state(state, origin=ORIGIN)
    frame = decode_frame(payload, origin=ORIGIN, timestamp=state.timestamp)

    with RprJsonlRecorder(path) as recorder:
        recorder.write_frame(frame, sequence=7, timestamp=state.timestamp)

    records = list(iter_rpr_jsonl(path))
    assert records[0].payload == payload
    assert records[0].sequence == 7
    assert records[0].timestamp == state.timestamp

    frames = list(iter_rpr_frames(path, origin=ORIGIN))
    replayed_state = frames[0].state
    assert replayed_state.key == state.key
    assert replayed_state.timestamp == state.timestamp
    assert replayed_state.position_enu_m == pytest.approx(
        state.position_enu_m, abs=1e-4
    )
    assert replayed_state.velocity_enu_mps == pytest.approx(
        state.velocity_enu_mps, abs=1e-4
    )
    assert replayed_state.orientation_rps == pytest.approx(
        state.orientation_rps, abs=1e-5
    )
    assert replayed_state.angular_velocity_rps == pytest.approx(
        state.angular_velocity_rps, abs=1e-6
    )
    assert replayed_state.marking == state.marking
    assert replayed_state.force_id == state.force_id
    assert replayed_state.exercise_id == state.exercise_id

    port = free_udp_port()
    with (
        Channel("127.0.0.1", port, bind=True) as receiver,
        Channel("127.0.0.1", port) as sender,
    ):
        assert replay_rpr_jsonl(path, sender, origin=ORIGIN) == 1
        replayed = RprChannel(receiver, origin=ORIGIN).recv(2.0)

    assert replayed.state.key == state.key
    assert replayed.state.position_enu_m == pytest.approx(
        state.position_enu_m, abs=1e-4
    )
    assert replayed.state.velocity_enu_mps == pytest.approx(
        state.velocity_enu_mps, abs=1e-4
    )
    assert replayed.state.orientation_rps == pytest.approx(
        state.orientation_rps, abs=1e-5
    )
    assert replayed.state.marking == state.marking
    assert replayed.state.force_id == state.force_id


def test_core_import_does_not_load_pysos_rpr():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, pysos_interop; "
            "assert 'pysos_rpr' not in sys.modules, sorted(sys.modules)",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
