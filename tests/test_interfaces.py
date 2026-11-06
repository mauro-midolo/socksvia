import ctypes
import socket
import struct

import pytest

from socksvia import interfaces as ifmod
from socksvia.interfaces import Interface, _sockaddr_to_ip, enumerate_interfaces


class TestInterface:
    def test_ipv4_flags_and_str(self):
        iface = Interface("eth0", "192.168.1.2", socket.AF_INET)
        assert iface.is_ipv4
        assert iface.note == ""
        assert str(iface) == "eth0: 192.168.1.2"

    def test_apipa_note(self):
        assert Interface("eth1", "169.254.10.1", socket.AF_INET).note == "APIPA, no DHCP"

    def test_link_local_note(self):
        iface = Interface("eth0", "FE80::abcd", socket.AF_INET6)
        assert not iface.is_ipv4
        assert iface.note == "link-local"


def _linux_sockaddr(family, packed):
    """Build a fake struct sockaddr with the Linux layout (sa_family = u16)."""
    if family == socket.AF_INET:
        raw = struct.pack("=H", family) + b"\x00\x00" + packed + b"\x00" * 8
    else:
        raw = struct.pack("=H", family) + b"\x00" * 6 + packed + b"\x00" * 4
    return ctypes.create_string_buffer(raw, len(raw))


def _darwin_sockaddr(family, packed):
    """Build a fake struct sockaddr with the BSD layout (sa_len, sa_family)."""
    if family == socket.AF_INET:
        raw = bytes([16, family]) + b"\x00\x00" + packed + b"\x00" * 8
    else:
        raw = bytes([28, family]) + b"\x00" * 6 + packed + b"\x00" * 4
    return ctypes.create_string_buffer(raw, len(raw))


class TestSockaddrToIp:
    def test_null_pointer(self):
        assert _sockaddr_to_ip(None) == (None, None)

    def test_linux_ipv4(self, monkeypatch):
        monkeypatch.setattr(ifmod.sys, "platform", "linux")
        buf = _linux_sockaddr(socket.AF_INET, socket.inet_aton("10.1.2.3"))
        assert _sockaddr_to_ip(ctypes.addressof(buf)) == (socket.AF_INET, "10.1.2.3")

    def test_linux_ipv6(self, monkeypatch):
        monkeypatch.setattr(ifmod.sys, "platform", "linux")
        packed = socket.inet_pton(socket.AF_INET6, "2001:db8::1")
        buf = _linux_sockaddr(socket.AF_INET6, packed)
        assert _sockaddr_to_ip(ctypes.addressof(buf)) == (socket.AF_INET6, "2001:db8::1")

    def test_darwin_ipv4(self, monkeypatch):
        monkeypatch.setattr(ifmod.sys, "platform", "darwin")
        buf = _darwin_sockaddr(socket.AF_INET, socket.inet_aton("172.16.0.9"))
        assert _sockaddr_to_ip(ctypes.addressof(buf)) == (socket.AF_INET, "172.16.0.9")

    def test_darwin_ipv6(self, monkeypatch):
        monkeypatch.setattr(ifmod.sys, "platform", "darwin")
        packed = socket.inet_pton(socket.AF_INET6, "fe80::1")
        buf = _darwin_sockaddr(socket.AF_INET6, packed)
        assert _sockaddr_to_ip(ctypes.addressof(buf)) == (socket.AF_INET6, "fe80::1")

    def test_unknown_family(self, monkeypatch):
        monkeypatch.setattr(ifmod.sys, "platform", "linux")
        raw = struct.pack("=H", 17) + b"\x00" * 14  # AF_PACKET-like
        buf = ctypes.create_string_buffer(raw, len(raw))
        assert _sockaddr_to_ip(ctypes.addressof(buf)) == (None, None)


