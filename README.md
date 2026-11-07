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

## License

[Apache License 2.0](LICENSE)
