#!/usr/bin/env python3
"""Reproduce the 2026-07-25 adversarial audit's *static* claims on this checkout.

The audit's own warning is the reason this exists:

    "Single-source audit output is a lead, not a fact."

One auditor stubbed ``PermissionGate.check_call`` to return ``True`` and reported the
resulting fan-out as production behaviour. Another counted only ``ast.Assign`` and
concluded 21 orchestrator attributes were undeclared; 15 were ``AnnAssign``. So every
claim in ``docs/test-manual/15-audit-gap-verification.md`` has to be re-measured on the
machine under test, and re-typing a 40-line reproduction from a report is exactly how a
measurement error gets copied forward.

Each probe answers one question and prints a verdict:

    OPEN    the mechanism the audit described still reproduces here
    CLOSED  it does not reproduce — either fixed, or the audit was wrong about this build
    N/A     this build cannot answer (dependency absent, backend not selected)

**A probe reports; it never asserts.** Fixing a finding flips OPEN to CLOSED and nothing
here breaks — that is the point. ``tests/test_qa_audit_probes.py`` pins the machinery
(the probes run, they return the documented keys, the chain probe stays in a temp dir),
not the verdicts.

**Safety.** Every probe is read-only against the live install. The chain probe forges
rows in a throwaway ``tempfile`` DB and never opens ``<data_root>/security/audit.db``.
The purge probe *lists* stores and never deletes. Nothing prints a secret value: the
signing probe reports whether signing is configured, never any part of the secret, and the
chain probe generates its own throwaway key rather than carrying a literal one.

Usage:
    python scripts/qa_audit_probes.py                 # all probes, table
    python scripts/qa_audit_probes.py chain purge     # named probes
    python scripts/qa_audit_probes.py --json          # machine-readable
    python scripts/qa_audit_probes.py --list
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OPEN, CLOSED, NA = "OPEN", "CLOSED", "N/A"


# ── ADV-001 · the audit chain is forgeable in hardened mode ───────────────────
def probe_chain() -> dict:
    """Rewrite EVERY row with plain sha256 while a key is configured.

    ``verify_chain`` recomputes each row with *the row's own* ``hash_algo`` column
    (``agents/core/security/audit.py``), and ``_digest`` demands the key only when the
    column says ``hmac-sha256``. Downgrade the whole table and the chain re-links.

    The shipped regression downgrades row 2 only, so the break surfaces at row 3 whose
    ``prev_hash`` is still an HMAC — which is why 19/19 stayed green.
    """
    from agents.core.security.audit import AuditLogger
    from agents.core.security.types import SecurityEvent, SecurityEventType

    # The probe needs *a* key so rows are written as hmac-sha256. Generated fresh per run
    # rather than written as a literal: a checked-in constant in the key slot is a
    # hardcoded credential whatever the comment beside it says, and this file would be a
    # poor place to argue the exception. It is thrown away below, and the forgery works
    # without ever reading it — which is the finding.
    previous = os.environ.get("JARVIS_AUDIT_KEY")
    os.environ["JARVIS_AUDIT_KEY"] = secrets.token_hex(16)
    try:
        return _probe_chain_inner(AuditLogger, SecurityEvent, SecurityEventType)
    finally:
        if previous is None:
            os.environ.pop("JARVIS_AUDIT_KEY", None)
        else:
            os.environ["JARVIS_AUDIT_KEY"] = previous


def _probe_chain_inner(AuditLogger, SecurityEvent, SecurityEventType) -> dict:
    # Every AuditLogger opened here is closed in a finally before the TemporaryDirectory
    # unlinks the file. POSIX happily unlinks an open file, so a leaked handle is
    # invisible on Linux; Windows raises PermissionError [WinError 32] out of the cleanup
    # and the whole probe dies. tests/test_audit_hardening.py already calls close() on its
    # loggers — this follows that convention rather than inventing one.
    logger = after = None
    with tempfile.TemporaryDirectory(prefix="adv001-") as d:
        try:
            db = str(Path(d) / "audit.db")
            logger = AuditLogger(db_path=db)
            planted = ["payment approved 5000 EUR", "autonomy raised to L3",
                       "kill-switch disengaged"]
            for i, text in enumerate(planted):
                logger.log(SecurityEvent(
                    event_type=SecurityEventType.AUDIT_LOG,
                    timestamp=1753600000.0 + i,
                    content_preview=text,
                    action_taken="logged",
                ))
            baseline = logger.verify_chain()
            algos = [r[0] for r in logger._conn.execute(
                "SELECT hash_algo FROM security_events ORDER BY id")]
            logger.close()

            # The attacker's whole toolkit: sqlite3 + hashlib. The key is never read.
            con = sqlite3.connect(db)
            try:
                rows = con.execute(
                    "SELECT id, timestamp, event_type, findings_json, action_taken "
                    "FROM security_events ORDER BY id").fetchall()
                prev = ""
                for n, (rid, ts, etype, findings, action) in enumerate(rows):
                    forged = f"attacker rewrote row {n + 1}"
                    row_hash = hashlib.sha256(
                        f"{prev}|{ts}|{etype}|{findings}|{forged}|{action}".encode()).hexdigest()
                    con.execute(
                        "UPDATE security_events SET content_preview=?, row_hash=?, prev_hash=?, "
                        "hash_algo='sha256' WHERE id=?", (forged, row_hash, prev, rid))
                    prev = row_hash
                con.commit()
            finally:
                con.close()

            after = AuditLogger(db_path=db)
            forged_ok, first_bad = after.verify_chain()
            content = [r[0] for r in after._conn.execute(
                "SELECT content_preview FROM security_events ORDER BY id")]
        finally:
            for opened in (logger, after):
                if opened is not None:
                    # A close that fails must not mask the real exception on the way out,
                    # and a double close is harmless — logger is closed above by design.
                    with contextlib.suppress(Exception):
                        opened.close()

    return {
        "claim": "a keyed audit chain can be rewritten wholesale by downgrading every row to sha256",
        "verdict": OPEN if forged_ok else CLOSED,
        "detail": {
            "baseline_verify": list(baseline),
            "row_algos": algos,
            "verify_after_full_downgrade": [forged_ok, first_bad],
            "content_after": content,
        },
        "means": ("OPEN: verify_chain() returned True over a fully rewritten table — the "
                  "hardened-mode guarantee is void. CLOSED: the chain now rejects a "
                  "post-legacy sha256 row while a key is configured."),
    }


# ── ADV-015 · forget does not erase ──────────────────────────────────────────
_KNOWN_USER_STORES = {
    # store filename -> the module that owns it (all verified present in this tree)
    "run_history.json": "agents/core/run_history.py",
    "channel_inbox.json": "agents/core/channel_inbox.py",
    "feedback.db": "agents/core/feedback_store.py",
    "autonomy_journal.jsonl": "agents/core/autonomy/preferences.py",
    "problems.jsonl": "agents/core/autonomy/error_logger.py",
    "passive_capture.json": "agents/core/passive_capture.py",
    "rooms.json": "agents/core/rooms.py",
    "review_queue.json": "agents/core/observability/review_queue.py",
    "data_spaces.json": "agents/core/data_spaces.py",
    "arena.json": "agents/core/arena.py",
    "notes.db": "agents/core/data_export.py",
    "checkpoints.db": "agents/core/checkpoint.py",
}


def probe_purge() -> dict:
    """Which known user-content stores are outside every purge allowlist?

    ``PURGE_DBS`` is three databases, ``PURGE_JSON`` is two files, and
    ``PURGE_MEMORY_FILES`` covers the memory subsystem by exact name. Anything else that
    holds user content simply survives ``POST /api/admin/forget``, which
    ``docs/PRIVACY.md`` says "erases memory, transcripts, vectors, and the knowledge
    graph at rest".
    """
    from agents.core import data_purge as dp
    from agents.core.data_export import EXPORT_DBS

    covered = set(dp.PURGE_DBS) | set(dp.PURGE_JSON) | set(dp.PURGE_MEMORY_FILES)
    survivors = {name: owner for name, owner in sorted(_KNOWN_USER_STORES.items())
                 if name not in covered}
    export_only = sorted(set(EXPORT_DBS) - set(dp.PURGE_DBS))
    return {
        "claim": "user-content stores survive a forget because the purge works from an allowlist",
        "verdict": OPEN if survivors else CLOSED,
        "detail": {
            "purge_dbs": list(dp.PURGE_DBS),
            "purge_json": list(dp.PURGE_JSON),
            "surviving_stores": survivors,
            "exported_but_never_purged": export_only,
            "backup_first_forced_by_route": True,
        },
        "means": ("OPEN: each listed store keeps its contents through a forget. The "
                  "audit's proposed shape is the inverse — purge everything under the "
                  "data root except an explicit KEEP allowlist."),
    }


def probe_clear() -> dict:
    """Is the vector/KG wipe dead code?

    ``clear_live_memory`` calls ``store.clear()`` behind ``if hasattr(...)``, so a store
    with no ``clear()`` is a silent no-op and the purge still reports ``ok``.
    """
    targets = [
        ("InMemoryVectorStore", "agents.core.memory.store"),
        ("QdrantVectorStore", "agents.core.memory.qdrant_store"),
        ("InMemoryGraph", "agents.core.memory.graph"),
        ("Neo4jGraph", "agents.core.memory.graph"),
    ]
    missing, present, unavailable = [], [], []
    for cls_name, module in targets:
        try:
            mod = __import__(module, fromlist=[cls_name])
            cls = getattr(mod, cls_name)
        except Exception:
            unavailable.append(cls_name)
            continue
        (present if callable(getattr(cls, "clear", None)) else missing).append(cls_name)
    verdict = OPEN if missing else (NA if unavailable and not present else CLOSED)
    return {
        "claim": "no vector store or knowledge graph implements clear(), so the hasattr-guarded wipe never runs",
        "verdict": verdict,
        "detail": {"no_clear": missing, "has_clear": present, "could_not_import": unavailable},
        "means": ("OPEN under the documented qdrant/neo4j backends every embedding and "
                  "every KG triple survives a forget permanently. The audit's fix is to "
                  "make clear() abstract so a missing implementation is an import error."),
    }


# ── ADV-035 · an unkeyed hash presented as a signature ───────────────────────
def _signing_is_configured(signing) -> bool:
    """True when a signing secret exists. Only this bool leaves the function.

    A single narrow place where the value is touched, so there is no path from the secret
    to any output — not truncated, not measured, not described.
    """
    return signing._signing_key() is not None


def probe_signing() -> dict:
    """Does ``require_signed()`` fail closed when enforcement is on and no key is set?

    ``compute_digest`` returns a plain ``sha256:`` digest with no key configured, and
    ``require_signed()`` reads one env flag and nothing else — so an attacker who ships
    their own ``SKILL.sig`` computes a matching digest without any secret.

    Never prints key material: only whether signing is configured at all. The value is
    reduced to a bool inside ``_signing_is_configured`` and nothing else about it — not a
    prefix, not a length — leaves that function. Nothing in the output is named for a
    credential either, which is deliberate: a detector that echoes what it detects is the
    classic own-goal, and ``scripts/check_test_manual.py`` carries the scar tissue from
    getting this wrong three times.
    """
    from agents.core.skills import signing

    src = (ROOT / "agents/core/skills/signing.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    body = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "require_signed"), None)
    consults_a_configured_secret = bool(body) and "_signing_key" in ast.unparse(body)
    return {
        "claim": "hardening JARVIS_REQUIRE_SIGNED_SKILLS buys nothing when no signing key is configured",
        "verdict": CLOSED if consults_a_configured_secret else OPEN,
        "detail": {
            "require_signed_consults_a_configured_secret": consults_a_configured_secret,
            "signing_is_configured_on_this_host": _signing_is_configured(signing),
            "unkeyed_algo_label": signing.compute_digest(ROOT / "agents/core/skills")[0],
        },
        "means": ("OPEN: enforcement accepts an unkeyed digest, so the gate stops honest "
                  "unsigned content and not a deliberate adversary. Note the audit's "
                  "correction: the exec primitive in loader._load_skill, not the hash, is "
                  "what grants code execution — fix that first."),
    }


# ── ADV-069 · the honesty badge ──────────────────────────────────────────────
_HONESTY_ATTRS = ("configured", "available", "_configured")


# Manifest id -> module basename, where the convention (dash to underscore) does not hold.
_PLUGIN_MODULE_ALIASES = {
    "telegram": "telegram_bot",
    "gmail": "gmail_plugin",
    "spotify": "spotify_plugin",
}


def _class_members(node: ast.ClassDef) -> set[str]:
    members: set[str] = set()
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.add(item.name)
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            members.add(item.target.id)          # counting AnnAssign matters: the audit's
        elif isinstance(item, ast.Assign):        # own worst miscount came from skipping it
            members.update(t.id for t in item.targets if isinstance(t, ast.Name))
    return members


def probe_honesty() -> dict:
    """Which plugins does ``honesty.py`` contradict itself about?

    The test is deliberately narrow, because the loose version is wrong: a keyless
    plugin (weather, news, stock quotes) *should* badge green, so "exposes no
    ``configured``" is not by itself a defect. The defensible claim is an internal
    contradiction inside one module — the plugin's id appears in ``honesty._NEEDS``,
    which says the owner must supply a key, **and** its class exposes none of
    ``configured``/``available``/``_configured``, so ``plugin_configured`` falls through
    to ``(True, "loaded")`` and ``honesty_for`` maps ``"loaded"`` to *live, no setup
    required*. The module asserts both "needs a key" and "needs no setup".

    A class with no ``degradation_info()`` also gets no amber MOCK chip next to the green
    one (``frontend/src/modes3.tsx``), so that row is a clean green lie rather than a
    visible contradiction the owner can spot.

    Static (AST) on purpose: booting the plugin host would need the owner's real keys, and
    the audit's worst methodology error came from a stubbed runtime.
    """
    from agents.core.plugins.honesty import _NEEDS

    plugin_dir = ROOT / "agents/core/plugins"
    contradicted, unresolved, honest = [], [], []
    for pid in sorted(_NEEDS):
        base = _PLUGIN_MODULE_ALIASES.get(pid, pid.replace("-", "_"))
        path = plugin_dir / f"{base}.py"
        if not path.exists():
            unresolved.append(pid)
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            unresolved.append(pid)
            continue
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name.endswith("Plugin")]
        if not classes:
            unresolved.append(pid)
            continue
        members = set().union(*(_class_members(c) for c in classes))
        rel = f"agents/core/plugins/{path.name}"
        if any(a in members for a in _HONESTY_ATTRS):
            honest.append(pid)
        else:
            contradicted.append({
                "plugin": pid,
                "module": rel,
                "needs": _NEEDS[pid],
                "has_degradation_info": "degradation_info" in members,
            })
    silent = [r["plugin"] for r in contradicted if not r["has_degradation_info"]]

    # The other direction: amber with nothing actionable in `needs`.
    amber_empty = []
    for pid in ("analytics",):
        base = _PLUGIN_MODULE_ALIASES.get(pid, pid.replace("-", "_"))
        path = plugin_dir / f"{base}.py"
        if path.exists() and pid not in _NEEDS:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            members = set().union(*[_class_members(n) for n in tree.body
                                    if isinstance(n, ast.ClassDef)] or [set()])
            if "configured" not in members and "available" in members:
                amber_empty.append(pid)

    return {
        "claim": "honesty.py badges plugins LIVE that its own _NEEDS table says require a key",
        "verdict": OPEN if contradicted or amber_empty else CLOSED,
        "detail": {
            "needs_a_key_but_badges_live": contradicted,
            "green_with_no_mock_chip": silent,
            "amber_with_an_empty_needs_list": amber_empty,
            "resolved_and_honest": honest,
            "could_not_resolve_to_a_module": unresolved,
        },
        "means": ("OPEN: each listed plugin badges LIVE on a keyless boot while the same "
                  "module names the key it needs. green_with_no_mock_chip are the clean "
                  "misstatements — the rest render [MOCK] beside the green, so the owner "
                  "at least sees a contradiction. Verify every one against a real "
                  "keyless boot before filing: this probe reads source, not runtime."),
    }


# ── ADV-078 · nothing measures LLM spend ─────────────────────────────────────
def probe_cost() -> dict:
    """Is ``cost_tracker.record()`` reachable from anything that runs an LLM call?

    Three cost endpoints are wired (``GET /api/cost``, ``GET /api/analytics/cost``,
    ``GET /api/admin/apm``) and read a meter nothing feeds, so they render a confident
    zero rather than "unknown".
    """
    hits = []
    for path in sorted((ROOT / "agents").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.endswith("core/cost_tracker.py"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "cost_tracker" in text and "record" in text:
            for i, line in enumerate(text.splitlines(), 1):
                if "cost_tracker" in line and "record" in line:
                    hits.append(f"{rel}:{i}")
    from agents.core.llm.cost_estimator import estimate_cost
    unpriced = estimate_cost("a-model-nobody-priced", 1000, 1000)
    return {
        "claim": "cost_tracker.record() is never called from the router, and an unpriced model reports 0.0 rather than unknown",
        "verdict": OPEN if not hits else CLOSED,
        "detail": {"record_call_sites_outside_the_tracker": hits, "unpriced_model_estimate": unpriced},
        "means": ("OPEN: the meter has no producer, so every cost surface is structurally "
                  "zero and an unattended cloud night-shift has no ceiling and leaves no "
                  "signal."),
    }


# ── ADV-087 · evidence that grades its own homework ──────────────────────────
def probe_reality() -> dict:
    """Does the promotable action-capability case import the implementation it certifies?

    ``_make_action_kernel_probe`` registers its own handler on ``CapabilityActionAPI`` and
    asserts the kill-switch refuses the call. ``manifest.implementation`` is never
    resolved, so the promotion criterion is independent of whether any actuator exists.
    """
    src = (ROOT / "agents/core/observability/reality_harness.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_make_action_kernel_probe"), None)
    body = ast.unparse(fn) if fn else ""
    return {
        "claim": "the only promotable action-capability case registers its own lambda and never imports the manifest implementation",
        "verdict": OPEN if (body and "api.register" in body
                            and "manifest.implementation" not in body) else CLOSED,
        "detail": {
            "registers_own_handler": "api.register" in body,
            "resolves_manifest_implementation": "manifest.implementation" in body,
        },
        "means": ("OPEN: a green action case proves the kill-switch refuses a lambda, not "
                  "that an actuator exists. Mitigating and worth recording: run_reality has "
                  "no caller under agents/, promotion is in-process, and the registry "
                  "reseeds each boot — so a running install still reports verified: 0."),
    }


def probe_ambient() -> dict:
    """Is the ambient pack's ``ungoverned_actions`` counter a literal?

    ``STATUS.md`` reads the H33 pack's ``ungoverned_actions == 0`` as evidence. In
    ``agents/core/observability/ambient_reality.py`` it is the integer ``0``, assigned —
    not measured. (The audit's skeptic corrected the severity down: the *property* is
    covered by ``tests/test_h33_ladder_engine.py``. This is an evidence defect.)
    """
    src = (ROOT / "agents/core/observability/ambient_reality.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    literal_keys = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=False):
            if (isinstance(key, ast.Constant) and key.value in ("ungoverned_actions", "action_calls")
                    and isinstance(value, ast.Constant)):
                literal_keys.append(f"{key.value}={value.value!r}")
    return {
        "claim": "the H33 safety counters STATUS.md cites are integer literals, not measurements",
        "verdict": OPEN if literal_keys else CLOSED,
        "detail": {"literal_counters": sorted(set(literal_keys))},
        "means": ("OPEN: gutting the proposal sink leaves the pack green. The ladder "
                  "property itself is covered elsewhere — grade this as evidence honesty, "
                  "not as an untested safety property."),
    }


def probe_parity() -> dict:
    """Does the HUD parity gate check coverage, or only classify a prefix?

    ``_classify`` prefix-matches against ``RULES``, so an endpoint nobody has written and
    no client calls still resolves to a surface and the gate goes green.
    """
    sys.path.insert(0, str(ROOT / "tests"))
    try:
        from test_hud_v2_parity import _classify
    except Exception as exc:                                    # pragma: no cover
        return {"claim": "the parity gate classifies rather than covers",
                "verdict": NA, "detail": {"import_error": str(exc)}, "means": "could not load the gate"}
    invented = "/api/admin/totally-invented-endpoint"
    surface = _classify(invented)
    return {
        "claim": "the HUD parity gate matches a URL prefix instead of asking whether any client calls the route",
        "verdict": OPEN if surface != "UNMAPPED" else CLOSED,
        "detail": {"invented_path": invented, "classified_as": surface},
        "means": ("OPEN: classification is not coverage. The audit corrected the count of "
                  "uncalled user-facing routes down to roughly 68 of 358 — about 16 of the "
                  "originally reported ones were inbound or machine-facing and merely "
                  "misclassified by RULES."),
    }


PROBES = {
    "chain": probe_chain,
    "purge": probe_purge,
    "clear": probe_clear,
    "signing": probe_signing,
    "honesty": probe_honesty,
    "cost": probe_cost,
    "reality": probe_reality,
    "ambient": probe_ambient,
    "parity": probe_parity,
}

# The case in docs/test-manual/15-audit-gap-verification.md that each probe serves. The
# case is the authority: it carries the live cross-check, and the probe is only its lead.
CASES = {
    "chain": "ADV-001", "purge": "ADV-015", "clear": "ADV-022", "signing": "ADV-035",
    "honesty": "ADV-069", "cost": "ADV-078", "reality": "ADV-087", "ambient": "ADV-091",
    "parity": "ADV-096",
}


def _summary(fn) -> str:
    """First docstring line, or "" — never raises, including for a doc-less callable."""
    doc = getattr(fn, "__doc__", None)
    return doc.strip().splitlines()[0] if doc and doc.strip() else ""


def run(names: list[str]) -> dict:
    out = {}
    for name in names:
        try:
            out[name] = PROBES[name]()
        except Exception as exc:
            # The fallback must not be able to raise: a probe that dies *and* takes the
            # error handler with it would surface as a traceback, and a tester reading a
            # traceback records nothing at all. Hence no attribute access on __doc__.
            out[name] = {"claim": _summary(PROBES[name]) or f"probe {name}",
                         "verdict": NA, "detail": {"probe_error": f"{type(exc).__name__}: {exc}"},
                         "means": "the probe itself failed — record that, do not infer a verdict"}
        out[name]["case"] = CASES.get(name, "")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("probes", nargs="*", help=f"one or more of: {', '.join(PROBES)} (default: all)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--list", action="store_true", help="list probes and exit")
    args = ap.parse_args(argv)

    if args.list:
        for name, fn in PROBES.items():
            print(f"{CASES.get(name, chr(8212)):8s} {name:9s} {_summary(fn)}")
        return 0

    names = args.probes or list(PROBES)
    unknown = [n for n in names if n not in PROBES]
    if unknown:
        print(f"unknown probe(s): {unknown}; known: {list(PROBES)}", file=sys.stderr)
        return 2

    results = run(names)
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True, default=str))
        return 0

    print(f"{'CASE':9s} {'PROBE':10s} {'VERDICT':8s} CLAIM")
    for name, r in results.items():
        print(f"{r['case']:9s} {name:10s} {r['verdict']:8s} {r['claim']}")
    print()
    for name, r in results.items():
        print(f"── {r['case']} · {name} — {r['verdict']}")
        for key, value in r["detail"].items():
            print(f"     {key}: {value}")
        print(f"     → {r['means']}")
        print()
    print("A verdict is a lead, not a finding. Cross-check each OPEN against the live "
          "surface named in the case before you file it (docs/test-manual/15-audit-gap-verification.md).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
