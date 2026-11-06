"""Minimal SOCKS5 server (CONNECT only, no authentication) bound to a source IP."""

import logging
import selectors
import socket
import socketserver
import struct
import threading

SOCKS_VERSION = 5

CMD_CONNECT = 0x01

ATYP_IPV4 = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV6 = 0x04

REP_SUCCESS = 0x00
REP_HOST_UNREACHABLE = 0x04
REP_CMD_NOT_SUPPORTED = 0x07
REP_ATYP_NOT_SUPPORTED = 0x08

AUTH_NONE = 0x00

BUFFER_SIZE = 65536
CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 300

log = logging.getLogger("socksvia")


def recv_exactly(sock, n):
    """Read exactly ``n`` bytes, or raise ``ConnectionError`` if the peer closes."""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("connection closed by peer")
        data.extend(chunk)
    return bytes(data)


class Socks5Handler(socketserver.BaseRequestHandler):
    """The outbound interface is read from ``self.server.outbound`` on every connection."""

    def handle(self):
        client = self.request
        try:
            self.negotiate_auth(client)
            self.handle_request(client)
        except ConnectionError as exc:
            log.debug("[%s] connection interrupted: %s", self.client_address, exc)
        except Exception as exc:
            log.warning("[%s] error: %s", self.client_address, exc)

    def negotiate_auth(self, client):
        header = recv_exactly(client, 2)
        version, nmethods = header[0], header[1]
        if version != SOCKS_VERSION:
            raise ConnectionError(f"unsupported SOCKS version: {version}")
        recv_exactly(client, nmethods)
        client.sendall(struct.pack("!BB", SOCKS_VERSION, AUTH_NONE))

    def handle_request(self, client):
        header = recv_exactly(client, 4)
        version, cmd, _, atyp = header
        if version != SOCKS_VERSION:
            raise ConnectionError("invalid SOCKS version in request")

        if atyp == ATYP_IPV4:
            host = socket.inet_ntop(socket.AF_INET, recv_exactly(client, 4))
        elif atyp == ATYP_IPV6:
            host = socket.inet_ntop(socket.AF_INET6, recv_exactly(client, 16))
        elif atyp == ATYP_DOMAIN:
            length = recv_exactly(client, 1)[0]
            host = recv_exactly(client, length).decode("idna")
        else:
            self.send_reply(client, REP_ATYP_NOT_SUPPORTED)
            return

        port = struct.unpack("!H", recv_exactly(client, 2))[0]

        if cmd != CMD_CONNECT:
            self.send_reply(client, REP_CMD_NOT_SUPPORTED)
            return

        remote = self.connect_via_nic(host, port)
        if remote is None:
            self.send_reply(client, REP_HOST_UNREACHABLE)
            return

        pair = (client, remote)
        self.server.track(pair)
        try:
            bound_ip, bound_port = remote.getsockname()[:2]
            self.send_reply(client, REP_SUCCESS, bound_ip, bound_port)
            log.info("%s:%s  -->  via %s", host, port, bound_ip)
            self.relay(client, remote)
        finally:
            self.server.untrack(pair)
            remote.close()

    def connect_via_nic(self, host, port):
        """
        Resolve the name here (so DNS also leaves through the chosen interface)
        and open the connection with the socket bound to the source IP.
        """
        # Read together (one tuple) so IP and family are always consistent,
        # even if the user switches interface in the meantime.
        external_ip, external_family = self.server.outbound
        try:
            infos = socket.getaddrinfo(host, port, external_family, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            log.warning("name resolution failed for %s: %s", host, exc)
            return None

        last_error = None
        for family, socktype, proto, _, sockaddr in infos:
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(CONNECT_TIMEOUT)
                sock.bind((external_ip, 0))
                sock.connect(sockaddr)
                sock.settimeout(None)
                return sock
            except OSError as exc:
                last_error = exc
                sock.close()

        log.warning("connection to %s:%s failed: %s", host, port, last_error)
        return None

    def send_reply(self, client, code, ip="0.0.0.0", port=0):
        try:
            packed = socket.inet_pton(socket.AF_INET, ip)
            atyp = ATYP_IPV4
        except OSError:
            try:
                packed = socket.inet_pton(socket.AF_INET6, ip)
                atyp = ATYP_IPV6
            except OSError:
                packed = b"\x00\x00\x00\x00"
                atyp = ATYP_IPV4
        reply = struct.pack("!BBBB", SOCKS_VERSION, code, 0x00, atyp)
        reply += packed + struct.pack("!H", port)
        try:
            client.sendall(reply)
        except OSError:
            pass

    def relay(self, client, remote):
        sel = selectors.DefaultSelector()
        sel.register(client, selectors.EVENT_READ, remote)
        sel.register(remote, selectors.EVENT_READ, client)
        try:
            while True:
                events = sel.select(timeout=IDLE_TIMEOUT)
                if not events:
                    break
                for key, _ in events:
                    source, destination = key.fileobj, key.data
                    try:
                        data = source.recv(BUFFER_SIZE)
                    except OSError:
                        return
                    if not data:
                        return
                    try:
                        destination.sendall(data)
                    except OSError:
                        return
        finally:
            sel.close()


class ThreadedSocksServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, external_ip, external_family):
        self.outbound = (external_ip, external_family)
        self._lock = threading.Lock()
        self._connections = set()
        super().__init__(address, handler)

    def track(self, pair):
        with self._lock:
            self._connections.add(pair)

    def untrack(self, pair):
        with self._lock:
            self._connections.discard(pair)

    def set_outbound(self, external_ip, external_family):
        """
        Switch the interface for new connections and close the open ones,
        so the browser reconnects right away through the new interface
        (otherwise keep-alive connections would stay on the old one).
        Return the number of connections that were closed.
        """
        with self._lock:
            self.outbound = (external_ip, external_family)
            active = list(self._connections)
        for pair in active:
            for sock in pair:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        return len(active)


def ip_family(external_ip):
    """Return ``AF_INET`` or ``AF_INET6`` for the given IP, ``ValueError`` if invalid."""
    try:
        socket.inet_pton(socket.AF_INET, external_ip)
        return socket.AF_INET
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, external_ip.split("%")[0])
        return socket.AF_INET6
    except OSError:
        raise ValueError(f"invalid source IP: {external_ip}") from None


def check_source_ip(external_ip, family):
    """
    Check that the IP is assigned to a local interface (``OSError`` if not):
    better to fail now than on every connection.
    """
    probe = socket.socket(family, socket.SOCK_STREAM)
    try:
        probe.bind((external_ip, 0))
    finally:
        probe.close()
