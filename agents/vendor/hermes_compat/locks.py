"""``threading`` for vendored code (rewrite rule ``threading-locks``): locks only.

``providers/base.py`` guards its lazy header resolution with an ``RLock``. A vendored
profile starts no thread in Nerva, so ``Thread`` is absent on purpose.
"""

from threading import Lock, RLock

__all__ = ["Lock", "RLock"]
