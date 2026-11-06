"""Keyboard handling while the proxy runs (press ``r`` to pick another interface)."""

import contextlib
import logging
import os
import select
import sys
import time

from socksvia.interfaces import enumerate_interfaces
from socksvia.menu import NoInterfaceChosen, choose_interface
from socksvia.server import check_source_ip, ip_family

log = logging.getLogger("socksvia")


class KeyReader:
    """Read single keys without waiting for Enter, on Windows and on Linux/macOS."""

    def __init__(self):
        self.enabled = sys.stdin is not None and sys.stdin.isatty()
        self._fd = None
        self._saved = None

    def __enter__(self):
        if self.enabled and os.name != "nt":
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc_info):
        if self._saved is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)

    def read_key(self, timeout):
        """A pressed key, or ``None`` if nothing arrives within ``timeout`` seconds."""
        if not self.enabled:
            time.sleep(timeout)
            return None

        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if msvcrt.kbhit():
                    return msvcrt.getwch()
                time.sleep(0.05)
            return None

        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            return os.read(self._fd, 1).decode(errors="ignore")
        return None

    @contextlib.contextmanager
    def line_mode(self):
        """Temporarily restore the normal terminal (echo + Enter) for ``input()``."""
        if self._saved is None:
            yield
            return
        import termios
        import tty

        termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        try:
            yield
        finally:
            tty.setcbreak(self._fd)


class LogGate(logging.Filter):
    """Silence logging while the menu is on screen, so it is not cluttered."""

    paused = False

    def filter(self, record):
        return not self.paused


def reselect_interface(server, labels, log_gate):
    """Show the menu again and, if the choice changes, move the traffic."""
    current_ip = server.outbound[0]

    log_gate.paused = True
    try:
        chosen = choose_interface(enumerate_interfaces(), current_ip)
    except NoInterfaceChosen as exc:
        print(f"{exc} Staying on {labels['current']}.")
        return
    finally:
        log_gate.paused = False

    if chosen.ip == current_ip:
        print(f"No change, staying on {labels['current']}.")
        return

    try:
        family = ip_family(chosen.ip)
        check_source_ip(chosen.ip, family)
    except (ValueError, OSError) as exc:
        print(f"Cannot use {chosen.ip} as source IP: {exc}")
        print(f"Staying on {labels['current']}.")
        return

    closed = server.set_outbound(chosen.ip, family)
    labels["current"] = str(chosen)
    print()
    log.info("Outbound interface: %s", labels["current"])
    if closed:
        log.info("Closed %d open connections on the previous interface.", closed)
