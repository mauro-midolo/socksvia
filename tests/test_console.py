import io
import logging
import socket

import pytest

from socksvia import console
from socksvia.console import KeyReader, LogGate, reselect_interface
from socksvia.interfaces import Interface
from socksvia.menu import NoInterfaceChosen


class FakeServer:
    def __init__(self, ip="10.0.0.1"):
        self.outbound = (ip, socket.AF_INET)
        self.switched = []

    def set_outbound(self, ip, family):
        self.switched.append((ip, family))
        self.outbound = (ip, family)
        return 2


@pytest.fixture
def gate():
    return LogGate()


def test_log_gate_filters_when_paused(gate):
    record = logging.LogRecord("socksvia", logging.INFO, "", 0, "msg", None, None)
    assert gate.filter(record)
    gate.paused = True
    assert not gate.filter(record)


def test_key_reader_disabled_without_tty(monkeypatch):
    monkeypatch.setattr(console.sys, "stdin", io.StringIO(""))
    sleeps = []
    monkeypatch.setattr(console.time, "sleep", sleeps.append)
    with KeyReader() as keys:
        assert not keys.enabled
        assert keys.read_key(0.5) is None
        with keys.line_mode():
            pass
    assert sleeps == [0.5]


def test_key_reader_disabled_without_stdin(monkeypatch):
    monkeypatch.setattr(console.sys, "stdin", None)
    assert not KeyReader().enabled


def _patch_menu(monkeypatch, result):
    monkeypatch.setattr(console, "enumerate_interfaces", lambda: [])

    def fake_choose(_interfaces, current_ip):
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(console, "choose_interface", fake_choose)


def test_reselect_switches_interface(monkeypatch, capsys, gate):
    server = FakeServer()
    labels = {"current": "eth0: 10.0.0.1"}
    _patch_menu(monkeypatch, Interface("lo", "127.0.0.1", socket.AF_INET))

    reselect_interface(server, labels, gate)

    assert server.switched == [("127.0.0.1", socket.AF_INET)]
    assert labels["current"] == "lo: 127.0.0.1"
    assert gate.paused is False


def test_reselect_same_interface_is_noop(monkeypatch, capsys, gate):
    server = FakeServer("10.0.0.1")
    labels = {"current": "eth0: 10.0.0.1"}
    _patch_menu(monkeypatch, Interface("eth0", "10.0.0.1", socket.AF_INET))

    reselect_interface(server, labels, gate)

    assert server.switched == []
    assert "No change" in capsys.readouterr().out


def test_reselect_cancelled(monkeypatch, capsys, gate):
    server = FakeServer()
    labels = {"current": "eth0: 10.0.0.1"}
    _patch_menu(monkeypatch, NoInterfaceChosen("Cancelled."))

    reselect_interface(server, labels, gate)

    assert server.switched == []
    assert "Cancelled. Staying on eth0: 10.0.0.1." in capsys.readouterr().out
    assert gate.paused is False


def test_reselect_unusable_ip(monkeypatch, capsys, gate):
    server = FakeServer()
    labels = {"current": "eth0: 10.0.0.1"}
    _patch_menu(monkeypatch, Interface("ghost", "203.0.113.77", socket.AF_INET))

    def refuse(_ip, _family):
        raise OSError("Cannot assign requested address")

    monkeypatch.setattr(console, "check_source_ip", refuse)

    reselect_interface(server, labels, gate)

    out = capsys.readouterr().out
    assert server.switched == []
    assert "Cannot use 203.0.113.77 as source IP" in out
    assert labels["current"] == "eth0: 10.0.0.1"
