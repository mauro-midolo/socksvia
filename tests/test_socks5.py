"""SOCKS5 protocol tests against a real server on the loopback interface."""

import socket
import struct
import threading
import time

import pytest

from socksvia import server as srv
from socksvia.server import (
    ATYP_DOMAIN,
    ATYP_IPV4,
    ATYP_IPV6,
    REP_ATYP_NOT_SUPPORTED,
    REP_CMD_NOT_SUPPORTED,
    REP_HOST_UNREACHABLE,
    REP_SUCCESS,
    Socks5Handler,
    ThreadedSocksServer,
    check_source_ip,
    ip_family,
    recv_exactly,
)

TIMEOUT = 5


def ipv6_loopback_available():
    if not socket.has_ipv6:
        return False
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


@pytest.fixture
def echo_server():
    """A TCP echo server on 127.0.0.1; yields its port."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.2)
    stop = threading.Event()

    def echo(conn):
        with conn:
            while True:
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                conn.sendall(data)

    def accept_loop():
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=echo, args=(conn,), daemon=True).start()

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    stop.set()
    thread.join(timeout=TIMEOUT)
    listener.close()


@pytest.fixture
def proxy():
    """A running socksvia server bound to 127.0.0.1 as outbound interface."""
    server = ThreadedSocksServer(("127.0.0.1", 0), Socks5Handler, "127.0.0.1", socket.AF_INET)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=TIMEOUT)


def open_client(server):
    client = socket.create_connection(server.server_address, timeout=TIMEOUT)
    return client


def greet(client, methods=b"\x00"):
    client.sendall(bytes([5, len(methods)]) + methods)
    return recv_exactly(client, 2)


def read_reply(client):
    head = recv_exactly(client, 4)
    atyp = head[3]
    addr_len = {ATYP_IPV4: 4, ATYP_IPV6: 16}[atyp]
    addr = recv_exactly(client, addr_len)
    port = struct.unpack("!H", recv_exactly(client, 2))[0]
    family = socket.AF_INET if atyp == ATYP_IPV4 else socket.AF_INET6
    return head[1], socket.inet_ntop(family, addr), port


def assert_closed_by_proxy(client):
    """The proxy dropped the connection: either a clean EOF or, when it closes
    with unread data still queued (macOS does this), a TCP reset."""
    try:
        assert client.recv(16) == b""
    except ConnectionResetError:
        pass


def connect_request(atyp, address, port, cmd=1):
    if atyp == ATYP_IPV4:
        addr = socket.inet_aton(address)
    elif atyp == ATYP_IPV6:
        addr = socket.inet_pton(socket.AF_INET6, address)
    else:
        encoded = address.encode("idna")
        addr = bytes([len(encoded)]) + encoded
    return bytes([5, cmd, 0, atyp]) + addr + struct.pack("!H", port)


# ---------------------------------------------------------------------------
# Handshake and CONNECT
# ---------------------------------------------------------------------------


def test_greeting_selects_no_auth(proxy):
    with open_client(proxy) as client:
        assert greet(client, b"\x00\x02") == b"\x05\x00"


def test_connect_ipv4_and_relay(proxy, echo_server):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_IPV4, "127.0.0.1", echo_server))
        code, bound_ip, bound_port = read_reply(client)
        assert code == REP_SUCCESS
        assert bound_ip == "127.0.0.1"
        assert bound_port > 0

        client.sendall(b"hello socksvia")
        assert recv_exactly(client, 14) == b"hello socksvia"


def test_connect_domain_resolved_by_proxy(proxy, echo_server):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_DOMAIN, "localhost", echo_server))
        code, bound_ip, _ = read_reply(client)
        assert code == REP_SUCCESS
        assert bound_ip == "127.0.0.1"
        client.sendall(b"ping")
        assert recv_exactly(client, 4) == b"ping"


def test_connection_is_tracked_while_open(proxy, echo_server):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_IPV4, "127.0.0.1", echo_server))
        assert read_reply(client)[0] == REP_SUCCESS
        assert len(proxy._connections) == 1
    deadline = time.monotonic() + TIMEOUT
    while proxy._connections and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not proxy._connections


def test_unsupported_command(proxy):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_IPV4, "127.0.0.1", 80, cmd=0x02))  # BIND
        assert read_reply(client)[0] == REP_CMD_NOT_SUPPORTED


def test_unsupported_address_type(proxy):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(bytes([5, 1, 0, 0x09]))
        assert read_reply(client)[0] == REP_ATYP_NOT_SUPPORTED


def test_wrong_version_closes_connection(proxy):
    with open_client(proxy) as client:
        client.sendall(b"\x04\x01\x00\x50")
        assert_closed_by_proxy(client)


def test_wrong_version_in_request_closes_connection(proxy):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(b"\x04\x01\x00\x01")
        assert_closed_by_proxy(client)


def test_resolution_failure_is_host_unreachable(proxy, monkeypatch):
    real_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "does-not-exist.invalid":
            raise socket.gaierror("no such host")
        return real_getaddrinfo(host, *args, **kwargs)

    # Note: srv.socket is the global socket module, so delegate everything else.
    monkeypatch.setattr(srv.socket, "getaddrinfo", fake_getaddrinfo)
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_DOMAIN, "does-not-exist.invalid", 80))
        assert read_reply(client)[0] == REP_HOST_UNREACHABLE


def test_refused_connection_is_host_unreachable(proxy):
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        free_port = closed.getsockname()[1]
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_IPV4, "127.0.0.1", free_port))
        assert read_reply(client)[0] == REP_HOST_UNREACHABLE


@pytest.mark.skipif(not ipv6_loopback_available(), reason="IPv6 loopback not available")
def test_connect_ipv6_request_uses_outbound_family(echo_server):
    """An IPv6 target with an IPv4 outbound interface cannot be reached."""
    server = ThreadedSocksServer(("127.0.0.1", 0), Socks5Handler, "127.0.0.1", socket.AF_INET)
    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    try:
        with open_client(server) as client:
            greet(client)
            client.sendall(connect_request(ATYP_IPV6, "::1", echo_server))
            assert read_reply(client)[0] == REP_HOST_UNREACHABLE
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# Interface switch
# ---------------------------------------------------------------------------


def test_set_outbound_closes_open_connections(proxy, echo_server):
    with open_client(proxy) as client:
        greet(client)
        client.sendall(connect_request(ATYP_IPV4, "127.0.0.1", echo_server))
        assert read_reply(client)[0] == REP_SUCCESS

        closed = proxy.set_outbound("127.0.0.2", socket.AF_INET)
        assert closed == 1
        assert proxy.outbound == ("127.0.0.2", socket.AF_INET)
        assert_closed_by_proxy(client)


def test_set_outbound_without_connections(proxy):
    assert proxy.set_outbound("127.0.0.1", socket.AF_INET) == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Sink:
    def __init__(self, fail=False):
        self.data = b""
        self.fail = fail

    def sendall(self, data):
        if self.fail:
            raise OSError("broken pipe")
        self.data += data


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("0.0.0.0", b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00"),
        ("10.0.0.1", b"\x05\x00\x00\x01\x0a\x00\x00\x01\x04\x38"),
        ("::1", b"\x05\x00\x00\x04" + b"\x00" * 15 + b"\x01\x04\x38"),
        ("not-an-ip", b"\x05\x00\x00\x01\x00\x00\x00\x00\x04\x38"),
    ],
)
def test_send_reply_encoding(ip, expected):
    sink = _Sink()
    port = 0 if ip == "0.0.0.0" else 1080
    Socks5Handler.send_reply(None, sink, REP_SUCCESS, ip, port)
    assert sink.data == expected


def test_send_reply_ignores_broken_client():
    Socks5Handler.send_reply(None, _Sink(fail=True), REP_HOST_UNREACHABLE)


def test_recv_exactly_reassembles_chunks():
    a, b = socket.socketpair()
    with a, b:
        a.sendall(b"ab")
        a.sendall(b"cd")
        assert recv_exactly(b, 4) == b"abcd"


def test_recv_exactly_raises_on_close():
    a, b = socket.socketpair()
    with b:
        a.sendall(b"x")
        a.close()
        with pytest.raises(ConnectionError):
            recv_exactly(b, 2)


@pytest.mark.parametrize(
    ("ip", "family"),
    [
        ("192.168.1.1", socket.AF_INET),
        ("2001:db8::1", socket.AF_INET6),
        ("fe80::1%eth0", socket.AF_INET6),
    ],
)
def test_ip_family(ip, family):
    assert ip_family(ip) == family


@pytest.mark.parametrize("ip", ["", "eth0", "300.1.1.1", "1.2.3", "::g"])
def test_ip_family_rejects_invalid(ip):
    with pytest.raises(ValueError, match="invalid source IP"):
        ip_family(ip)


def test_check_source_ip_accepts_local_address():
    check_source_ip("127.0.0.1", socket.AF_INET)


def test_check_source_ip_rejects_foreign_address():
    # 203.0.113.0/24 is TEST-NET-3 (RFC 5737): never assigned to a real host.
    with pytest.raises(OSError):
        check_source_ip("203.0.113.77", socket.AF_INET)
