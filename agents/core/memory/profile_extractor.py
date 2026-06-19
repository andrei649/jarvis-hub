"""
Profile extractor — derives user facts/preferences from conversation history.
Runs periodically to keep the profile fresh. All writes go through MemoryStore.
"""
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class ProfileFact:
    category: str        # e.g. "preference", "fact", "habit", "goal"
    key: str             # e.g. "language", "timezone", "wake_time"
    value: str
    confidence: float = 1.0   # 0–1
    source: str = "extraction"

# Simple rule-based extraction patterns (LLM-enhanced extraction is H8.2+)
_PATTERNS = [
    (r"\bmy name is ([a-z][a-z]+)\b", "fact", "name"),
    (r"\bi('m| am) in ([a-z ]+)\b", "fact", "location"),
    (r"\bi (prefer|like|love|use) ([a-z0-9 _-]+)\b", "preference", "preference"),
    (r"\bwake up at (\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", "habit", "wake_time"),
    (r"\bmy timezone is ([a-z/_]+)\b", "fact", "timezone"),
]

def extract_facts(text: str) -> list[ProfileFact]:
    """Extract structured facts from a single message/conversation turn."""
    facts = []
    text_lower = text.lower()
    for pattern, category, key in _PATTERNS:
        m = re.search(pattern, text_lower)
        if m:
            value = m.group(m.lastindex or 1).strip()
            if value:
                facts.append(ProfileFact(category=category, key=key, value=value, confidence=0.8))
    return facts

async def process_conversation(messages: list[dict], store) -> int:
    """
    Extract facts from a list of message dicts ({"role": ..., "content": ...})
    and persist them in the given MemoryStore. Returns count of new facts stored.
    """
    count = 0
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        facts = extract_facts(content)
        for fact in facts:
            try:
                await store.upsert(fact.category, fact.key, fact.value,
                                   metadata={"confidence": fact.confidence, "source": fact.source})
                count += 1
            except Exception:
                logger.warning("Failed to store fact %s/%s", fact.category, fact.key, exc_info=True)
    return count
