"""Shared input validators (AUD-5, AUD-12).

Small, dependency-free guards for values that cross a trust boundary into a
filesystem path, a Cypher query, or other sink. Kept in one place so every call
site validates identically.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# A session id becomes a filename via ``MEMORY_DIR / f"{session_id}.json"`` in
# memory/persistence.py. Restrict it to an inert identifier alphabet so it can
# never carry a path separator, ``..`` traversal, NUL, or whitespace out of the
# memory dir (AUD-5). 128 chars is well above any id the system generates.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_SESSION_ID_LEN = 128


def is_valid_session_id(session_id: object) -> bool:
    """Return ``True`` iff *session_id* is a safe, filesystem-inert identifier.

    Accepts only ``[A-Za-z0-9_-]`` (1..128 chars). Rejects the empty string,
    path separators, ``..``, NUL and whitespace — so a hostile id can never
    escape the memory directory.
    """
    return (
        isinstance(session_id, str)
        and 0 < len(session_id) <= _MAX_SESSION_ID_LEN
        and _SESSION_ID_RE.match(session_id) is not None
    )


# ── AUD-12 (F11): Cypher label / relationship-type / property-key safety ──────
# Neo4j cannot parameterise node *labels* or relationship *types* — they are
# interpolated into the query string (memory/graph.py), as are property *keys*
# inside a map literal. The injection-safety boundary is therefore "is this a
# bare Cypher identifier?": a value matching ``[A-Za-z][A-Za-z0-9_]*`` cannot
# carry whitespace, braces, quotes or parentheses and so cannot break out of the
# query. Values that ARE safe identifiers pass through unchanged — so a
# free-form-but-safe predicate (e.g. ``DAUGHTER`` from "Andrei's daughter is …")
# or a label like ``Geo_aoi`` keeps its meaning and no extracted fact is lost.
# Only values that are NOT safe identifiers are coerced to a safe fallback on the
# graph write path, and hard-rejected (400) on the direct write API.
#
# KG_LABELS / KG_REL_TYPES document the canonical vocabulary the system emits
# (seeds, conversation extraction, WorldView sync). They are the *expected* set
# for reference and tests — NOT the enforcement boundary (any other safe
# identifier is still accepted), so novel-but-legitimate types are never lost.
KG_LABELS: frozenset[str] = frozenset({
    "Person", "Organization", "City", "Village", "Project",
    "Location", "Geo_aoi", "Geo_event", "Entity", "Unknown",
})
KG_REL_TYPES: frozenset[str] = frozenset({
    "WORKS_AT", "RUNS", "MARRIED_TO", "PARENT_OF", "LIVES_IN",
    "BUILDING_HOUSE_AT", "OWNS", "LOCATED_IN", "IN_AOI", "KNOWS",
    "RELATED_TO", "IS_A",
})

KG_LABEL_FALLBACK = "Entity"
KG_REL_FALLBACK = "RELATED_TO"

# A Cypher identifier: starts with a letter, then letters/digits/underscores.
_KG_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
# A property key may also start with an underscore (e.g. ``_source``).
_KG_PROP_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_KG_TOKEN_MAXLEN = 64


def _is_safe_kg_token(token: str) -> bool:
    return 0 < len(token) <= _KG_TOKEN_MAXLEN and _KG_TOKEN_RE.match(token) is not None


def is_safe_kg_label(value: object) -> bool:
    """Return ``True`` iff *value* normalizes to a safe Cypher label token."""
    return isinstance(value, str) and _is_safe_kg_token(value.strip().capitalize())


def is_safe_kg_rel_type(value: object) -> bool:
    """Return ``True`` iff *value* normalizes to a safe Cypher relationship type."""
    return isinstance(value, str) and _is_safe_kg_token(value.strip().upper().replace(" ", "_"))


def coerce_kg_label(value: object) -> str:
    """Normalize *value* to a Cypher-safe node label.

    Mirrors the historical ``entity_type.capitalize()`` for safe inputs, so a
    legitimate type round-trips unchanged. A value that is not a safe identifier
    (contains whitespace, braces, quotes, …) is coerced to ``Entity`` and logged
    — it can therefore never break out of the interpolated query.
    """
    token = str(value or "").strip().capitalize()
    if _is_safe_kg_token(token):
        return token
    logger.warning("KG label %r is not a safe Cypher identifier → coerced to %s",
                   value, KG_LABEL_FALLBACK)
    return KG_LABEL_FALLBACK


def coerce_kg_rel_type(value: object) -> str:
    """Normalize *value* to a Cypher-safe relationship type.

    Mirrors the historical ``relation.upper()`` for safe inputs. A non-identifier
    value is coerced to ``RELATED_TO`` and logged.
    """
    token = str(value or "").strip().upper().replace(" ", "_")
    if _is_safe_kg_token(token):
        return token
    logger.warning("KG relationship type %r is not a safe Cypher identifier → coerced to %s",
                   value, KG_REL_FALLBACK)
    return KG_REL_FALLBACK


def is_safe_property_key(key: object) -> bool:
    """Return ``True`` iff *key* is a bare identifier safe to interpolate as a
    Cypher map key. Used to drop hostile property keys at the graph boundary."""
    return (
        isinstance(key, str)
        and 0 < len(key) <= _KG_TOKEN_MAXLEN
        and _KG_PROP_KEY_RE.match(key) is not None
    )
