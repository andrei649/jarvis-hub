"""``python -m agents.cli …`` — the `nerva` command without the wrapper script."""

import sys

from .env_spelling import main  # RB-2: refuses a variable set twice, then .nerva.main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
