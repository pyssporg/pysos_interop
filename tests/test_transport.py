"""Datagram channel tests: UDP unicast always, multicast opt-in, Unix always."""

import os
import socket
import uuid

import pytest

from pysos_interop.transport import (
    Channel,
    ChannelClosedError,
    ChannelTimeoutError,
    TransportError,
    UnixChannel,
    parse_unix_endpoint,
)


def unique_abstract_name() -> str:
    return f"@pysos-test-{os.getpid()}-{uuid.uuid4().hex}"


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def test_unicast_loopback_round_trip():
    port = free_udp_port()
    with (
        Channel("127.0.0.1", port, bind=True) as receiver,
        Channel("127.0.0.1", port) as sender,
    ):
        payload = b"\x07\x01\x01\x01entity-state-test"
        assert sender.send(payload) == len(payload)
        assert receiver.recv(2.0) == payload


def test_receive_timeout_raises_a_typed_error():
    port = free_udp_port()
    with Channel("127.0.0.1", port, bind=True) as receiver:
        with pytest.raises(ChannelTimeoutError):
            receiver.recv(0.01)


def test_closed_and_failed_channels_raise_typed_errors():
    channel = Channel("127.0.0.1", free_udp_port()).open()
    channel.close()
    with pytest.raises(ChannelClosedError):
        channel.send(b"closed")

    with pytest.raises(TransportError):
        Channel("203.0.113.1", free_udp_port(), bind=True).open()


def test_unix_pathname_round_trip(tmp_path):
    path = str(tmp_path / "peer.sock")
    payload = b"\x07\x01\x01\x01unix-entity-state"
    with (
        UnixChannel(path, bind=True) as receiver,
        UnixChannel(path) as sender,
    ):
        assert receiver.local_address == path
        assert sender.local_address is None
        assert sender.send(payload) == len(payload)
        assert receiver.recv(2.0) == payload


def test_unix_abstract_round_trip():
    name = unique_abstract_name()
    payload = b"abstract-datagram"
    with (
        UnixChannel(name, bind=True) as receiver,
        UnixChannel(name) as sender,
    ):
        assert receiver.local_address == name
        assert sender.send(payload) == len(payload)
        assert receiver.recv(2.0) == payload


def test_unix_receive_timeout_raises_a_typed_error():
    with UnixChannel(unique_abstract_name(), bind=True) as receiver:
        with pytest.raises(ChannelTimeoutError):
            receiver.recv(0.01)


def test_unix_closed_channel_raises_a_typed_error():
    channel = UnixChannel(unique_abstract_name(), bind=True).open()
    channel.close()
    with pytest.raises(ChannelClosedError):
        channel.send(b"closed")
    with pytest.raises(ChannelClosedError):
        channel.recv(0.01)


def test_unix_pathname_unlinks_a_stale_socket(tmp_path):
    path = tmp_path / "stale.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        stale.bind(str(path))
    finally:
        stale.close()
    assert path.exists()

    with UnixChannel(str(path), bind=True) as receiver:
        assert receiver.local_address == str(path)
        assert path.is_socket()


def test_unix_pathname_preserves_a_non_socket_path(tmp_path):
    path = tmp_path / "not-a-socket.txt"
    path.write_bytes(b"keep me")

    with pytest.raises(TransportError):
        UnixChannel(str(path), bind=True).open()

    assert path.read_bytes() == b"keep me"


def test_unix_endpoint_parsing_and_from_endpoint(tmp_path):
    path = str(tmp_path / "peer.sock")
    assert parse_unix_endpoint(f"unix://{path}") == path
    assert parse_unix_endpoint("unix://@peer") == "@peer"

    with pytest.raises(ValueError):
        parse_unix_endpoint("udp://127.0.0.1:3000")
    with pytest.raises(ValueError):
        parse_unix_endpoint("unix://relative.sock")

    with Channel.from_endpoint(f"unix://{path}", bind=True) as receiver:
        assert isinstance(receiver, UnixChannel)
        assert receiver.local_address == path


@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("PYSOS_NETWORK_TESTS") != "1",
    reason="set PYSOS_NETWORK_TESTS=1 to run multicast tests",
)
def test_multicast_loopback_round_trip():
    group = "239.255.42.99"
    port = free_udp_port()
    with (
        Channel(group, port, bind=True) as receiver,
        Channel(group, port, ttl=1) as sender,
    ):
        payload = b"multicast-entity-state"
        assert sender.send(payload) == len(payload)
        assert receiver.recv(2.0) == payload
