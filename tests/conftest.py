import os
import socket

import pytest

from socksvia.interfaces import Interface


def pytest_collection_modifyitems(config, items):
    """Skip platform-specific tests on the wrong OS."""
    skip_posix = pytest.mark.skip(reason="POSIX-only API (getifaddrs / termios)")
    skip_windows = pytest.mark.skip(reason="Windows-only API (iphlpapi / msvcrt / registry)")
    for item in items:
        if "posix_only" in item.keywords and os.name == "nt":
            item.add_marker(skip_posix)
        if "windows_only" in item.keywords and os.name != "nt":
            item.add_marker(skip_windows)


@pytest.fixture
def sample_interfaces():
    return [
        Interface("Ethernet", "192.168.1.10", socket.AF_INET),
        Interface("Wi-Fi", "10.0.0.5", socket.AF_INET),
        Interface("Ethernet 2", "169.254.3.4", socket.AF_INET),
        Interface("Ethernet", "fe80::1", socket.AF_INET6),
    ]
