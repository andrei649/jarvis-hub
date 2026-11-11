# Jarvis v0.2.0 — Pure Python orchestration core with skills, checkpointing, gateway, and agent handoff

# RB-2: NERVA_<X> is the preferred spelling of every JARVIS_<X> (env_alias). The fold
# into the process environment happens here, once, when the core package is first
# imported under either of its names (``agents.core`` or ``core``): no hub module can be
# imported before its package, so none reads the environment before this line. It moves
# names, never raises, and logs no value; a contradiction is left for the boot guard.
from .env_alias import normalize_process_env as _normalize_process_env

_normalize_process_env()
