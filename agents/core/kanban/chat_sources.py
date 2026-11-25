"""Owner-reviewed references to completed work. Receipts store only its location and digest."""

import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BoardSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    board: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    task_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    source: Literal["result", "latest_summary"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BoardReference(BoardSource):
    excerpt: str = Field(min_length=1, max_length=64_000)


def recorded_source(result, summary):
    for field, text in (("result", result), ("latest_summary", summary)):
        if isinstance(text, str) and text.strip():
            return field, text, hashlib.sha256(text.encode("utf-8")).hexdigest()
    return None
