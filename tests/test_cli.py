import socket

import pytest

from socksvia import __version__, cli
from socksvia.interfaces import Interface


class TestParser:
    def test_defaults(self):
        args = cli.build_parser().parse_args([])
        assert args.external is None
        assert args.listen == "127.0.0.1"
        assert args.port == 1080
        assert args.list is False
        assert args.verbose is False

    def test_short_options(self):
        args = cli.build_parser().parse_args(
            ["-e", "10.0.0.5", "-l", "0.0.0.0", "-p", "1081", "-v"]
        )
        assert args.external == "10.0.0.5"
        assert args.listen == "0.0.0.0"
        assert args.port == 1081
        assert args.verbose is True

    def test_long_options(self):
        args = cli.build_parser().parse_args(
            ["--external", "fe80::1", "--listen", "::1", "--port", "9050", "--list"]
        )
        assert args.external == "fe80::1"
        assert args.listen == "::1"
        assert args.port == 9050
        assert args.list is True

    def test_port_must_be_integer(self, capsys):
        parser = cli.build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["--port", "abc"])
        assert excinfo.value.code == 2
        assert "invalid int value" in capsys.readouterr().err

    def test_version(self, capsys):
        parser = cli.build_parser()
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(["--version"])
        assert excinfo.value.code == 0
        assert capsys.readouterr().out.strip() == f"socksvia {__version__}"


class TestMain:
    def test_list(self, monkeypatch, capsys, sample_interfaces):
        monkeypatch.setattr(cli, "enumerate_interfaces", lambda: sample_interfaces)
        assert cli.main(["--list"]) == 0
        out = capsys.readouterr().out
        assert "Available network interfaces" in out
        assert "Wi-Fi: 10.0.0.5" in out

    def test_list_empty(self, monkeypatch, capsys):
        monkeypatch.setattr(cli, "enumerate_interfaces", lambda: [])
        assert cli.main(["--list"]) == 1
        assert "No usable network interface" in capsys.readouterr().out

    def test_invalid_external_ip(self):
        with pytest.raises(SystemExit, match="invalid source IP: nope"):
            cli.main(["--external", "nope"])

    def test_unassigned_external_ip(self):
        with pytest.raises(SystemExit, match=r"Cannot use 203\.0\.113\.77 as source IP"):
            cli.main(["--external", "203.0.113.77"])

    def test_port_in_use(self, monkeypatch):
        def busy(*_args, **_kwargs):
            raise OSError(98, "Address already in use")

        monkeypatch.setattr(cli, "ThreadedSocksServer", busy)
        with pytest.raises(SystemExit, match="try --port 1081"):
            cli.main(["--external", "127.0.0.1"])

    def test_external_skips_menu_and_starts(self, monkeypatch):
        started = {}

        def fake_run(server, label, _gate):
            started["outbound"] = server.outbound
            started["label"] = label
            server.server_close()
            return 0

        def no_menu(_interfaces):
            raise AssertionError("menu must not be shown with --external")

        monkeypatch.setattr(cli, "run_until_stopped", fake_run)
        monkeypatch.setattr(cli, "choose_interface", no_menu)

        assert cli.main(["--external", "127.0.0.1", "--port", "0"]) == 0
        assert started == {"outbound": ("127.0.0.1", socket.AF_INET), "label": "127.0.0.1"}

    def test_menu_choice_is_used(self, monkeypatch):
        chosen = Interface("lo", "127.0.0.1", socket.AF_INET)
        started = {}

        def fake_run(server, label, _gate):
            started["label"] = label
            server.server_close()
            return 0

        monkeypatch.setattr(cli, "enumerate_interfaces", lambda: [chosen])
        monkeypatch.setattr(cli, "choose_interface", lambda _interfaces: chosen)
        monkeypatch.setattr(cli, "run_until_stopped", fake_run)

        assert cli.main(["--port", "0"]) == 0
        assert started["label"] == "lo: 127.0.0.1"

    def test_run_until_stopped_handles_ctrl_c(self, monkeypatch, capsys):
        """Non-interactive stdin: the loop sleeps; Ctrl+C stops the server cleanly."""

        class StopReader:
            enabled = False

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read_key(self, _timeout):
                raise KeyboardInterrupt

        monkeypatch.setattr(cli, "KeyReader", StopReader)
        server = cli.ThreadedSocksServer(
            ("127.0.0.1", 0), cli.Socks5Handler, "127.0.0.1", socket.AF_INET
        )
        assert cli.run_until_stopped(server, "lo: 127.0.0.1", cli.LogGate()) == 0
        assert "input is not interactive" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("interfaces", "answer", "message"),
    [
        ([], None, "No usable network interface found."),
        (
            [
                Interface("eth0", "10.0.0.1", socket.AF_INET),
                Interface("eth1", "10.0.0.2", socket.AF_INET),
            ],
            "q",
            "Cancelled.",
        ),
    ],
)
def test_menu_without_choice_exits_with_message(monkeypatch, interfaces, answer, message):
    """At startup, no choice still stops the program with the message, as before."""
    monkeypatch.setattr(cli, "enumerate_interfaces", lambda: interfaces)
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == message
