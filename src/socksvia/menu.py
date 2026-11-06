"""Interactive interface picker, in the style of ``update-alternatives``."""


def print_interfaces(interfaces, current_ip=None):
    """List the interfaces; the one currently in use is marked with ``*``."""
    width = max((len(f"{i.name}: {i.ip}") for i in interfaces), default=0)
    for index, iface in enumerate(interfaces, start=1):
        mark = "*" if current_ip is not None and iface.ip == current_ip else " "
        line = f"{iface.name}: {iface.ip}"
        if iface.note:
            print(f" {mark}{index:>2}) {line:<{width}}   [{iface.note}]")
        else:
            print(f" {mark}{index:>2}) {line}")


class NoInterfaceChosen(Exception):
    """No interface was chosen: none is available, or the user cancelled.

    At startup the CLI turns it into an exit with the message; while the proxy
    runs, the ``r`` re-selection catches it and keeps the current interface.
    """


def _default_choice(interfaces, current_ip):
    """Index and label of the entry picked by Enter: the current one, else the first."""
    for index, iface in enumerate(interfaces):
        if current_ip is not None and iface.ip == current_ip:
            return index, "keep current [*]"
    return 0, "1"


def _parse_choice(answer, count):
    """Zero-based index for a valid ``1..count`` answer, otherwise ``None``."""
    if answer.isdecimal() and 1 <= int(answer) <= count:
        return int(answer) - 1
    return None


def choose_interface(interfaces, current_ip=None):
    """
    Numbered menu, ``update-alternatives`` style.

    Enter = current interface (if any), otherwise the first entry.
    Raises ``NoInterfaceChosen`` if there is nothing to choose or the user cancels.
    """
    if not interfaces:
        raise NoInterfaceChosen("No usable network interface found.")

    if len(interfaces) == 1:
        only = interfaces[0]
        print(f"Found a single usable interface: {only}")
        return only

    default, default_label = _default_choice(interfaces, current_ip)

    print()
    print("Available network interfaces:")
    print()
    print_interfaces(interfaces, current_ip)
    print()

    prompt = (
        f"Which interface should be used for outbound traffic? "
        f"[1-{len(interfaces)}, Enter = {default_label}, q to cancel]: "
    )
    while True:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise NoInterfaceChosen("Cancelled.") from None

        if answer.lower() in ("q", "quit", "exit"):
            raise NoInterfaceChosen("Cancelled.")
        if answer == "":
            return interfaces[default]
        index = _parse_choice(answer, len(interfaces))
        if index is not None:
            return interfaces[index]
        print(f"  Invalid choice. Enter a number between 1 and {len(interfaces)}.")
