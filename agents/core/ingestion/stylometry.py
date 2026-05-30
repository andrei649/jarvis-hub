"""
stylometry.py — Voice profile extraction for Howard.

Analyzes normalized messages to build a stylometric fingerprint
of how Andrei writes and speaks: word choice, sentence rhythm,
code-switching, emoji usage, formality curve.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .normalizer import NormalizedMessage

logger = logging.getLogger("jarvis.ingestion.stylometry")

ROMANIAN_STOPWORDS = {
    "și", "în", "pe", "la", "cu", "din", "pentru", "prin", "după", "peste",
    "ca", "că", "mai", "foarte", "tot", "dar", "însă", "sau", "ori", "decât",
    "un", "o", "al", "ai", "ale", "ale", "lui", "îi", "îl", "o", "le", "se",
    "să", "nu", "da", "ba", "de", "a", "într", "dintr", "printr", "ntr",
    "este", "sunt", "fost", "fi", "fie", "era", "fiind",
}

ENGLISH_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their",
    "and", "or", "but", "if", "because", "as", "until", "while",
    "of", "at", "by", "for", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below",
    "to", "from", "in", "on", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "just", "also", "now",
}

RO_PREFIXES = {"ne", "pre", "re", "des", "dez", "in", "im", "răs", "stră"}
EN_PREFIXES = {"un", "re", "in", "dis", "en", "em", "pre", "pro", "anti"}


def _detect_language(word: str) -> str:
    """Simple RO/EN detection by character trigrams and common patterns."""
    word_lower = word.lower().strip(".,!?;:'\"()[]{}")
    if not word_lower:
        return "other"

    ro_chars = {"ă", "â", "î", "ș", "ț"}
    if any(c in word_lower for c in ro_chars):
        return "ro"

    en_endings = {"tion", "sion", "ment", "ness", "less", "ful", "ing", "ed", "ly", "er", "est"}
    ro_endings = {"ul", "ului", "urilor", "ilor", "elor", "al", "ale", "ilor", "ică", "esc", "ește"}

    for suff in en_endings:
        if word_lower.endswith(suff):
            return "en"
    for suff in ro_endings:
        if word_lower.endswith(suff):
            return "ro"

    if word_lower in ENGLISH_STOPWORDS:
        return "en"
    if word_lower in ROMANIAN_STOPWORDS:
        return "ro"

    return "unknown"


@dataclass
class VoiceProfile:
    name: str = "Andrei Tarcomnicu"
    total_messages: int = 0
    total_words: int = 0

    # Word-level stats
    top_words: list[tuple[str, int]] = field(default_factory=list)
    top_bigrams: list[tuple[str, int]] = field(default_factory=list)
    signature_phrases: list[str] = field(default_factory=list)

    # Language switching
    ro_ratio: float = 0.0
    en_ratio: float = 0.0
    code_switch_rate: float = 0.0

    # Emoji stats
    emoji_usage: dict[str, int] = field(default_factory=dict)
    messages_with_emoji: int = 0

    # Message metrics
    avg_message_length: float = 0.0
    median_message_length: float = 0.0
    message_length_std: float = 0.0

    # Sentence-level
    avg_sentence_length: float = 0.0
    sentences_per_message: float = 0.0

    # Conversation dynamics
    formality_score: float = 0.5
    messages_per_conversation: dict[str, int] = field(default_factory=dict)

    # Raw data paths
    data_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    @classmethod
    def from_dict(cls, data: dict) -> "VoiceProfile":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class StylometryAnalyzer:
    EMOJI_PATTERN = re.compile(
        r"[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F"
        r"\U0001F680-\U0001F6FF\U0001F900-\U0001F9FF"
        r"\U00002500-\U00002BEF\U00002702-\U000027B0"
        r"\U0001FA00-\U0001FA6F\U000024C2-\U0001F251]+"
    )

    def __init__(self, profile_path: Optional[Path] = None):
        self.profile_path = profile_path
        self.profile = VoiceProfile()

    def analyze(self, messages: list[NormalizedMessage]) -> VoiceProfile:
        my_messages = [m for m in messages if m.is_me]
        if not my_messages:
            logger.warning("No 'me' messages found for stylometry")
            return self.profile

        self.profile.total_messages = len(my_messages)

        word_counter: Counter = Counter()
        bigram_counter: Counter = Counter()
        emoji_counter: Counter = Counter()
        lengths: list[int] = []
        sentence_lengths: list[int] = []
        ro_words = 0
        en_words = 0
        total_content_words = 0
        switches = 0
        msgs_with_emoji = 0

        for msg in my_messages:
            length = len(msg.text)
            lengths.append(length)

            sentences = re.split(r"[.!?]+", msg.text)
            sentences = [s.strip() for s in sentences if s.strip()]
            self.profile.sentences_per_message += len(sentences) / len(my_messages)

            words = re.findall(r"\b\w+\b", msg.text.lower())
            word_counter.update(words)
            total_content_words += len(words)

            for i in range(len(words) - 1):
                bigram_counter.update([f"{words[i]} {words[i+1]}"])

            for w in words:
                lang = _detect_language(w)
                if lang == "ro":
                    ro_words += 1
                elif lang == "en":
                    en_words += 1

            emojis = self.EMOJI_PATTERN.findall(msg.text)
            for e in emojis:
                emoji_counter[e] += 1
            if emojis:
                msgs_with_emoji += 1

            prev_lang = None
            for w in words:
                lang = _detect_language(w)
                if lang in ("ro", "en") and prev_lang and prev_lang != lang:
                    switches += 1
                if lang in ("ro", "en"):
                    prev_lang = lang

            sentence_lengths.extend(len(s.split()) for s in sentences)

        self.profile.total_words = sum(word_counter.values())
        self.profile.top_words = word_counter.most_common(100)
        self.profile.top_bigrams = bigram_counter.most_common(50)

        total_ro_en = ro_words + en_words
        self.profile.ro_ratio = ro_words / total_ro_en if total_ro_en else 0.5
        self.profile.en_ratio = en_words / total_ro_en if total_ro_en else 0.5
        self.profile.code_switch_rate = switches / total_content_words if total_content_words else 0

        self.profile.emoji_usage = dict(emoji_counter.most_common(30))
        self.profile.messages_with_emoji = msgs_with_emoji

        if lengths:
            sorted_lengths = sorted(lengths)
            n = len(sorted_lengths)
            self.profile.avg_message_length = sum(lengths) / n
            self.profile.median_message_length = (
                sorted_lengths[n // 2] if n % 2 == 1
                else (sorted_lengths[n // 2 - 1] + sorted_lengths[n // 2]) / 2
            )
            if n > 1:
                variance = sum((x - self.profile.avg_message_length) ** 2 for x in lengths) / (n - 1)
                self.profile.message_length_std = variance ** 0.5

        if sentence_lengths:
            self.profile.avg_sentence_length = sum(sentence_lengths) / len(sentence_lengths)

        self._extract_signature_phrases(word_counter, bigram_counter)
        self._compute_formality(word_counter, my_messages)

        logger.info(
            f"Stylometry complete: {self.profile.total_messages} msgs, "
            f"{self.profile.total_words} words, "
            f"RO/EN ratio {self.profile.ro_ratio:.0%}/{self.profile.en_ratio:.0%}"
        )
        return self.profile

    def _extract_signature_phrases(self, word_counter: Counter, bigram_counter: Counter):
        signature = []
        stopwords_lower = ROMANIAN_STOPWORDS | ENGLISH_STOPWORDS
        content_words = [(w, c) for w, c in word_counter.most_common(200) if w not in stopwords_lower and len(w) > 2][:30]
        signature.extend(w for w, _ in content_words[:15])
        top_phrases = [(b, c) for b, c in bigram_counter.most_common(50) if all(len(w) > 2 for w in b.split())][:15]
        signature.extend(b for b, _ in top_phrases)
        self.profile.signature_phrases = signature

    def _compute_formality(self, word_counter: Counter, messages: list[NormalizedMessage]):
        formal_indicators = {"mulțumesc", "vă rog", "domnule", "doamnă", "stimați",
                             "thank you", "please", "regards", "sincer", "respect"}
        informal_indicators = {"mă", "boss", "bă", "ba", "hai", "haiu", "păi", "wow",
                               "cool", "awesome", "bro", "dude", "măi"}

        formal_count = sum(word_counter.get(w, 0) for w in formal_indicators)
        informal_count = sum(word_counter.get(w, 0) for w in informal_indicators)
        total = formal_count + informal_count
        self.profile.formality_score = formal_count / total if total else 0.5

    def save(self, path: Optional[Path] = None):
        save_path = path or self.profile_path
        if not save_path:
            return
        save_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        save_path.write_text(json.dumps(self.profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"VoiceProfile saved to {save_path}")

    def load(self, path: Optional[Path] = None) -> bool:
        load_path = path or self.profile_path
        if not load_path or not load_path.exists():
            return False
        import json
        try:
            data = json.loads(load_path.read_text(encoding="utf-8"))
            self.profile = VoiceProfile.from_dict(data)
            logger.info(f"VoiceProfile loaded from {load_path}")
            return True
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Failed to load VoiceProfile: {e}")
            return False
