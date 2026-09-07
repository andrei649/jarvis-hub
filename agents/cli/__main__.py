"""``python -m agents.cli …`` — the `nerva` command without the wrapper script."""

import sys

from .nerva import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
