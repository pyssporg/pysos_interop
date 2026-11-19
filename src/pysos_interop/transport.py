"""UDP unicast and multicast channel.

A :class:`Channel` owns one socket.  Construction is cheap; :meth:`open`
creates the socket and :meth:`close` releases it.  Every socket failure is
re-raised as a typed :class:`TransportError` and a receive timeout raises
:class:`ChannelTimeoutError`; nothing is swallowed.
"""

from __future__ import annotations

import socket
import struct

SIOCGIFADDR = 0x8915


class TransportError(RuntimeError):
    """Base class for transport failures."""


class ChannelClosedError(TransportError):
    """The channel has not been opened or has already been closed."""


class ChannelTimeoutError(TransportError, TimeoutError):
    """No datagram arrived within the requested timeout."""


def is_multicast_address(host: str) -> bool:
    """Return whether ``host`` is an IPv4 multicast address literal."""

    try:
        packed = socket.inet_aton(host)
    except OSError:
        return False
    return 224 <= packed[0] <= 239


def _interface_address(interface: str) -> str:
    """Resolve an interface name or address to an IPv4 address."""

    try:
        socket.inet_aton(interface)
        return interface
    except OSError:
        pass

    try:
        socket.if_nametoindex(interface)
    except OSError:
        pass
    else:
        try:
            import fcntl

            request = struct.pack("256s", interface.encode("ascii")[:15])
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                response = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, request)
            return socket.inet_ntoa(response[20:24])
        except (OSError, ImportError, UnicodeEncodeError) as exc:
            raise TransportError(
                f"Cannot determine the address of interface {interface!r}"
            ) from exc

    try:
        return socket.gethostbyname(interface)
    except OSError as exc:
        raise TransportError(f"Cannot resolve interface {interface!r}") from exc


class Channel:
    """One UDP socket, unicast or multicast.

    Pass ``bind=True`` for a receiving channel.  ``multicast`` is detected
    from the host address when omitted.  A multicast receiver binds to the
    port and joins the group; a multicast sender only sets the send options.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 3000,
        *,
        multicast: bool | None = None,
        bind: bool = False,
        ttl: int = 1,
        interface: str | None = None,
    ) -> None:
        self.host = str(host)
        self.port = int(port)
        self.multicast = is_multicast_address(self.host) if multicast is None else multicast
        self.bind = bool(bind)
        self.ttl = int(ttl)
        self.interface = interface
        self._socket: socket.socket | None = None

    def open(self) -> Channel:
        """Create and configure the socket, returning ``self``."""

        if self._socket is not None:
            return self
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if self.multicast:
                self._configure_multicast(sock)
            elif self.bind:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((self.host, self.port))
        except OSError as exc:
            sock.close()
            raise TransportError(
                f"Failed to open channel {self.host}:{self.port}: {exc}"
            ) from exc
        except BaseException:
            sock.close()
            raise
        self._socket = sock
        return self

    def _configure_multicast(self, sock: socket.socket) -> None:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.ttl)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        interface_address = "0.0.0.0"
        if self.interface is not None:
            interface_address = _interface_address(self.interface)
            sock.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_MULTICAST_IF,
                socket.inet_aton(interface_address),
            )

        if not self.bind:
            return

        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", self.port))
        membership = struct.pack(
            "4s4s",
            socket.inet_aton(self.host),
            socket.inet_aton(interface_address),
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise ChannelClosedError("Channel is not open")
        return self._socket

    def send(self, data: bytes) -> int:
        """Send one datagram, returning the number of bytes sent."""

        sock = self._require_socket()
        try:
            return sock.sendto(bytes(data), (self.host, self.port))
        except OSError as exc:
            raise TransportError(f"Failed to send to {self.host}:{self.port}: {exc}") from exc

    def recv(self, timeout: float | None = None) -> bytes:
        """Receive one datagram or raise :class:`ChannelTimeoutError`."""

        sock = self._require_socket()
        sock.settimeout(timeout)
        try:
            data, _ = sock.recvfrom(65535)
        except (socket.timeout, TimeoutError) as exc:
            raise ChannelTimeoutError(
                f"No datagram within {timeout} seconds"
            ) from exc
        except OSError as exc:
            raise TransportError(f"Failed to receive on {self.host}:{self.port}: {exc}") from exc
        return data

    def close(self) -> None:
        """Close the socket; safe to call more than once."""

        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()

    def __enter__(self) -> Channel:
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()
