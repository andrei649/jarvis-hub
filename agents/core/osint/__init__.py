"""osint — P2 OSINT Investigator pack (ORIZONT 24 Track P).

Governed correlation over *untrusted* external evidence. See :mod:`.correlate`.
"""

from .correlate import (
    Evidence,
    Finding,
    build_brief,
    correlate,
    writeback_payload,
)

__all__ = ["Evidence", "Finding", "correlate", "build_brief", "writeback_payload"]
