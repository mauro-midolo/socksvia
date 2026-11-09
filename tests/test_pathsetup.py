import os
import runpy
import sys

import pytest

from socksvia import cli, pathsetup

SCRIPTS = os.path.join(os.sep, "py", "Scripts")


class FakeRegistry:
    """In-memory stand-in for HKCU\\Environment\\Path."""

    def __init__(self, value="", kind=2, fail_read=False, fail_write=False):
        self.value = value
        self.kind = kind
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.writes = []
        self.broadcasts = 0

    def read(self):
        if self.fail_read:
            raise OSError("access denied")
        return self.value, self.kind

    def write(self, value, kind):
        if self.fail_write:
            raise OSError("access denied")
        self.writes.append((value, kind))
        self.value, self.kind = value, kind

    def broadcast(self):
        self.broadcasts += 1


@pytest.fixture
def windows(monkeypatch):
    """Run the Windows code path with a fake registry, on any OS."""
    registry = FakeRegistry()
    monkeypatch.setattr(pathsetup, "_on_windows", lambda: True)
    monkeypatch.setattr(pathsetup, "scripts_dir", lambda: SCRIPTS)
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: False)
    monkeypatch.setattr(pathsetup, "_read_user_path", registry.read)
    monkeypatch.setattr(pathsetup, "_write_user_path", registry.write)
    monkeypatch.setattr(pathsetup, "_broadcast_environment_change", registry.broadcast)
    monkeypatch.setenv("PATH", "")
    return registry


# ---------------------------------------------------------------------------
# PATH helpers
# ---------------------------------------------------------------------------


def test_path_contains_ignores_trailing_separator_and_quotes():
    other = os.path.join(os.sep, "usr", "bin")
    value = os.pathsep.join([other, f'"{SCRIPTS}{os.sep}"', ""])
    assert pathsetup.path_contains(value, SCRIPTS)
    assert not pathsetup.path_contains(other, SCRIPTS)
    assert not pathsetup.path_contains("", SCRIPTS)


def test_scripts_dir_prefers_the_folder_with_the_launcher(monkeypatch, tmp_path):
    base, user = tmp_path / "base", tmp_path / "user"
    base.mkdir()
    user.mkdir()
    (user / pathsetup._launcher_name()).write_text("")
    folders = {"prefix": str(base), "user": str(user)}
    monkeypatch.setattr(pathsetup.sysconfig, "get_preferred_scheme", lambda key: key)
    monkeypatch.setattr(pathsetup.sysconfig, "get_path", lambda _name, scheme: folders[scheme])
    assert pathsetup.scripts_dir() == str(user)


def test_scripts_dir_defaults_to_the_installation_folder(monkeypatch, tmp_path):
    folders = {"prefix": str(tmp_path / "base"), "user": str(tmp_path / "user")}
    monkeypatch.setattr(pathsetup.sysconfig, "get_preferred_scheme", lambda key: key)
    monkeypatch.setattr(pathsetup.sysconfig, "get_path", lambda _name, scheme: folders[scheme])
    assert pathsetup.scripts_dir() == folders["prefix"]


def test_scripts_dir_of_this_interpreter_exists():
    assert os.path.isdir(pathsetup.scripts_dir())


def test_self_command_uses_py_launcher_on_windows(monkeypatch):
    monkeypatch.setattr(pathsetup, "_on_windows", lambda: True)
    monkeypatch.setattr(pathsetup.shutil, "which", lambda name: "C:\\Windows\\py.exe")
    major, minor = sys.version_info[:2]
    assert pathsetup.self_command("--list") == f"py -{major}.{minor} -m socksvia --list"


def test_self_command_falls_back_to_the_interpreter(monkeypatch):
    monkeypatch.setattr(pathsetup, "_on_windows", lambda: False)
    assert pathsetup.self_command("--list") == f"{sys.executable} -m socksvia --list"


# ---------------------------------------------------------------------------
# Hint shown by `python -m socksvia`
# ---------------------------------------------------------------------------


