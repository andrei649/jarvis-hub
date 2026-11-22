"""Whole-word ranking for the local Obsidian graph. Results retain their source paths."""
import re
import unicodedata
from collections import Counter, deque
from array import array

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


def query_terms(query, synonyms):
    """Return the same direct and expanded terms used by ranking and excerpts."""
    phrase = f" {_words(query)} "
    terms = {word for word in phrase.split() if word not in _STOP and (len(word) >= 3 or word in _SHORT)}
    related = {_words(extra) for key, extras in synonyms.items()
               if f" {_words(key)} " in phrase for extra in extras} - terms
    return terms, related


def score(node, terms, related, *, body=None):
    """Score one node; an explicit body is a fresh read in place of indexed text."""
    if not terms and not related:
        return 0, 0
    path = node.get("relPath", "")
    if node.get("isHub") or node.get("cloudEvicted") or not (path.lower().endswith(".md") or node.get("projectId")):
        return 0, 0
    fields = [(6, node.get("title", "")), (3, path if node.get("projectId") else path[:-3]), (2, node.get("category", "")),
              (1, node.get("body", "") if body is None else body), (3, " ".join(node.get("tags", [])))]
    literal = expanded = 0
    related_words = {term for term in related if " " not in term}
    related_phrases = related - related_words
    for weight, value in fields:
        if value:
            normalized = _words(value)
            words = set(normalized.split())
            literal += weight * len(terms & words)
            padded = f" {normalized} "
            expanded += weight * (len(related_words & words) + sum(f" {phrase} " in padded for phrase in related_phrases))
    return literal, expanded


def rank(query, nodes, synonyms):
    """Rank exact query words before expanded terms. Never return an unrelated default."""
    terms, related = query_terms(query, synonyms)
    if not terms and not related:
        return []

    scored = []
    for node in nodes:
        literal, expanded = score(node, terms, related)
        if literal or expanded:
            scored.append((literal, expanded, node.get("relPath", ""), node))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [node for _, _, _, node in scored]


def passage(body, query, synonyms, limit=1500):
    """Pick a verbatim, bounded paragraph or window that contains the best body evidence."""
    if limit <= 0:
        return ""
    if len(body) <= limit:
        return body
    terms, related = query_terms(query, synonyms)
    if not terms and not related:
        return body[:limit]

    paragraphs = []
    offset = paragraph_start = 0
    for line in body.splitlines(keepends=True):
        if not line.strip():
            if paragraph_start < offset:
                paragraphs.append((paragraph_start, offset))
            paragraph_start = offset + len(line)
        elif re.match(r"^ {0,3}#{1,6}(?:[ \t]|$)", line) and paragraph_start < offset:
            paragraphs.append((paragraph_start, offset))
            paragraph_start = offset
        offset += len(line)
    if paragraph_start < len(body):
        paragraphs.append((paragraph_start, len(body)))

    related_words = {term for term in related if " " not in term}
    related_phrases = related - related_words
    expansions = {}
    for phrase in related:
        parts = tuple(phrase.split())
        if parts:
            expansions.setdefault(parts[0], []).append((parts, phrase))
    best_key = None
    best_span = None
    for paragraph_index, (start, end) in enumerate(paragraphs):
        paragraph = body[start:end]
        substantive = not paragraph.lstrip().startswith("#") or len(paragraph.strip().splitlines()) > 1
        if end - start <= limit:
            normalized = _words(paragraph)
            words = set(normalized.split())
            direct = terms & words
            expanded = (related_words & words) | {phrase for phrase in related_phrases if f" {phrase} " in f" {normalized} "}
            if not direct and not expanded:
                continue
            key = (len(direct), len(expanded), substantive, -(end - start), -start)
            if best_key is None or key > best_key:
                best_key = key
                best_span = (start, end, paragraph_index, True)
        else:
            if paragraph.isascii():
                tokens = [(match.group(), start + match.start(), start + match.end())
                          for match in _WORDS.finditer(paragraph.casefold())]
            else:
                normalized = []
                offsets = array("I")
                for position, char in enumerate(paragraph):
                    for folded in unicodedata.normalize("NFKD", char.casefold()):
                        if not unicodedata.combining(folded):
                            normalized.append(folded)
                            offsets.append(position)
                tokens = [(match.group(), start + offsets[match.start()], start + offsets[match.end() - 1] + 1)
                          for match in _WORDS.finditer("".join(normalized))]
            hits = []
            for index, (word, hit_start, hit_end) in enumerate(tokens):
                if word in terms:
                    hits.append((hit_start, hit_end, word, True))
                for parts, phrase in expansions.get(word, ()):
                    if index + len(parts) <= len(tokens) and all(tokens[index + offset][0] == part for offset, part in enumerate(parts)):
                        hits.append((hit_start, tokens[index + len(parts) - 1][2], phrase, False))
            direct, expanded = Counter(), Counter()
            left = 0
            maximum_ends = deque()
            for right, hit in enumerate(hits):
                counts = direct if hit[3] else expanded
                counts[hit[2]] += 1
                while maximum_ends and hits[maximum_ends[-1]][1] <= hit[1]:
                    maximum_ends.pop()
                maximum_ends.append(right)
                while left <= right and hits[maximum_ends[0]][1] - hits[left][0] > limit:
                    old = hits[left]
                    counts = direct if old[3] else expanded
                    counts[old[2]] -= 1
                    if not counts[old[2]]:
                        del counts[old[2]]
                    if maximum_ends[0] == left:
                        maximum_ends.popleft()
                    left += 1
                if left <= right:
                    candidate_start = hits[left][0]
                    candidate_end = hits[maximum_ends[0]][1]
                    key = (len(direct), len(expanded), substantive, -(candidate_end - candidate_start), -candidate_start)
                    if best_key is None or key > best_key:
                        best_key = key
                        best_span = (candidate_start, candidate_end, paragraph_index, False)

    if best_span is None:
        return body[:limit]
    start, end, paragraph_index, complete = best_span
    if complete:
        previous = paragraphs[paragraph_index - 1] if paragraph_index else None
        following = paragraphs[paragraph_index + 1] if paragraph_index + 1 < len(paragraphs) else None
        if (previous and body[previous[0]:previous[1]].lstrip().startswith("#")
                and len(body[previous[0]:previous[1]].strip().splitlines()) == 1
                and end - previous[0] <= limit):
            start = previous[0]
        elif (body[start:end].lstrip().startswith("#") and len(body[start:end].strip().splitlines()) == 1
              and following and following[1] - start <= limit):
            end = following[1]
        return body[start:end]
    # Center a long-paragraph window on the selected cluster without dropping its matches.
    paragraph_start, paragraph_end = paragraphs[paragraph_index]
    start = min(max(paragraph_start, start - 80, end - limit), max(paragraph_start, paragraph_end - limit))
    return body[start:min(paragraph_end, start + limit)]
