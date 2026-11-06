import socket

import pytest

from socksvia.interfaces import Interface
from socksvia.menu import choose_interface, print_interfaces


def feed_input(monkeypatch, *answers):
    """Make input() return the given answers in order (or raise them if exceptions)."""
    pending = list(answers)
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        answer = pending.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr("builtins.input", fake_input)
    return prompts


def test_print_interfaces_marks_current_and_notes(capsys, sample_interfaces):
    print_interfaces(sample_interfaces, current_ip="10.0.0.5")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "   1) Ethernet: 192.168.1.10"
    assert lines[1] == " * 2) Wi-Fi: 10.0.0.5"
    assert lines[2].startswith("   3) Ethernet 2: 169.254.3.4")
    assert lines[2].endswith("[APIPA, no DHCP]")
    assert lines[3].endswith("[link-local]")


def test_no_interfaces_exits():
    with pytest.raises(SystemExit, match="No usable network interface"):
        choose_interface([])


def test_single_interface_is_returned_without_prompt(monkeypatch, capsys):
    only = Interface("eth0", "10.0.0.1", socket.AF_INET)
    prompts = feed_input(monkeypatch)
    assert choose_interface([only]) is only
    assert prompts == []
    assert "single usable interface" in capsys.readouterr().out


def test_enter_picks_first_by_default(monkeypatch, sample_interfaces):
    prompts = feed_input(monkeypatch, "")
    assert choose_interface(sample_interfaces) is sample_interfaces[0]
    assert "Enter = 1" in prompts[0]


def test_enter_keeps_current(monkeypatch, sample_interfaces):
    prompts = feed_input(monkeypatch, "")
    assert choose_interface(sample_interfaces, "10.0.0.5") is sample_interfaces[1]
    assert "keep current [*]" in prompts[0]


def test_number_selects_entry(monkeypatch, sample_interfaces):
    feed_input(monkeypatch, " 3 ")
    assert choose_interface(sample_interfaces) is sample_interfaces[2]


@pytest.mark.parametrize("bad", ["0", "5", "abc", "-1", "1.5"])
def test_invalid_answers_are_retried(monkeypatch, capsys, sample_interfaces, bad):
    feed_input(monkeypatch, bad, "2")
    assert choose_interface(sample_interfaces) is sample_interfaces[1]
    assert "Invalid choice" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["q", "Q", "quit", "exit"])
def test_quit_cancels(monkeypatch, sample_interfaces, answer):
    feed_input(monkeypatch, answer)
    with pytest.raises(SystemExit, match="Cancelled"):
        choose_interface(sample_interfaces)


@pytest.mark.parametrize("exc", [EOFError(), KeyboardInterrupt()])
def test_eof_or_ctrl_c_cancels(monkeypatch, sample_interfaces, exc):
    feed_input(monkeypatch, exc)
    with pytest.raises(SystemExit, match="Cancelled"):
        choose_interface(sample_interfaces)
