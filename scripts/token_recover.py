#!/usr/bin/env python3
"""token_recover.py — offline token recovery on the hub's own box, in the hub's own store.

    python scripts/token_recover.py rotate admin [ttl_days]
    python scripts/token_recover.py issue  user  [ttl_days]
    python scripts/token_recover.py revoke admin|user|all [--revoke-env]
    python scripts/token_recover.py list

The verbs are ``agents.core.security.token_store``'s own. What this adds is the hub's
view of where that store lives: the hub loads its .env files before it opens
``security/tokens.db``, so a ``JARVIS_USER_HOME`` set only in one of them moves the store
(``JARVIS_HOME`` is read from the process environment only, by the hub and here alike).
Run bare, the store's CLI reads only the process environment, and a token rotated there
lands in a file the hub never reads (review-H273g m2). This loads the same .env files
first, then says on stderr which file it wrote: check that path, since like the hub it
creates the data home (its folders, a README and a .env) where none is, and a mistyped
``JARVIS_USER_HOME`` gets a new, empty home. Filesystem access to the box is the root of
trust, as for the store's own CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from agents.core.env_provenance import load_hub_env

    load_hub_env()
    from agents.core.security import token_store

    store = token_store.get_token_store()
    print(f"token store: {getattr(store, '_path', '?')}", file=sys.stderr)
    return token_store._main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
