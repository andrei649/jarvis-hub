"""Parse TLE catalog text (Celestrak / Space-Track) into records."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class TleRecord:
    name: str
    norad_id: int
    line1: str
    line2: str


def parse_tle_text(text: str) -> Iterator[TleRecord]:
    """Yield TleRecord for each 3-line (name, line1, line2) block in a TLE catalog.

    Tolerates blank lines and trailing whitespace; skips malformed blocks.
    """
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    for i in range(0, len(lines) - 2, 3):
        name, line1, line2 = lines[i], lines[i + 1], lines[i + 2]
        if not (line1.startswith("1 ") and line2.startswith("2 ")):
            continue
        try:
            norad_id = int(line1[2:7])
        except ValueError:
            continue
        yield TleRecord(name=name.strip(), norad_id=norad_id, line1=line1, line2=line2)
