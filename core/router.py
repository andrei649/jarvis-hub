import re
from typing import Optional

_DIACRITICS = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ț": "t",
    "Ă": "A", "Â": "A", "Î": "I", "Ș": "S", "Ț": "T",
})


def normalize(text: str) -> str:
    return text.translate(_DIACRITICS)


class IntentRouter:
    def __init__(self):
        self._routes: dict[str, list[dict]] = {}
        self._anti_patterns: dict[str, list[re.Pattern]] = {}

    def register(
        self,
        agent_id: str,
        patterns: list[str],
        priority: int = 0,
        anti_patterns: Optional[list[str]] = None,
    ):
        if agent_id not in self._routes:
            self._routes[agent_id] = []
        for p in patterns:
            clean = normalize(p)
            self._routes[agent_id].append({
                "pattern": re.compile(clean, re.IGNORECASE),
                "priority": priority,
            })
        if anti_patterns:
            if agent_id not in self._anti_patterns:
                self._anti_patterns[agent_id] = []
            for ap in anti_patterns:
                self._anti_patterns[agent_id].append(re.compile(normalize(ap), re.IGNORECASE))

    def route(self, message: str) -> list[tuple[str, float]]:
        scores = {}
        msg_normalized = normalize(message)
        for agent_id, patterns in self._routes.items():
            if not patterns:
                continue
            match_count = 0
            for entry in patterns:
                if entry["pattern"].search(msg_normalized):
                    match_count += 1 + entry["priority"]
            if match_count > 0:
                anti_score = self._compute_anti_score(agent_id, message)
                raw = match_count - anti_score
                score = raw / len(patterns)
                if score > 0:
                    scores[agent_id] = score
        return sorted(scores.items(), key=lambda x: -x[1])

    def _compute_anti_score(self, agent_id: str, message: str) -> float:
        anti = self._anti_patterns.get(agent_id)
        if not anti:
            return 0.0
        normalized = normalize(message)
        count = sum(1 for ap in anti if ap.search(normalized))
        return count * 1.5

    def best_match(self, message: str) -> Optional[str]:
        results = self.route(message)
        return results[0][0] if results else None

    def setup_defaults(self):
        self.register(
            "frigga",
            [r"\b(?:max|bebe|copil|pediatru|alaptat|scutec|familie)"],
            priority=2,
            anti_patterns=[r"\b(?:finance|buget|investitie)"],
        )
        self.register(
            "hephaestus",
            [r"\b(?:cosmina|casa|n54|bmw|e93|constructie|permis|materiale|reparatie|masina)"],
            priority=1,
        )
        self.register(
            "gecko",
            [r"\b(?:buget|factura|venit|cheltuiala|salariu|investitie|runway|bani|finante)"],
            priority=1,
        )
        self.register(
            "athena",
            [r"\b(?:digitaholic|brand|pozitionare|consultan|consilient|client|pitch|freelance|carier)"],
            priority=1,
        )
        self.register(
            "stark",
            [r"\b(?:raiffeisen|kpi|ga4|firebase|board|prezentare|corporate|banca|slack)"],
            priority=1,
        )
        self.register(
            "hercules",
            [r"\b(?:somn|antrenament|sport|fitness|nutritie|sanatate|medic|sala|greutate|stres)"],
            priority=1,
        )
        self.register(
            "jerome",
            [r"\b(?:muzica|dj|playlist|snowboard|vacanta|film|joc|relaxare|hobby|travel|enjoy)"],
            priority=1,
        )
        self.register(
            "veronica",
            [r"\b(?:linkedin|postare|caption|newsletter|continut|scrie|text|articol)"],
            priority=1,
        )
        self.register(
            "vision",
            [r"\b(?:cercetare|research|stire|noutate|industrie|competitor|analiza)"],
            priority=1,
        )
        self.register(
            "ultron",
            [r"\b(?:securitate|vpn|parola|backup|monitorizare|alerta|firewall|pericol)"],
            priority=2,
            anti_patterns=[r"\b(?:server|bonobo|deploy|build|repo)"],
        )
        self.register(
            "steve",
            [r"\b(?:server|bonobo|pi|deploy|build|repo|github|infrastructura|hosting)"],
            priority=1,
        )
        self.register(
            "oracle",
            [r"\b(?:workflow|n8n|automatizare|cron|trigger|script)"],
            priority=1,
        )
        self.register(
            "friday",
            [r"\b(?:raport|dimineata|brief|vreme|astazi|azi|calendarul)"],
            priority=2,
            anti_patterns=[r"\b(?:somn|antrenament|fitness|nutritie)"],
        )
        self.register(
            "pepper",
            [r"\b(?:programar|meeting|email|calendar|task|reminder|agenda|sedinta|schedule)"],
            priority=1,
        )
