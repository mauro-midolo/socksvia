"""Network interface enumeration (Windows, Linux/macOS, and a generic fallback)."""

import ctypes
import logging
import os
import socket
import struct
import sys

log = logging.getLogger("socksvia")


class Interface:
    """A network interface / IP address pair."""

    def __init__(self, name, ip, family, description=""):
        self.name = name
        self.ip = ip
        self.family = family
        self.description = description

    @property
    def is_ipv4(self):
        return self.family == socket.AF_INET

    @property
    def note(self):
        """Flag addresses that are unlikely to reach the Internet."""
        if self.ip.startswith("169.254."):
            return "APIPA, no DHCP"
        if self.ip.lower().startswith("fe80:"):
            return "link-local"
        return ""

    def __str__(self):
        return f"{self.name}: {self.ip}"

    def __repr__(self):
        return f"Interface({self.name!r}, {self.ip!r}, {self.family!r})"


def _sockaddr_to_ip(sockaddr_ptr):
    """Convert a pointer to a ``struct sockaddr`` into ``(family, ip_string)``."""
    if not sockaddr_ptr:
        return None, None

    # On Linux sa_family is an unsigned short at offset 0.
    # On macOS/BSD there is sa_len (1 byte) first, then sa_family (1 byte).
    raw = ctypes.string_at(sockaddr_ptr, 2)
    if sys.platform == "darwin":
        family = raw[1]
    else:
        family = struct.unpack("=H", raw)[0]

    if family == socket.AF_INET:
        packed = ctypes.string_at(sockaddr_ptr + 4, 4)
        return socket.AF_INET, socket.inet_ntop(socket.AF_INET, packed)
    if family == socket.AF_INET6:
        packed = ctypes.string_at(sockaddr_ptr + 8, 16)
        return socket.AF_INET6, socket.inet_ntop(socket.AF_INET6, packed)
    return None, None


def _enumerate_windows():
    """Use GetAdaptersAddresses (iphlpapi) to get the "friendly" adapter names."""

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [
            ("lpSockaddr", ctypes.c_void_p),
            ("iSockaddrLength", ctypes.c_int),
        ]

    class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
        pass

    IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
        ("Length", ctypes.c_ulong),
        ("Flags", ctypes.c_ulong),
        ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
        ("Address", SOCKET_ADDRESS),
        ("PrefixOrigin", ctypes.c_int),
        ("SuffixOrigin", ctypes.c_int),
        ("DadState", ctypes.c_int),
    ]

    class IP_ADAPTER_ADDRESSES(ctypes.Structure):
        pass

    IP_ADAPTER_ADDRESSES._fields_ = [
        ("Length", ctypes.c_ulong),
        ("IfIndex", ctypes.c_ulong),
        ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
        ("AdapterName", ctypes.c_char_p),
        ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
        ("FirstAnycastAddress", ctypes.c_void_p),
        ("FirstMulticastAddress", ctypes.c_void_p),
        ("FirstDnsServerAddress", ctypes.c_void_p),
        ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p),
        ("FriendlyName", ctypes.c_wchar_p),
        ("PhysicalAddress", ctypes.c_ubyte * 8),
        ("PhysicalAddressLength", ctypes.c_ulong),
        ("Flags", ctypes.c_ulong),
        ("Mtu", ctypes.c_ulong),
        ("IfType", ctypes.c_ulong),
        ("OperStatus", ctypes.c_int),
    ]

    AF_UNSPEC = 0
    GAA_FLAG_SKIP_ANYCAST = 0x0002
    GAA_FLAG_SKIP_MULTICAST = 0x0004
    GAA_FLAG_SKIP_DNS_SERVER = 0x0008
    ERROR_BUFFER_OVERFLOW = 111
    ERROR_SUCCESS = 0
    IF_TYPE_SOFTWARE_LOOPBACK = 24
    IF_OPER_STATUS_UP = 1

    flags = GAA_FLAG_SKIP_ANYCAST | GAA_FLAG_SKIP_MULTICAST | GAA_FLAG_SKIP_DNS_SERVER
    iphlpapi = ctypes.windll.iphlpapi

    size = ctypes.c_ulong(15000)
    for _ in range(4):
        buffer = ctypes.create_string_buffer(size.value)
        result = iphlpapi.GetAdaptersAddresses(AF_UNSPEC, flags, None, buffer, ctypes.byref(size))
        if result == ERROR_BUFFER_OVERFLOW:
            continue
        break

    if result != ERROR_SUCCESS:
        raise OSError(f"GetAdaptersAddresses returned {result}")

    interfaces = []
    adapter = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    while adapter:
        entry = adapter.contents
        if entry.OperStatus == IF_OPER_STATUS_UP and entry.IfType != IF_TYPE_SOFTWARE_LOOPBACK:
            name = entry.FriendlyName or (entry.AdapterName or b"").decode()
            unicast = entry.FirstUnicastAddress
            while unicast:
                family, ip = _sockaddr_to_ip(unicast.contents.Address.lpSockaddr)
                if ip:
                    interfaces.append(Interface(name, ip, family, entry.Description or ""))
                unicast = unicast.contents.Next
        adapter = entry.Next
    return interfaces


