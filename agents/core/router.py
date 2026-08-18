"""
router.py — Intent classifier. Decides which agent(s) should handle an input.

Design (v0.5 rewrite, replacing the v0.1 keyword stub):

  * **Deterministic & offline-first.** No LLM call on the hot path → zero added
    latency, works with the network down. An optional `llm_classifier` is used
    *only* as a fallback for inputs that match nothing (see `__init__`).
  * **Word/token boundary matching**, never naive substring `in`. The old code
    matched "car" inside "s**car**ed", "sign" inside "de**sign**", "search"
    inside "re**search**" → silent misroutes. Here a single-word trigger must
    equal a token or be a stem prefix of one (min length 4), and multi-word
    phrases match on word boundaries.
  * **Bilingual RO/EN.** Andrei talks to the cabinet in both languages, so
    "câți bani am?" must reach Gecko and "cum am dormit?" must reach Hercules.
    Triggers carry both surfaces and the input is diacritic-folded.
  * **Scored & ranked.** Each candidate agent accumulates trigger weights; the
    highest-scoring agent is primary, the rest follow in order. A confidence
    score and the per-agent breakdown are exposed on `Intent.context`.

The public contract is unchanged so this is a drop-in replacement:
`await router.classify(text, agents) -> Intent` with `.target_agents` (primary
first), `.is_general`, `.context["source"|"keywords_found"|...]`, and the
mutable instance-level `ROUTING_TABLE` that the orchestrator extends when a
bench agent is promoted.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("jarvis.router")

# Optional async hook: (text, ranked_candidates) -> list[agent_id]. Injected by
# the orchestrator when a cloud/local LLM is available; never required.
LLMClassifier = Callable[[str, list[str]], Awaitable[Optional[list[str]]]]

_WORD_RE = re.compile(r"[a-z0-9]+")
_STEM_MIN = 4          # shortest trigger eligible for prefix (inflection) matching
_GENERAL_TAG = "general"


class Intent:
    """The routing decision for one input.

    `target_agents` is ordered primary-first. `context` carries provenance and,
    for keyword matches, the canonical intent tags found and the score table —
    both additive and safe for existing consumers to ignore.
    """

    def __init__(self, target_agents: Optional[list[str]], is_general: bool,
                 context: dict, confidence: float = 0.0):
        self.target_agents = target_agents
        self.is_general = is_general
        self.context = context
        self.confidence = confidence

    @property
    def primary(self) -> str:
        return self.target_agents[0] if self.target_agents else "jarvis"

    def __repr__(self) -> str:
        return (f"Intent(target_agents={self.target_agents}, "
                f"is_general={self.is_general}, confidence={self.confidence:.2f}, "
                f"source={self.context.get('source')!r})")


# Trigger weights. Distinctive proper nouns and multi-word phrases are trusted
# more than common domain words; greetings/very generic words are de-emphasised
# so they never outvote a real domain signal.
W_STRONG = 2.0   # phrases + distinctive proper nouns (raiffeisen, cosmina, bmw…)
W_NORMAL = 1.0   # ordinary domain words
W_WEAK = 0.5     # greetings & ambiguous fillers (hello, help, search…)

# Canonical intent tag → (agents, surface forms [EN + RO, diacritic-folded], weight).
# The canonical tag is what lands in context["keywords_found"]; the orchestrator
# checks those tags ("weather", "news", "calendar", "email", "research") when it
# decides which plugins to pre-fetch, so they are language-independent here.
INTENT_RULES: dict[str, tuple[list[str], tuple[str, ...], float]] = {
    "weather":   (["friday"], ("weather", "forecast", "vreme", "vremea", "prognoza",
                                "temperatura", "ploaie", "ninge"), W_NORMAL),
    "news":      (["friday"], ("news", "headlines", "stiri", "noutati",
                               "actualitate", "presa"), W_NORMAL),
    "calendar":  (["pepper"], ("calendar", "meeting", "schedule", "agenda",
                               "sedinta", "intalnire", "eveniment"), W_NORMAL),
    "email":     (["pepper", "veronica", "stark"],
                  ("email", "inbox", "mail", "mesaje", "corespondenta"), W_NORMAL),
    "write":     (["veronica"], ("write", "draft", "caption", "linkedin",
                                 "instagram", "scrie", "redacteaza", "compune"), W_NORMAL),
    "research":  (["vision"], ("research", "search", "investigate", "osint",
                               "cercet", "cauta", "cautare",
                               "gaseste", "investigheaza"), W_NORMAL),
    "geoint":    (["argus"], ("satellite", "satelit", "recon", "overflight", "overpass",
                              "orbit", "vessel", "tanker", "aircraft", "adsb", "ais",
                              "hormuz", "strait", "geospatial", "geoint", "worldview",
                              "jamming", "bruiaj", "footprint", "aoi"), W_STRONG),
    "kpi":       (["stark"], ("kpi", "board", "raiffeisen", "analytics", "ga4",
                              "indicatori", "raport"), W_STRONG),
    "strategy":  (["athena"], ("strategy", "career", "digitaholic", "brand", "cmo",
                               "strategie", "cariera"), W_STRONG),
    "money":     (["gecko"], ("money", "finance", "budget", "balance", "salary",
                              "bani", "banii", "finante", "buget",
                              "economii", "salariu", "cheltuieli"), W_NORMAL),
    "health":    (["hercules"], ("sleep", "workout", "fitness", "recovery", "hrv",
                                 "somn", "dormit", "doarme", "antrenament",
                                 "recuperare", "snowboard"), W_NORMAL),
    "build":     (["hephaestus"], ("cosmina", "bmw", "garage", "engine", "n54",
                                   "masina", "masini", "santier", "constructie",
                                   "motor"), W_STRONG),
    "family":    (["frigga"], ("max", "alexandra", "family", "familie", "copii",
                               "sotie", "acasa"), W_NORMAL),
    "beads":     (["frigga", "veronica"], ("beads", "blush", "bijuterii"), W_STRONG),
    "music":     (["jerome"], ("music", "playlist", "song", "spotify", "muzica",
                               "melodie", "piesa", "game", "joc"), W_NORMAL),
    "infra":     (["steve"], ("infrastructure", "server", "backup", "docker",
                              "deploy", "infrastructura", "sistem"), W_NORMAL),
    "security":  (["ultron"], ("security", "firewall", "threat", "vlan", "gdpr",
                               "securitate", "amenintare", "porturi"), W_NORMAL),
    "automation":(["oracle"], ("automation", "workflow", "n8n", "pipeline",
                               "automatizare", "flux"), W_NORMAL),
    # House state, not house construction — "santier"/"constructie" stay with
    # hephaestus above, and "acasa" stays with frigga (who is home, not what the
    # building is doing). Ambiguous words are deliberately absent: RO "camera" is
    # both a room and a camera device, and "lumina" is too often figurative.
    "house":     (["hestia"], ("thermostat", "termostat", "hvac", "radiator",
                               "boiler", "centrala", "heating", "incalzire",
                               "lights", "lumini", "bec", "becuri", "priza",
                               "prize", "smart home", "homebridge",
                               "living room", "bedroom", "dormitor",
                               "sufragerie"), W_NORMAL),
    "howard":    (["howard"], ("howard", "archive", "remember", "arhiva",
                               "aminteste", "digital twin", "what would i",
                               "what did i", "what have i", "what do i",
                               "how would i", "what do you know about",
                               "ce as face", "ce am facut"), W_STRONG),
    "identity":  (["howard", "jarvis"], ("who is", "cine e", "cine este"), W_STRONG),
    _GENERAL_TAG:(["jarvis"], ("hello", "hi", "hey", "morning", "help", "route",
                               "who are you", "what can you", "salut", "buna",
                               "noroc", "ajutor", "ce poti"), W_WEAK),
}


class IntentRouter:
    """Routes input to the correct agent(s) by scored, bilingual keyword match.

    Falls back to an injected LLM classifier only when nothing matches and one
    was provided; otherwise unmatched input goes to Jarvis as general chat.
    """

    # Wake-word / direct-address table: agent id → routes-to. Kept as a class
    # default and copied per-instance so the orchestrator can register promoted
    # bench agents (`router.ROUTING_TABLE[bench_id] = [bench_id]`) without the
    # entry leaking across instances or tests.
    ROUTING_TABLE: dict[str, list[str]] = {
        "jarvis": ["jarvis"], "friday": ["friday"], "pepper": ["pepper"],
        "jerome": ["jerome"], "athena": ["athena"], "stark": ["stark"],
        "veronica": ["veronica"], "vision": ["vision"], "steve": ["steve"],
        "oracle": ["oracle"], "ultron": ["ultron"], "gecko": ["gecko"],
        "hercules": ["hercules"], "hephaestus": ["hephaestus"],
        "frigga": ["frigga"], "howard": ["howard"], "argus": ["argus"],
        "hestia": ["hestia"],
    }

    # Back-compat: flat keyword → agents view (some tooling/tests may read it).
    INTENT_KEYWORDS: dict[str, list[str]] = {
        surface: list(agents)
        for agents, surfaces, _ in INTENT_RULES.values()
        for surface in surfaces
    }

    # Optional leading particles before a wake word: "hey jarvis", "ok jarvis".
    _WAKE_PARTICLES = {"hey", "ok", "okay", "hei", "salut", "yo"}

    # Confidence below this → consult the LLM fallback (if one is injected).
    LLM_FALLBACK_THRESHOLD = 0.5

    def __init__(self, config, llm_classifier: Optional[LLMClassifier] = None):
        self.config = config
        self.llm_classifier = llm_classifier
        self.ROUTING_TABLE = dict(self.__class__.ROUTING_TABLE)
        self._agent_order = {a: i for i, a in enumerate(self.ROUTING_TABLE)}
        # Pre-split rules into fast single-token triggers and phrase regexes.
        self._token_rules: list[tuple[str, str, list[str], float]] = []   # (tag, token, agents, w)
        self._phrase_rules: list[tuple[str, re.Pattern, list[str], float]] = []
        for tag, (agents, surfaces, weight) in INTENT_RULES.items():
            for surface in surfaces:
                if " " in surface:
                    pat = re.compile(rf"\b{re.escape(surface)}\b")
                    self._phrase_rules.append((tag, pat, agents, weight))
                else:
                    self._token_rules.append((tag, surface, agents, weight))

    # ── public API ────────────────────────────────────────────────
    async def classify(self, text: str, agents: dict) -> Intent:
        """Classify input → target agent(s) + provenance context.

        Stages: (1) explicit wake word, (2) scored bilingual keyword match,
        (3) optional LLM fallback, (4) general chat → Jarvis.
        """
        raw = (text or "").strip()
        if not raw:
            return self._general()

        normalized = _normalize(raw)
        tokens = _WORD_RE.findall(normalized)

        # Stage 1 — explicit direct address ("Jarvis, …", "hey Friday …").
        wake = self._check_wake_word(tokens)
        if wake:
            return Intent([wake], is_general=False,
                          context={"source": "wake_word", "agent": wake},
                          confidence=1.0)

        # Stage 2 — scored keyword match.
        scores, tags = self._score(normalized, set(tokens))
        if scores:
            ranked = self._rank(scores)
            top = scores[ranked[0]]
            confidence = min(1.0, top / W_STRONG)
            if confidence < self.LLM_FALLBACK_THRESHOLD and self.llm_classifier:
                llm = await self._llm_fallback(raw, ranked)
                if llm:
                    return llm
            return Intent(
                ranked, is_general=False,
                context={
                    "source": "keyword_match",
                    "keywords_found": sorted(tags),
                    "scores": {a: round(s, 2) for a, s in scores.items()},
                },
                confidence=confidence,
            )

        # Stage 3 — nothing matched: let the LLM try, if available.
        if self.llm_classifier:
            llm = await self._llm_fallback(raw, [])
            if llm:
                return llm

        # Stage 4 — general chat.
        return self._general()

    async def classify_deterministic(self, text: str, agents: dict) -> Intent:
        """Classify without consulting the optional LLM fallback capability."""
        raw = (text or "").strip()
        if not raw:
            return self._general()

        normalized = _normalize(raw)
        tokens = _WORD_RE.findall(normalized)
        wake = self._check_wake_word(tokens)
        if wake:
            return Intent(
                [wake],
                is_general=False,
                context={"source": "wake_word", "agent": wake},
                confidence=1.0,
            )

        scores, tags = self._score(normalized, set(tokens))
        if scores:
            ranked = self._rank(scores)
            top = scores[ranked[0]]
            return Intent(
                ranked,
                is_general=False,
                context={
                    "source": "keyword_match",
                    "keywords_found": sorted(tags),
                    "scores": {agent: round(score, 2) for agent, score in scores.items()},
                },
                confidence=min(1.0, top / W_STRONG),
            )
        return self._general()

    # ── stages ────────────────────────────────────────────────────
    def _check_wake_word(self, tokens: list[str]) -> Optional[str]:
        """Return an agent id if the input directly addresses one.

        Matches a leading agent token, optionally preceded by a particle
        ("hey", "ok", "salut"). Uses exact token equality, so "visionary" no
        longer triggers Vision and "steven" no longer triggers Steve.
        """
        if not tokens:
            return None
        first = tokens[0]
        if first in self._WAKE_PARTICLES and len(tokens) > 1:
            first = tokens[1]
        return first if first in self.ROUTING_TABLE else None

    def _score(self, normalized: str, token_set: set[str]) -> tuple[dict[str, float], set[str]]:
        """Accumulate per-agent scores and the set of canonical tags matched."""
        scores: dict[str, float] = {}
        tags: set[str] = set()

        for tag, token, agents, weight in self._token_rules:
            if _token_matches(token, token_set):
                tags.add(tag)
                for agent in agents:
                    scores[agent] = scores.get(agent, 0.0) + weight

        for tag, pattern, agents, weight in self._phrase_rules:
            if pattern.search(normalized):
                tags.add(tag)
                for agent in agents:
                    scores[agent] = scores.get(agent, 0.0) + weight

        return scores, tags

    def _rank(self, scores: dict[str, float]) -> list[str]:
        """Agents ordered by score desc, ties broken by canonical agent order."""
        return sorted(scores, key=lambda a: (-scores[a], self._agent_order.get(a, 99)))

    async def _llm_fallback(self, text: str, ranked: list[str]) -> Optional[Intent]:
        try:
            chosen = await self.llm_classifier(text, ranked)
        except Exception as e:  # never let the fallback break routing
            logger.warning(f"LLM router fallback failed: {e}")
            return None
        chosen = [a for a in (chosen or []) if a in self.ROUTING_TABLE]
        if not chosen:
            return None
        logger.info(f"LLM router fallback chose {chosen} for: {text[:60]!r}")
        return Intent(chosen, is_general=False,
                      context={"source": "llm", "candidates": ranked},
                      confidence=0.6)

    def _general(self) -> Intent:
        return Intent(["jarvis"], is_general=True,
                      context={"source": "general"}, confidence=0.0)


# ── helpers ─────────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    """Lowercase, strip diacritics (ă→a, ș→s, ț→t…), collapse whitespace."""
    folded = unicodedata.normalize("NFKD", text.lower())
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", folded).strip()


def _token_matches(trigger: str, token_set: set[str]) -> bool:
    """True if a single-word trigger matches a token.

    Exact match always counts. For triggers of at least `_STEM_MIN` chars we
    also accept a token that *starts with* the trigger, so "bani" matches
    "banii" and "dormit" matches "dormit"/"dormitul" — without the substring
    traps that plagued the old `keyword in text` check ("car" ⊄ "scared").
    """
    if trigger in token_set:
        return True
    if len(trigger) >= _STEM_MIN:
        return any(tok.startswith(trigger) for tok in token_set)
    return False
