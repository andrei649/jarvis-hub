"""
guardrail_node.py — H10.4 Guardrails Node in the Visual Builder.

Exposes the security scanners (secret / PII) as a workflow step (`kind ==
"guardrail"`) configurable **per workflow** — not just the global guardrails
engine. On findings the node WARNs (pass through), REDACTs (mask), or BLOCKs
(returns an `[error:...]` so the engine halts/marks the step), per config:

    {"mode": "warn|redact|block", "scanners": ["secret", "pii"]}
"""

from __future__ import annotations

from ..security.scanner import PIIScanner, SecretScanner

_SCANNERS = {"secret": SecretScanner, "pii": PIIScanner}


def apply_guardrail(config: dict, text: str) -> tuple[str, dict]:
    """Scan *text* and apply the configured policy. Returns (out_text, info)."""
    cfg = config or {}
    mode = (cfg.get("mode") or "redact").lower()
    names = cfg.get("scanners") or ["secret", "pii"]
    scanners = [_SCANNERS[n]() for n in names if n in _SCANNERS]

    findings: list[str] = []
    for sc in scanners:
        res = sc.scan(text or "")
        if not res.clean:
            findings.extend(f.pattern_name for f in res.findings)
    findings = sorted(set(findings))

    if not findings:
        return text, {"clean": True, "action": "pass", "findings": [], "mode": mode}

    if mode == "warn":
        return text, {"clean": False, "action": "warn", "findings": findings, "mode": mode}
    if mode == "block":
        return (f"[error:guardrail blocked: {', '.join(findings)}]",
                {"clean": False, "action": "block", "findings": findings, "mode": mode})
    # default: redact
    out = text or ""
    for sc in scanners:
        out = sc.redact(out)
    return out, {"clean": False, "action": "redact", "findings": findings, "mode": mode}
