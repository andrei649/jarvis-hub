"""Whole-word ranking for the local Obsidian graph. Results retain their source paths."""
import re
import unicodedata

_WORDS = re.compile(r"\b(?:prj-[0-9]{3}|ws-[a-z0-9]+(?:-[a-z0-9]+)*)\b|[^\W_]+")
_STOP = {
    "the", "and", "for", "what", "who", "how", "are", "you", "can", "tell", "about", "show",
    "jarvis", "please", "with", "from", "have", "my", "me", "in", "on", "to", "did", "does",
    "would", "could", "that", "this", "which", "into", "este", "sunt", "care", "despre", "meu",
    "mele", "din", "sau", "cum", "ce", "am", "si", "pe", "la", "noi", "poate", "poti", "pentru",
    "ale", "mai", "imi", "un", "una", "unei", "prin", "intr", "dupa",
}
_SHORT = {"ai", "pc", "3d", "2d", "ui", "ux", "vr", "ar", "os"}


def _words(text):
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return " ".join(_WORDS.findall("".join(c for c in decomposed if not unicodedata.combining(c))))


def rank(query, nodes, synonyms):
    """Rank exact query words before expanded terms. Never return an unrelated default."""
    phrase = f" {_words(query)} "
    terms = {word for word in phrase.split() if word not in _STOP and (len(word) >= 3 or word in _SHORT)}
    related = {_words(extra) for key, extras in synonyms.items()
               if f" {_words(key)} " in phrase for extra in extras} - terms
    if not terms and not related:
        return []

    scored = []
    for node in nodes:
        path = node.get("relPath", "")
        if node.get("isHub") or node.get("cloudEvicted") or not (path.lower().endswith(".md") or node.get("projectId")):
            continue
        fields = [(6, node.get("title", "")), (3, path if node.get("projectId") else path[:-3]), (2, node.get("category", "")),
                  (1, node.get("body", "")), (3, " ".join(node.get("tags", [])))]
        literal = expanded = 0
        for weight, value in fields:
            if value:
                normalized = f" {_words(value)} "
                literal += weight * sum(f" {word} " in normalized for word in terms)
                expanded += weight * sum(f" {word} " in normalized for word in related)
        if literal or expanded:
            scored.append((literal, expanded, path, node))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [node for _, _, _, node in scored]
