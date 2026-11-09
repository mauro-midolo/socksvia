"""Allow ``python -m socksvia``."""

import sys

from socksvia.cli import main
from socksvia.pathsetup import path_hint


def run():
    if "--add-to-path" not in sys.argv[1:]:
        hint = path_hint()
        if hint:
            print(hint, file=sys.stderr)
    return main()


if __name__ == "__main__":
    sys.exit(run())
