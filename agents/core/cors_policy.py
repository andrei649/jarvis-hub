"""cors_policy.py — AUD-18 / F30: validate CORS origins instead of trusting them.

`JARVIS_CORS_ORIGINS` used to be parsed and handed straight to `CORSMiddleware`.
Nothing checked the values, and both ways that goes wrong are **silent**:

* A browser matches the `Origin` header against these strings *exactly* — scheme
  included, no trailing slash, no path. So ``example.com`` or
  ``https://a.example/`` look configured and simply never match. A security
  control that is inert while reading as enabled is worse than one that is
  obviously off.
* ``*`` with ``allow_credentials=True`` is rejected by every browser, so it also
  does nothing — while looking maximally permissive in the config file, which is
  precisely the misreading to avoid.

So this returns the usable origins **and** the rejected ones with reasons, and
the caller logs what it dropped. Pure and offline; no network, no app import.
"""

from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["normalize_cors_origins"]


def normalize_cors_origins(
    values, *, allow_credentials: bool = True,
) -> tuple[list[str], list[dict]]:
    """Split configured origins into ``(usable, rejected)``.

    ``rejected`` entries are ``{"value", "reason"}`` so a caller can say exactly
    what it ignored rather than dropping it silently.
    """
    usable: list[str] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for raw in list(values or []):
        if not isinstance(raw, str):
            rejected.append({"value": repr(raw), "reason": "not a string"})
            continue
        value = raw.strip()
        if not value:
            continue

        if value == "*":
            if allow_credentials:
                rejected.append({
                    "value": value,
                    "reason": "'*' cannot be combined with credentialed CORS — "
                              "browsers reject it, so it would allow nothing",
                })
            elif value not in seen:
                seen.add(value)
                usable.append(value)
            continue

        parts = urlsplit(value)
        if not parts.scheme or not parts.netloc:
            rejected.append({
                "value": value,
                "reason": "origin needs a scheme and host (e.g. https://a.example)",
            })
            continue
        if parts.path:
            rejected.append({
                "value": value,
                "reason": "origin must have no path or trailing slash — a browser "
                          "compares the Origin header exactly and would never match",
            })
            continue
        if parts.query or parts.fragment:
            rejected.append({"value": value, "reason": "origin must have no query or fragment"})
            continue

        if value not in seen:
            seen.add(value)
            usable.append(value)

    return usable, rejected
