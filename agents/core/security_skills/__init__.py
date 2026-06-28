"""security_skills — 0.42 Security Skills Pack (curated defensive-security knowledge).

A pure, offline, read-only knowledge pack over public taxonomies (MITRE ATT&CK,
MITRE D3FEND, NIST CSF 2.0): tactics/techniques, a behavior→technique heuristic,
and a defensive-playbook assembler. Honest curated subset — never the full corpus,
never fabricated, never acts. See :mod:`.pack`.
"""

from .pack import (
    DISCLAIMER,
    SOURCES,
    build_playbook,
    frameworks,
    map_behavior,
    tactics,
    technique,
    techniques,
)

__all__ = [
    "DISCLAIMER",
    "SOURCES",
    "tactics",
    "techniques",
    "technique",
    "map_behavior",
    "frameworks",
    "build_playbook",
]
