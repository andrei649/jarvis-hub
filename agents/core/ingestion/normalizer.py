from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class NormalizedMessage:
    source: str
    conversation_id: str
    sender: str
    is_me: bool
    text: str
    timestamp: float
    metadata: dict = field(default_factory=dict)
    embedding: Optional[list[float]] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NormalizedMessage":
        return cls(**data)
