"""The `nerva` command — one discoverable command tree for the whole product.

Hermes absorption, wave 1 (docs/HERMES_ABSORPTION.md). Nerva had 83 HTTP routers and a
governed kernel behind a browser tab on 127.0.0.1, and a terminal that offered `serve.py`,
a three-target Makefile and ~35 unrelated argparse scripts — a headless or SSH install could
not be configured, diagnosed or recovered. Every verb here that moves anything calls the
same admin-guarded HTTP route the HUD calls, so it inherits the kernel and the approval
queue for free; the offline verbs (`doctor`, `config`, `logs`, `kernel explain`) read the
same data root the hub reads and never need it running.
"""

from .nerva import build_parser, main

__all__ = ["build_parser", "main"]
