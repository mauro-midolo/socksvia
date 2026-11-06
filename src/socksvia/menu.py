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


def choose_interface(interfaces, current_ip=None):
    """
    Numbered menu, ``update-alternatives`` style.

    Enter = current interface (if any), otherwise the first entry.
    Raises ``SystemExit`` if there is nothing to choose or the user cancels.
    """
    if not interfaces:
        raise SystemExit("No usable network interface found.")

    if len(interfaces) == 1:
        only = interfaces[0]
        print(f"Found a single usable interface: {only}")
        return only

    default = 0
    default_label = "1"
    for index, iface in enumerate(interfaces):
        if current_ip is not None and iface.ip == current_ip:
            default = index
            default_label = "keep current [*]"
            break

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
            raise SystemExit("Cancelled.") from None

        if answer.lower() in ("q", "quit", "exit"):
            raise SystemExit("Cancelled.")
        if answer == "":
            return interfaces[default]
        if answer.isdigit():
            choice = int(answer)
            if 1 <= choice <= len(interfaces):
                return interfaces[choice - 1]
        print(f"  Invalid choice. Enter a number between 1 and {len(interfaces)}.")
