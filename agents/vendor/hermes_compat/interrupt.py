"""``tools.interrupt`` for vendored code.

Hermes polls a per-session interrupt flag before a provider call. Nerva has no such flag
for a search: the owner's e-stop acts on the call itself, through the kernel's
``plugin.egress`` hook every request crosses, so this always answers False.
"""


def is_interrupted() -> bool:
    return False
