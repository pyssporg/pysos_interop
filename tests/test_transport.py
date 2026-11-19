"""UDP channel tests: unicast always, multicast opt-in."""

import os
import socket

import pytest

from pysos_interop.transport import (
    Channel,
    ChannelClosedError,
    ChannelTimeoutError,
    TransportError,
)


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
