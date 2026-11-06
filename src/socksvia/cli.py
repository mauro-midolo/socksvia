"""Command-line entry point: ``socksvia``."""

import argparse
import logging
import threading

from socksvia import __version__
from socksvia.console import KeyReader, LogGate, reselect_interface
from socksvia.interfaces import enumerate_interfaces
from socksvia.menu import NoInterfaceChosen, choose_interface, print_interfaces
from socksvia.server import Socks5Handler, ThreadedSocksServer, check_source_ip, ip_family

log = logging.getLogger("socksvia")

KEY_HINT = "Press r to switch interface, Ctrl+C to stop."


def build_parser():
    parser = argparse.ArgumentParser(
        prog="socksvia",
        description="SOCKS5 proxy that pins outbound traffic to a network interface.",
    )
    parser.add_argument("--external", "-e", help="IP of the interface to use (skips the menu)")
    parser.add_argument(
        "--listen", "-l", default="127.0.0.1", help="Listen address (default: 127.0.0.1)"
    )
    parser.add_argument("--port", "-p", type=int, default=1080, help="Listen port (default: 1080)")
    parser.add_argument("--list", action="store_true", help="List the interfaces and exit")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def setup_logging(verbose):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    log_gate = LogGate()
    for log_handler in logging.getLogger().handlers:
        log_handler.addFilter(log_gate)
    return log_gate


def list_interfaces():
    interfaces = enumerate_interfaces()
    if not interfaces:
        print("No usable network interface found.")
        return 1
    print("Available network interfaces:\n")
    print_interfaces(interfaces)
    return 0


def run_until_stopped(server, label, log_gate):
    """Serve in a background thread; the main thread listens to the keyboard."""
    labels = {"current": label}

    server_thread = threading.Thread(target=server.serve_forever, name="socks-server", daemon=True)
    server_thread.start()

    try:
        with KeyReader() as keys:
            print()
            if keys.enabled:
                print(KEY_HINT)
            else:
                print("Ctrl+C to stop (r key unavailable: input is not interactive).")
            print()

            while server_thread.is_alive():
                key = keys.read_key(0.5)
                if key is None:
                    continue
                if key == "\x03":  # Ctrl+C read as a key (Windows)
                    raise KeyboardInterrupt
                if key.lower() == "r":
                    with keys.line_mode():
                        reselect_interface(server, labels, log_gate)
                    print()
                    print(KEY_HINT)
                    print()
    except KeyboardInterrupt:
        print()
        log.info("Shutting down...")
    finally:
        server.shutdown()
        server.server_close()
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    log_gate = setup_logging(args.verbose)

    if args.list:
        return list_interfaces()

    if args.external:
        external_ip = args.external
        label = external_ip
    else:
        try:
            chosen = choose_interface(enumerate_interfaces())
        except NoInterfaceChosen as exc:
            raise SystemExit(str(exc)) from None
        external_ip = chosen.ip
        label = str(chosen)

    try:
        family = ip_family(external_ip)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None

    try:
        check_source_ip(external_ip, family)
    except OSError as exc:
        raise SystemExit(f"Cannot use {external_ip} as source IP: {exc}") from None

    try:
        server = ThreadedSocksServer((args.listen, args.port), Socks5Handler, external_ip, family)
    except OSError as exc:
        raise SystemExit(
            f"Cannot listen on {args.listen}:{args.port}: {exc}\n"
            f"The port is probably already in use: try --port 1081."
        ) from None

    print()
    log.info("Outbound interface: %s", label)
    log.info("Proxy listening on: socks5://%s:%s", args.listen, args.port)

    return run_until_stopped(server, label, log_gate)
