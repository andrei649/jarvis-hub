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

from agents.cli.env_spelling import main as checked_main  # noqa: E402
from agents.cli.nerva import main  # noqa: E402,F401

if __name__ == "__main__":
    # RB-2: NERVA_<X> is the preferred spelling of JARVIS_<X>; a variable set under both,
    # differently, is refused by name before the command tree runs (agents.cli.env_spelling).
    raise SystemExit(checked_main(sys.argv[1:]))