def test_hint_when_command_missing(monkeypatch):
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: False)
    hint = pathsetup.path_hint()
    assert "not on your PATH" in hint
    assert hint.rstrip().endswith("-m socksvia --add-to-path")


def test_no_hint_when_command_available(monkeypatch):
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: True)
    assert pathsetup.path_hint() is None


def _run_module(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["socksvia", *args])
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("socksvia", run_name="__main__", alter_sys=False)
    return excinfo.value.code


def test_python_m_socksvia_prints_hint(monkeypatch, capsys):
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: False)
    assert _run_module(monkeypatch, "--version") == 0
    captured = capsys.readouterr()
    assert "--add-to-path" in captured.err
    assert captured.out.startswith("socksvia ")


def test_python_m_socksvia_no_hint_for_add_to_path(monkeypatch, capsys):
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: False)
    monkeypatch.setattr(cli, "add_to_path", lambda: 0)
    assert _run_module(monkeypatch, "--add-to-path") == 0
    assert capsys.readouterr().err == ""


# ---------------------------------------------------------------------------
# --add-to-path
# ---------------------------------------------------------------------------


def test_cli_dispatches_add_to_path(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "add_to_path", lambda: calls.append(1) or 0)
    assert cli.main(["--add-to-path"]) == 0
    assert calls == [1]


def test_windows_appends_to_existing_user_path(windows, capsys):
    windows.value, windows.kind = "C:\\Tools;%USERPROFILE%\\bin;", 2  # REG_EXPAND_SZ
    assert pathsetup.add_to_path() == 0
    assert windows.writes == [(f"C:\\Tools;%USERPROFILE%\\bin;{SCRIPTS}", 2)]
    assert windows.broadcasts == 1
    out = capsys.readouterr().out
    assert f"Added {SCRIPTS}" in out
    assert "Open a new terminal" in out


def test_windows_creates_user_path_and_keeps_registry_type(windows):
    windows.value, windows.kind = "", 1  # REG_SZ
    assert pathsetup.add_to_path() == 0
    assert windows.writes == [(SCRIPTS, 1)]


def test_windows_already_in_user_path_is_not_duplicated(windows, capsys):
    windows.value = f"C:\\Tools;{SCRIPTS}"
    assert pathsetup.add_to_path() == 0
    assert windows.writes == []
    assert "already on your user PATH" in capsys.readouterr().out


def test_already_reachable_changes_nothing(windows, monkeypatch, capsys):
    monkeypatch.setenv("PATH", SCRIPTS)
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: True)
    assert pathsetup.add_to_path() == 0
    assert windows.writes == []
    assert "just type socksvia" in capsys.readouterr().out


def test_windows_read_error(windows, capsys):
    windows.fail_read = True
    assert pathsetup.add_to_path() == 1
    assert "Cannot read your user PATH" in capsys.readouterr().out


def test_windows_write_error(windows, capsys):
    windows.fail_write = True
    assert pathsetup.add_to_path() == 1
    assert "Cannot update your user PATH" in capsys.readouterr().out
    assert windows.broadcasts == 0


def test_windows_broadcast_failure_is_not_fatal(windows, monkeypatch):
    def broken():
        raise OSError("no desktop")

    monkeypatch.setattr(pathsetup, "_broadcast_environment_change", broken)
    assert pathsetup.add_to_path() == 0
    assert windows.writes


def test_posix_prints_instructions_and_changes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(pathsetup, "_on_windows", lambda: False)
    monkeypatch.setattr(pathsetup, "scripts_dir", lambda: "/home/me/.local/bin")
    monkeypatch.setattr(pathsetup, "command_on_path", lambda: False)
    monkeypatch.setenv("PATH", "/usr/bin")
    assert pathsetup.add_to_path() == 0
    assert 'export PATH="$PATH:/home/me/.local/bin"' in capsys.readouterr().out


@pytest.mark.windows_only
def test_real_user_path_can_be_read():
    """Read-only check of the real registry access (Windows only, nothing is written)."""
    value, kind = pathsetup._read_user_path()
    assert isinstance(value, str)
    assert kind in (1, 2)  # REG_SZ, REG_EXPAND_SZ
