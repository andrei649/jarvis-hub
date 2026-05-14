import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("memory")


class MemoryManager:
    def __init__(self, storage_path: str = "data/memory"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._episodic: dict[str, list[dict]] = {}
        self._semantic: dict[str, dict] = {}

    async def store(self, agent_id: str, query: str, response: str, metadata: dict = None):
        entry = {
            "query": query,
            "response": response,
            "metadata": metadata or {},
            "tokens": self._tokenize(f"{query} {response}"),
            "timestamp": datetime.now().isoformat(),
        }
        if agent_id not in self._episodic:
            self._episodic[agent_id] = []
        self._episodic[agent_id].append(entry)
        file_path = self.storage_path / f"{agent_id}.jsonl"
        with open(file_path, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    async def get_relevant(self, agent_id: str, query: str, limit: int = 5) -> str:
        records = self._episodic.get(agent_id, [])
        if not records:
            return ""
        query_tokens = self._tokenize(query)
        if not query_tokens:
            recent = records[-limit:]
            return self._format_records(recent)

        scored = []
        for r in records:
            if "tokens" not in r:
                r["tokens"] = self._tokenize(f"{r['query']} {r['response']}")
            score = self._overlap_score(query_tokens, r["tokens"])
            if score > 0:
                scored.append((score, r))

        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]
        if not top:
            recent = records[-limit:]
            return self._format_records(recent)
        return self._format_records([r for _, r in top])

    async def consolidate_nightly(self):
        logger.info("Nightly memory consolidation started...")
        for agent_id, records in self._episodic.items():
            if not records:
                continue
            all_tokens: Counter = Counter()
            for r in records:
                tokens = r.get("tokens", self._tokenize(f"{r['query']} {r['response']}"))
                all_tokens.update(tokens)
            top_keywords = [w for w, _ in all_tokens.most_common(20) if len(w) > 2]
            topics = list(dict.fromkeys(top_keywords))[:10]
            self._semantic[agent_id] = {
                "summary": f"{len(records)} interactions. Topics: {', '.join(topics)}",
                "topics": topics,
                "total_interactions": len(records),
                "last_consolidated": datetime.now().isoformat(),
            }
        logger.info(f"Memory consolidation complete — {len(self._semantic)} agents")

    def load_history(self, agent_id: str) -> list[dict]:
        file_path = self.storage_path / f"{agent_id}.jsonl"
        if not file_path.exists():
            return []
        records = []
        with open(file_path) as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if "tokens" not in entry:
                        entry["tokens"] = self._tokenize(
                            f"{entry['query']} {entry['response']}"
                        )
                    records.append(entry)
        self._episodic[agent_id] = records
        return records

    def get_semantic_summary(self, agent_id: str) -> Optional[dict]:
        return self._semantic.get(agent_id)

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        _diac = str.maketrans({"ă": "a", "â": "a", "î": "i", "ș": "s", "ț": "t",
                               "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ț": "T"})
        text = text.lower().translate(_diac)
        tokens = re.findall(r"[a-z0-9]+", text)
        stopwords = {
            "si", "in", "pe", "cu", "la", "de", "a", "ai", "al", "ale", "alor",
            "un", "o", "unei", "unui", "il", "ii", "le", "l", "i", "si",
            "este", "sunt", "fost", "au", "ati", "am", "ai", "a",
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
        }
        return [t for t in tokens if t not in stopwords and len(t) > 1]

    @staticmethod
    def _overlap_score(query_tokens: list[str], doc_tokens: list[str]) -> float:
        if not query_tokens or not doc_tokens:
            return 0.0
        score = 0.0
        for qt in query_tokens:
            for dt in doc_tokens:
                if qt == dt or dt.startswith(qt) or qt.startswith(dt):
                    score += 1.0
                    break
        return score / len(query_tokens)

    @staticmethod
    def _format_records(records: list[dict]) -> str:
        lines = []
        for r in records:
            lines.append(f"Q: {r['query']}\nA: {r['response']}")
        return "\n\n".join(lines)
