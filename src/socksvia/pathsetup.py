"""Help put the ``socksvia`` command on PATH (``--add-to-path``).

pip installs the ``socksvia`` launcher in the "Scripts" folder of the Python
that installed it, but it never changes PATH. Several Windows Python
installations (the Python install manager, the Microsoft Store) do not put that
folder on PATH either, so after ``pip install socksvia`` the command is not
found. ``socksvia --add-to-path`` (run as ``py -m socksvia --add-to-path``)
fixes that once, only when the user asks for it.
"""

import os
import shutil
import sys
import sysconfig

COMMAND = "socksvia"


def _on_windows():
    return os.name == "nt"


def _launcher_name():
    return COMMAND + (".exe" if _on_windows() else "")


def scripts_dir():
    """The folder that holds the ``socksvia`` launcher of this Python installation.

    That is the installation's own scripts folder or, after ``pip install --user``,
    the per-user one: whichever actually contains the launcher (the first if neither).
    """
    candidates = []
    for scheme_key in ("prefix", "user"):
        try:
            path = sysconfig.get_path("scripts", sysconfig.get_preferred_scheme(scheme_key))
        except (KeyError, ValueError):
            continue
        if path and path not in candidates:
            candidates.append(path)
    for path in candidates:
        if os.path.isfile(os.path.join(path, _launcher_name())):
            return path
    return candidates[0] if candidates else sysconfig.get_path("scripts")


def _normalize(path):
    return os.path.normcase(os.path.normpath(os.path.expandvars(path.strip().strip('"'))))


def path_contains(path_value, directory, separator=os.pathsep):
    """Whether ``directory`` is one of the entries of a PATH-style string."""
    target = _normalize(directory)
    entries = (entry for entry in path_value.split(separator) if entry.strip())
    return any(_normalize(entry) == target for entry in entries)


def command_on_path():
    return shutil.which(COMMAND) is not None


def self_command(argument):
    """How the user can run ``socksvia <argument>`` without the command on PATH."""
    if _on_windows() and shutil.which("py"):
        major, minor = sys.version_info[:2]
        return f"py -{major}.{minor} -m socksvia {argument}"
    return f"{sys.executable} -m socksvia {argument}"


def path_hint():
    """Tip shown by ``python -m socksvia`` when the ``socksvia`` command is not on PATH."""
    if command_on_path():
        return None
    return (
        "Tip: the `socksvia` command is not on your PATH. "
        "To start socksvia by just typing `socksvia`, run once:\n"
        f"    {self_command('--add-to-path')}"
    )


# ---------------------------------------------------------------------------
# Windows: the per-user PATH lives in the registry (HKCU\Environment\Path)
# ---------------------------------------------------------------------------


def _read_user_path():
    """Return ``(value, registry_type)`` of the user PATH; empty if it does not exist."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ
    return value, kind


def _write_user_path(value, kind):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, kind, value)


def _broadcast_environment_change():
    """Tell Explorer (and the programs it starts from now on) that PATH changed."""
    import ctypes
    from ctypes import wintypes

    hwnd_broadcast = 0xFFFF
    wm_settingchange = 0x001A
    smto_abortifhung = 0x0002

    user32 = ctypes.WinDLL("user32")
    send = user32.SendMessageTimeoutW
    send.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPCWSTR,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    result = ctypes.c_size_t()
    send(
        hwnd_broadcast,
        wm_settingchange,
        0,
        "Environment",
        smto_abortifhung,
        5000,
        ctypes.byref(result),
    )


def _add_to_windows_user_path(directory):
    try:
        current, kind = _read_user_path()
    except OSError as exc:
        print(f"Cannot read your user PATH: {exc}")
        return 1

    if path_contains(current, directory, separator=";"):
        print(f"{directory} is already on your user PATH.")
        print("Open a new terminal and type: socksvia")
        return 0

    trimmed = current.rstrip(";")
    new_value = f"{trimmed};{directory}" if trimmed else directory
    try:
        _write_user_path(new_value, kind)
    except OSError as exc:
        print(f"Cannot update your user PATH: {exc}")
        return 1

    try:
        _broadcast_environment_change()
    except OSError:
        pass  # the change is saved anyway: it applies at the next sign-in at the latest

    print(f"Added {directory} to your user PATH (no administrator rights needed).")
    print("Open a new terminal and type: socksvia")
    print("Commands of other packages installed with this Python will work there too.")
    return 0


def _posix_instructions(directory):
    print("socksvia does not edit shell profiles. Add this line to ~/.profile")
    print("(or ~/.bashrc / ~/.zshrc), then open a new terminal:")
    print(f'    export PATH="$PATH:{directory}"')
    return 0


def add_to_path():
    """Implementation of ``socksvia --add-to-path``. Returns the exit code."""
    directory = scripts_dir()

    if path_contains(os.environ.get("PATH", ""), directory) and command_on_path():
        print(f"{directory} is already on PATH: just type socksvia")
        return 0

    if _on_windows():
        return _add_to_windows_user_path(directory)
    return _posix_instructions(directory)
