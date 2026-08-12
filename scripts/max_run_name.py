#!/usr/bin/env python3
"""max_run_name.py — draw a two-word name for a Max run. (Spark S-002.)

The charm ledger made real: every Max run gets a name like `nimble-beacon` from the
entropy table in MAX.md §6. This is the drawer — stdlib only, no side effects but
stdout, deletable in one commit. It exists to make the ritual reproducible (a seed
draws the same name twice) and greppable, not to do anything load-bearing.

    python scripts/max_run_name.py            # a fresh random name + a tagline
    python scripts/max_run_name.py --seed 42  # deterministic (same seed → same name)
    python scripts/max_run_name.py --plain    # just the name, for scripts/branches

The word lists are the ones in MAX.md §6; keep them in sync if that table changes.
"""

from __future__ import annotations

import argparse
import random

ADJECTIVES = (
    "amber", "bold", "copper", "drowsy", "electric", "feral", "gilded", "hushed",
    "iron", "jade", "lucid", "midnight", "nimble", "oblique", "pale", "quiet",
)
NOUNS = (
    "anvil", "beacon", "cipher", "dune", "ember", "fjord", "gale", "harbor",
    "isle", "knot", "lantern", "meridian", "nectar", "orbit", "prism", "quill",
)

# One tiny honest tagline per noun — the smile, not a promise. A beacon guides,
# a cipher keeps a secret; the point is a wink, not a feature.
_TAGLINES = {
    "anvil": "where rough work gets shaped",
    "beacon": "lit so the next run finds its way",
    "cipher": "keeps what it's told",
    "dune": "moves quietly, ends up somewhere new",
    "ember": "small, still warm, ready to catch",
    "fjord": "goes deep between hard walls",
    "gale": "arrives fast, clears the air",
    "harbor": "a safe place to tie up green",
    "isle": "self-contained, on purpose",
    "knot": "holds under load",
    "lantern": "carried, not installed",
    "meridian": "knows which way is true",
    "nectar": "worth the trip",
    "orbit": "comes back around",
    "prism": "one input, honest colors out",
    "quill": "leaves a legible trail",
}


def draw(seed: int | None = None) -> tuple[str, str]:
    # Cosmetic run-name draw, never a security decision — a predictable name is a
    # feature (--seed reproduces it), so the non-crypto PRNG is the right tool.
    rng = random.Random(seed)  # nosec B311
    adj = rng.choice(ADJECTIVES)
    noun = rng.choice(NOUNS)
    return f"{adj}-{noun}", _TAGLINES.get(noun, "a run with a name")


def main() -> None:
    ap = argparse.ArgumentParser(description="Draw a Max run name (Spark S-002).")
    ap.add_argument("--seed", type=int, default=None, help="deterministic draw")
    ap.add_argument("--plain", action="store_true", help="print only the name")
    args = ap.parse_args()

    name, tagline = draw(args.seed)
    if args.plain:
        print(name)
    else:
        print(f"⚡ {name} — {tagline}")


if __name__ == "__main__":
    main()