def _enumerate_posix():
    """Use getifaddrs() on Linux/macOS."""

    class ifaddrs(ctypes.Structure):
        pass

    ifaddrs._fields_ = [
        ("ifa_next", ctypes.POINTER(ifaddrs)),
        ("ifa_name", ctypes.c_char_p),
        ("ifa_flags", ctypes.c_uint),
        ("ifa_addr", ctypes.c_void_p),
        ("ifa_netmask", ctypes.c_void_p),
        ("ifa_dstaddr", ctypes.c_void_p),
        ("ifa_data", ctypes.c_void_p),
    ]

    IFF_UP = 0x1
    IFF_LOOPBACK = 0x8

    libc = ctypes.CDLL(None, use_errno=True)
    head = ctypes.POINTER(ifaddrs)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        raise OSError(ctypes.get_errno(), "getifaddrs failed")

    interfaces = []
    try:
        current = head
        while current:
            entry = current.contents
            up = entry.ifa_flags & IFF_UP
            loopback = entry.ifa_flags & IFF_LOOPBACK
            if up and not loopback:
                family, ip = _sockaddr_to_ip(entry.ifa_addr)
                if ip:
                    name = entry.ifa_name.decode(errors="replace")
                    interfaces.append(Interface(name, ip, family))
            current = entry.ifa_next
    finally:
        libc.freeifaddrs(head)
    return interfaces


UNKNOWN_INTERFACE = "(unknown interface)"


def _enumerate_fallback():
    """Last resort: addresses only, without the interface name."""
    interfaces = []
    seen = set()
    for probe_target in (("8.8.8.8", 80), ("2001:4860:4860::8888", 80)):
        family = socket.AF_INET if ":" not in probe_target[0] else socket.AF_INET6
        sock = socket.socket(family, socket.SOCK_DGRAM)
        try:
            sock.connect(probe_target)
            ip = sock.getsockname()[0]
            if ip not in seen:
                seen.add(ip)
                interfaces.append(Interface(UNKNOWN_INTERFACE, ip, family))
        except OSError:
            pass
        finally:
            sock.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ip = info[4][0]
            if ip not in seen and not ip.startswith("127."):
                seen.add(ip)
                interfaces.append(Interface(UNKNOWN_INTERFACE, ip, info[0]))
    except socket.gaierror:
        pass
    return interfaces


def _sort_key(item):
    """Usable IPv4 addresses first, then everything else."""
    return (not item.is_ipv4, bool(item.note), item.name.lower())


def enumerate_interfaces():
    """List the active network interfaces, IPv4 first."""
    try:
        interfaces = _enumerate_windows() if os.name == "nt" else _enumerate_posix()
    except Exception as exc:
        log.debug("native enumeration failed (%s), using the fallback method", exc)
        interfaces = _enumerate_fallback()

    if not interfaces:
        interfaces = _enumerate_fallback()

    interfaces.sort(key=_sort_key)
    return interfaces
