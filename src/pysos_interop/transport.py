"""UDP and Unix-domain datagram channels.

A channel owns one datagram socket.  :class:`Channel` covers IPv4 unicast and
multicast; :class:`UnixChannel` covers single-host ``AF_UNIX``/``SOCK_DGRAM``
traffic.  Construction is cheap; :meth:`open` creates the socket and
:meth:`close` releases it.  Every socket failure is re-raised as a typed
:class:`TransportError` and a receive timeout raises
:class:`ChannelTimeoutError`; nothing is swallowed.

A Unix endpoint is a pathname (``/abs/path.sock``) or an abstract name
(``@name``); ``unix:///abs/path.sock`` and ``unix://@name`` are the URI forms
understood by :meth:`Channel.from_endpoint`.  One datagram is one message, the
same framing UDP uses.
"""

from __future__ import annotations

import os
import socket
import stat
import struct

SIOCGIFADDR = 0x8915
UNIX_SCHEME = "unix://"


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


def _unix_address(path: str) -> str | bytes:
    """Return the ``sockaddr_un`` value for a pathname or ``@abstract`` name."""

    text = str(path)
    if text.startswith("@"):
        name = text[1:]
        if not name:
            raise ValueError("Unix abstract socket name must not be empty")
        if "\0" in name:
            raise ValueError("Unix abstract socket name must not contain NUL")
        return b"\0" + name.encode("utf-8")
    if not text:
        raise ValueError("Unix socket path must not be empty")
    if "\0" in text:
        raise ValueError("Unix socket path must not contain NUL")
    if not os.path.isabs(text):
        raise ValueError(f"Unix socket path must be absolute: {path!r}")
    return text


def parse_unix_endpoint(endpoint: str) -> str:
    """Parse ``unix:///abs/path.sock`` or ``unix://@name`` into an address.

    The returned value is the pathname or the ``@name`` abstract form;
    :class:`UnixChannel` converts it to the ``sockaddr_un`` representation on
    bind and send.
    """

    text = str(endpoint)
    if not text.startswith(UNIX_SCHEME):
        raise ValueError(f"Not a Unix endpoint: {endpoint!r}")
    address = text[len(UNIX_SCHEME) :]
    _unix_address(address)
    return address


def _unlink_stale_socket(path: str) -> None:
    """Remove a stale socket at ``path``; refuse to touch anything else."""

    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise TransportError(f"Cannot inspect Unix socket path {path!r}: {exc}") from exc
    if not stat.S_ISSOCK(info.st_mode):
        raise TransportError(f"Refusing to remove non-socket path {path!r}")
    try:
        os.unlink(path)
    except OSError as exc:
        raise TransportError(f"Cannot remove stale Unix socket {path!r}: {exc}") from exc


class _DatagramChannel:
    """Shared receive, close and context-manager behaviour for datagram channels."""

    _socket: socket.socket | None

    def _endpoint_label(self) -> str:
        raise NotImplementedError

    def _require_socket(self) -> socket.socket:
        if self._socket is None:
            raise ChannelClosedError("Channel is not open")
        return self._socket

    def recv(self, timeout: float | None = None) -> bytes:
        """Receive one datagram or raise :class:`ChannelTimeoutError`."""

        sock = self._require_socket()
        sock.settimeout(timeout)
        try:
            data, _ = sock.recvfrom(65535)
        except (socket.timeout, TimeoutError) as exc:
            raise ChannelTimeoutError(f"No datagram within {timeout} seconds") from exc
        except OSError as exc:
            raise TransportError(
                f"Failed to receive on {self._endpoint_label()}: {exc}"
            ) from exc
        return data

    def close(self) -> None:
        """Close the socket; safe to call more than once."""

        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()

    def __enter__(self) -> _DatagramChannel:
        return self.open()

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class Channel(_DatagramChannel):
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

    @classmethod
    def from_endpoint(cls, endpoint: str, *, bind: bool = False) -> Channel | UnixChannel:
        """Construct a channel from ``unix:///abs/path`` or ``unix://@name``."""

        if str(endpoint).startswith(UNIX_SCHEME):
            return UnixChannel.from_endpoint(endpoint, bind=bind)
        raise ValueError(
            f"Unsupported endpoint {endpoint!r}; expected unix:///abs/path or unix://@name"
        )

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

    def _endpoint_label(self) -> str:
        return f"{self.host}:{self.port}"

    def send(self, data: bytes) -> int:
        """Send one datagram, returning the number of bytes sent."""

        sock = self._require_socket()
        try:
            return sock.sendto(bytes(data), (self.host, self.port))
        except OSError as exc:
            raise TransportError(f"Failed to send to {self.host}:{self.port}: {exc}") from exc


class UnixChannel(_DatagramChannel):
    """One ``AF_UNIX``/``SOCK_DGRAM`` socket, pathname or abstract.

    ``path`` is the send destination.  Pass ``bind=True`` for a receiver; the
    same path is bound locally and exposed as :attr:`local_address`.  A
    pathname receiver unlinks a stale socket before binding but never removes a
    non-socket path.  Abstract names (``@name``) need no filesystem cleanup and
    are preferable for ephemeral runs.
    """

    def __init__(self, path: str, *, bind: bool = False) -> None:
        self.path = str(path)
        _unix_address(self.path)
        self.bind = bool(bind)
        self._socket: socket.socket | None = None

    @classmethod
    def from_endpoint(cls, endpoint: str, *, bind: bool = False) -> UnixChannel:
        """Construct a channel from ``unix:///abs/path`` or ``unix://@name``."""

        return cls(parse_unix_endpoint(endpoint), bind=bind)

    @property
    def local_address(self) -> str | None:
        """The bound path or ``@name``; ``None`` for a sender or closed channel."""

        if self.bind and self._socket is not None:
            return self.path
        return None

    def open(self) -> UnixChannel:
        """Create and bind the socket if requested, returning ``self``."""

        if self._socket is not None:
            return self
        if not hasattr(socket, "AF_UNIX"):
            raise TransportError("Unix-domain sockets are not available on this platform")
        address = _unix_address(self.path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            if self.bind:
                if isinstance(address, bytes):
                    sock.bind(address)
                else:
                    _unlink_stale_socket(address)
                    sock.bind(address)
        except OSError as exc:
            sock.close()
            raise TransportError(
                f"Failed to open Unix channel {self.path!r}: {exc}"
            ) from exc
        except BaseException:
            sock.close()
            raise
        self._socket = sock
        return self

    def _endpoint_label(self) -> str:
        return self.path

    def send(self, data: bytes) -> int:
        """Send one datagram to :attr:`path`, returning the number of bytes sent."""

        sock = self._require_socket()
        try:
            return sock.sendto(bytes(data), _unix_address(self.path))
        except OSError as exc:
            raise TransportError(f"Failed to send to {self.path!r}: {exc}") from exc
