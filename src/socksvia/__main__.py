"""Allow ``python -m socksvia``."""

import sys

from socksvia.cli import main

if __name__ == "__main__":
    sys.exit(main())
