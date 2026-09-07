#!/usr/bin/env python3
"""``nerva`` — one command for the whole product (``python scripts/nerva.py --help``).

The tree lives in ``agents/cli``; this wrapper only puts the checkout on ``sys.path`` so the
command works from any directory, like the other scripts here.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.cli.nerva import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