class TestEnumerateInterfaces:
    def _patch_native(self, monkeypatch, result):
        def native():
            if isinstance(result, Exception):
                raise result
            return list(result)

        monkeypatch.setattr(ifmod, "_enumerate_windows", native)
        monkeypatch.setattr(ifmod, "_enumerate_posix", native)

    def test_sorting_ipv4_first_and_noted_last(self, monkeypatch):
        self._patch_native(
            monkeypatch,
            [
                Interface("zeta", "fe80::1", socket.AF_INET6),
                Interface("beta", "169.254.0.1", socket.AF_INET),
                Interface("Alpha", "10.0.0.1", socket.AF_INET),
                Interface("gamma", "2001:db8::1", socket.AF_INET6),
            ],
        )
        result = [i.ip for i in enumerate_interfaces()]
        assert result == ["10.0.0.1", "169.254.0.1", "2001:db8::1", "fe80::1"]

    def test_native_failure_uses_fallback(self, monkeypatch):
        self._patch_native(monkeypatch, OSError("boom"))
        fallback = [Interface(ifmod.UNKNOWN_INTERFACE, "10.9.9.9", socket.AF_INET)]
        monkeypatch.setattr(ifmod, "_enumerate_fallback", lambda: list(fallback))
        assert [i.ip for i in enumerate_interfaces()] == ["10.9.9.9"]

    def test_empty_native_uses_fallback(self, monkeypatch):
        self._patch_native(monkeypatch, [])
        fallback = [Interface(ifmod.UNKNOWN_INTERFACE, "10.8.8.8", socket.AF_INET)]
        monkeypatch.setattr(ifmod, "_enumerate_fallback", lambda: list(fallback))
        assert [i.ip for i in enumerate_interfaces()] == ["10.8.8.8"]


class _FakeUdpSocket:
    """Stand-in for socket.socket used by the fallback probe (no real traffic)."""

    def __init__(self, family, _type):
        self.family = family

    def connect(self, target):
        if self.family == socket.AF_INET6:
            raise OSError("network unreachable")

    def getsockname(self):
        return ("192.168.50.2", 54321)

    def close(self):
        pass


def test_fallback_enumeration(monkeypatch):
    monkeypatch.setattr(ifmod.socket, "socket", _FakeUdpSocket)
    monkeypatch.setattr(ifmod.socket, "gethostname", lambda: "myhost")
    monkeypatch.setattr(
        ifmod.socket,
        "getaddrinfo",
        lambda host, port: [
            (socket.AF_INET, 0, 0, "", ("127.0.1.1", 0)),
            (socket.AF_INET, 0, 0, "", ("192.168.50.2", 0)),
            (socket.AF_INET, 0, 0, "", ("10.20.30.40", 0)),
        ],
    )
    result = ifmod._enumerate_fallback()
    assert [i.ip for i in result] == ["192.168.50.2", "10.20.30.40"]
    assert all(i.name == ifmod.UNKNOWN_INTERFACE for i in result)


def test_fallback_handles_resolution_error(monkeypatch):
    monkeypatch.setattr(ifmod.socket, "socket", _FakeUdpSocket)
    monkeypatch.setattr(ifmod.socket, "gethostname", lambda: "myhost")

    def broken(*_args):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(ifmod.socket, "getaddrinfo", broken)
    assert [i.ip for i in ifmod._enumerate_fallback()] == ["192.168.50.2"]


@pytest.mark.posix_only
def test_native_posix_enumeration_runs():
    """Smoke test of the real getifaddrs() call (Linux/macOS only)."""
    result = ifmod._enumerate_posix()
    assert isinstance(result, list)
    for iface in result:
        assert iface.family in (socket.AF_INET, socket.AF_INET6)
        assert not iface.ip.startswith("127.")


@pytest.mark.windows_only
def test_native_windows_enumeration_runs():
    """Smoke test of the real GetAdaptersAddresses() call (Windows only)."""
    result = ifmod._enumerate_windows()
    assert isinstance(result, list)
    for iface in result:
        assert iface.family in (socket.AF_INET, socket.AF_INET6)
