# socksvia

[![CI](https://github.com/mauro-midolo/socksvia/actions/workflows/ci.yml/badge.svg)](https://github.com/mauro-midolo/socksvia/actions/workflows/ci.yml)
[![Release](https://github.com/mauro-midolo/socksvia/actions/workflows/release.yml/badge.svg)](https://github.com/mauro-midolo/socksvia/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/socksvia?logo=pypi&logoColor=white)](https://pypi.org/project/socksvia/)
[![Python](https://img.shields.io/pypi/pyversions/socksvia?logo=python&logoColor=white)](https://pypi.org/project/socksvia/)
[![License](https://img.shields.io/github/license/mauro-midolo/socksvia)](https://github.com/mauro-midolo/socksvia/blob/main/LICENSE)

[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=mauro-midolo_socksvia&metric=bugs)](https://sonarcloud.io/project/issues?id=mauro-midolo_socksvia&resolved=false&types=BUG)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=mauro-midolo_socksvia&metric=vulnerabilities)](https://sonarcloud.io/project/issues?id=mauro-midolo_socksvia&resolved=false&types=VULNERABILITY)

Tiny SOCKS5 proxy that routes traffic through the network interface you choose.
Pure Python, no dependencies, no admin rights.

Got two network cards (say, office LAN and a 4G dongle) and want *one* browser
profile to go out through the second one, without touching the routing table?
Start `socksvia`, pick the interface from a menu, and point the browser at
`socks5://127.0.0.1:1080`.

- Lists the active interfaces with name and IP, `update-alternatives` style
- Every outbound connection is bound to the chosen interface's source IP
- DNS names are resolved by the proxy (SOCKS5 "remote DNS")
- Press <kbd>r</kbd> while it runs to switch interface without restarting;
  open connections are closed so the browser reconnects through the new one
- Standard library only, Windows / Linux / macOS, Python 3.10+
- Listens on `127.0.0.1:1080` by default: no administrator rights needed

## Installation

```bash
pipx install socksvia
```

or, in any virtual environment:

```bash
pip install socksvia
```

## Usage

```bash
socksvia                       # interactive menu
socksvia --external 10.0.0.5   # skip the menu, use this source IP
socksvia --list                # list the interfaces and exit
socksvia --port 1081           # listen on another port
socksvia --version
```

`python -m socksvia` works too.

```text
$ socksvia

Available network interfaces:

   1) Ethernet: 192.168.1.20
   2) Wi-Fi: 10.0.0.5
   3) Ethernet 2: 169.254.12.7   [APIPA, no DHCP]

Which interface should be used for outbound traffic? [1-3, Enter = 1, q to cancel]: 2

14:02:11 INFO    Outbound interface: Wi-Fi: 10.0.0.5
14:02:11 INFO    Proxy listening on: socks5://127.0.0.1:1080

Press r to switch interface, Ctrl+C to stop.
```

While the proxy runs:

| Key        | Action                                                 |
|------------|--------------------------------------------------------|
| `r`        | choose the outbound interface again (no restart)       |
| `Ctrl+C`   | stop the proxy                                         |

### Options

| Option                | Default     | Description                              |
|-----------------------|-------------|------------------------------------------|
| `-e`, `--external IP` | menu        | source IP of the interface to use        |
| `-l`, `--listen ADDR` | `127.0.0.1` | listen address                           |
| `-p`, `--port PORT`   | `1080`      | listen port                              |
| `--list`              |             | list the interfaces and exit             |
| `-v`, `--verbose`     |             | debug logging                            |
| `--version`           |             | print the version and exit               |

### Browser example

Chrome / Edge with a separate profile, so your normal browsing is unaffected
(Windows `cmd`):

```bat
chrome.exe --user-data-dir="%USERPROFILE%\chrome-nic2" ^
           --proxy-server="socks5://127.0.0.1:1080"
```

Linux / macOS:

```bash
google-chrome --user-data-dir="$HOME/.chrome-nic2" --proxy-server="socks5://127.0.0.1:1080"
```

Firefox: *Settings → Network Settings → Manual proxy configuration →
SOCKS Host `127.0.0.1`, Port `1080`, SOCKS v5*, and tick
*Proxy DNS when using SOCKS v5*.

`curl`:

```bash
curl --socks5-hostname 127.0.0.1:1080 https://ifconfig.me
```

## How it works and limitations

`socksvia` binds every outbound socket to the source IP of the interface you
chose (`bind((ip, 0))` before `connect()`), and resolves host names itself so
DNS lookups go through the same path.

- **Windows**: binding the source IP is enough to make the OS send the
  traffic out of that interface (strong host model).
- **macOS**: usually enough as well, thanks to scoped routing for sockets
  bound to an interface address.
- **Linux**: the kernel uses the *weak host model*: with a single default
  route, packets with the second card's source IP may still leave through the
  default interface. If that happens you need a policy route for that source
  address (e.g. `ip rule add from 10.0.0.5 table 100` plus a default route in
  table 100). `socksvia` does **not** use `SO_BINDTODEVICE`, which would need
  root/`CAP_NET_RAW`.
- Only the SOCKS5 `CONNECT` command (TCP) is supported: no `BIND`, no `UDP
  ASSOCIATE`, no authentication. Keep it on `127.0.0.1` unless you trust the
  network you expose it to.
- The address family follows the chosen interface: with an IPv4 interface,
  IPv6-only destinations are unreachable (and vice versa).

## Development

The project uses [uv](https://docs.astral.sh/uv/); the exact versions of all
development and release tools are pinned in `uv.lock` (CI installs them with
`uv sync --locked`).

```bash
git clone https://github.com/mauro-midolo/socksvia
cd socksvia
uv sync            # creates .venv with socksvia (editable) + dev tools
```

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build && uv run twine check --strict dist/*
```

After changing the dependency groups in `pyproject.toml`, run `uv lock` and
commit `uv.lock`. Without uv, `python -m pip install --group dev -e .`
(pip >= 25.1) also works, but does not use the locked versions.

Some tests exercise platform-specific code (`getifaddrs`/`termios` on
Linux/macOS, `iphlpapi`/`msvcrt` on Windows) and are skipped on the other
platforms; CI runs the suite on all three.

### Commit messages and releases

Releases are fully automatic: every push to `main` runs the checks and then
[python-semantic-release](https://python-semantic-release.readthedocs.io/),
which reads [Conventional Commits](https://www.conventionalcommits.org/) since
the last tag:

| Commit                                       | Release (while on 0.x) |
|----------------------------------------------|------------------------|
| `fix: ...`, `perf: ...`                      | patch `0.1.0 → 0.1.1`  |
| `feat: ...`                                  | minor `0.1.0 → 0.2.0`  |
| `feat!: ...` / `BREAKING CHANGE:` footer     | minor `0.1.0 → 0.2.0`  |
| `docs:`, `chore:`, `ci:`, `test:`, `refactor:` ... | no release       |

After `1.0.0` a breaking change bumps the major version. When a release is
due, the workflow updates the version in `pyproject.toml` and
`src/socksvia/__init__.py`, updates [CHANGELOG.md](CHANGELOG.md), commits,
tags `vX.Y.Z`, creates a GitHub Release with the wheel and sdist, and publishes
to PyPI with Trusted Publishing.

When merging pull requests with *squash*, the PR title becomes the commit
message: write it as a Conventional Commit.

## License

[Apache License 2.0](LICENSE)
