#!/usr/bin/env python3
"""Generate the API-surface sweep chapter of the deep test manual.

The sweep enumerates **every** HTTP route the app exposes, with its auth tier and a
copy-pasteable probe, so a manual run can prove it touched the whole surface instead of
sampling it. It is generated — never hand-edited — because the surface changes with every
route PR and a hand-maintained table would silently rot into fabrication:

    python scripts/gen_api_sweep.py            # rewrite docs/test-manual/14-api-surface-sweep.md
    python scripts/gen_api_sweep.py --check     # exit 1 if the committed file is stale

Sources of truth (both reseeded by the route snapshot tests):
  tests/_snapshots/route_surface.json   every "METHOD /path" the app serves
  tests/_snapshots/route_auth.json      the same, mapped to its guard tier (admin/user/open)

`route_auth.json` additionally carries FastAPI's own doc routes (/docs, /redoc,
/openapi.json, /docs/oauth2-redirect), which are not part of the app surface snapshot; they
are emitted in their own group rather than dropped, since they are reachable and worth a
tier check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SURFACE = ROOT / "tests/_snapshots/route_surface.json"
AUTH = ROOT / "tests/_snapshots/route_auth.json"
TARGET = ROOT / "docs/test-manual/14-api-surface-sweep.md"

# Which manual section owns the semantics of each route group. The sweep proves a route
# EXISTS and is guarded correctly; the owning section proves it BEHAVES correctly.
OWNER = {
    "a2a": "08", "acquisition": "10 · 12", "actions": "07", "admin": "05 · 08",
    "agent-templates": "05", "agents": "02", "ambient": "12", "analytics": "09",
    "arena": "10", "autonomy": "07", "brain": "06", "browser": "12", "cameras": "12",
    "canvas": "05", "capabilities": "04", "capture": "09", "channels": "11",
    "coach": "05", "codeintel": "09", "cognition": "09", "context": "09", "cost": "09",
    "creative": "05", "dashboard": "05", "desktop": "06", "digest": "07", "eval": "10",
    "feedback": "10", "health": "01", "house": "12", "ingestion": "09",
    "integrations": "11", "kg": "09", "learning": "07", "llm": "02", "local-docs": "09",
    "market": "05", "mcp": "08", "media": "12", "memory": "09", "mesh": "04",
    "metrics": "07", "missions": "07", "models": "02", "multimodal": "05", "nodes": "04",
    "notes": "09", "oauth": "05", "onboarding": "05", "oracle": "04", "osint": "04",
    "pairing": "08", "payments": "07", "plugins": "02", "presence": "07",
    "provenance": "09", "quality": "10", "reflection": "09", "resilience": "01",
    "review": "10", "rooms": "09", "sandbox": "08", "satellites": "04", "schedule": "07",
    "secrets": "08", "security": "08", "security-skills": "08",
    "self-improvement": "10", "sessions": "09", "skills": "08", "status": "01",
    "subagents": "06", "support": "11", "swarm": "06", "sync": "04", "system": "01",
    "system-profiles": "05", "toolrpc": "05", "tools": "05", "traces": "09",
    "transcripts": "05", "trust": "04", "vlm": "05", "voice": "11", "webhooks": "11",
    "widget": "06", "workflows": "10", "worldview": "06", "wyoming": "11",
    # non-/api groups (prefixed "~" while grouping)
    "~(root)": "03", "~.well-known": "08", "~admin": "03 · 06", "~agents": "02",
    "~autonomy": "07", "~bench": "10", "~brain": "06", "~chat": "02",
    "~dashboard": "05", "~favicon.ico": "03", "~healthz": "01", "~heartbeat": "07",
    "~learning": "07", "~memory": "09", "~metrics": "07", "~mission-control": "06",
    "~plugins": "02", "~readyz": "01", "~sandbox": "08", "~security": "08",
    "~sessions": "09", "~skills": "08", "~status": "01", "~sw.js": "06",
    "~tasks": "07", "~ticker": "03", "~tts": "11", "~v1": "03", "~v2": "03",
    "~docs": "01", "~openapi.json": "01", "~redoc": "01",
}

HEADER = {
    "admin": '-H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" ',
    "user": '-H "X-User-Token: $JARVIS_USER_TOKEN" ',
    "open": "",
}

READ_METHODS = {"GET", "HEAD"}


def group_of(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if parts and parts[0] == "api":
        return parts[1] if len(parts) > 1 else "(api-root)"
    return "~" + (parts[0] if parts else "(root)")


def probe(method: str, path: str, tier: str) -> tuple[str, str]:
    """Return (how to hit it, what proves it healthy)."""
    templated = "{" in path
    if method in READ_METHODS and not templated:
        cmd = f'`curl -sS {HEADER[tier]}-o /dev/null -w "%{{http_code}}\\n" $B{path}`'
        return cmd, "**200** — or a documented 4xx/503 whose body says honestly why"
    if method in READ_METHODS:
        return (
            f"`GET $B{path}` with a real id from this group's list route",
            "**200** for a live id · **404** for a bogus one — never a fabricated record",
        )
    return (
        f"mutating — needs a body; exercise it in §{OWNER.get(group_of(path), '—')}",
        "**401/403** with no token · state actually changes only on a valid call",
    )


def build() -> str:
    surface: list[str] = json.loads(SURFACE.read_text(encoding="utf-8"))
    auth: dict[str, str] = json.loads(AUTH.read_text(encoding="utf-8"))

    groups: dict[str, list[tuple[str, str, str]]] = {}
    for route in sorted(set(surface) | set(auth)):
        method, path = route.split(" ", 1)
        groups.setdefault(group_of(path), []).append((method, path, auth.get(route, "?")))

    tiers = {t: sum(1 for v in auth.values() if v == t) for t in ("user", "admin", "open")}
    doc_only = sorted(set(auth) - set(surface))

    out: list[str] = []
    w = out.append

    w("# 14. API surface sweep — every route, every tier")
    w("")
    w("> **Scope.** A complete, generated enumeration of the HTTP surface: "
      f"**{len(surface)} app routes** (the figure `project-status.json` → `routes` reports) "
      f"**plus {len(doc_only)} FastAPI doc routes** = **{len(surface) + len(doc_only)} enumerated "
      f"below** — the two numbers are not a contradiction, they count different things. Across "
      f"**{len(groups)}** groups, each with its guard tier and a copy-pasteable probe. "
      "This chapter proves a route **exists and is guarded correctly**; the *owning section* "
      "proves it **behaves correctly** — follow the §-pointer in each group heading.")
    w("> **Prereqs.** A booted server and both tokens exported. "
      "`export B=http://127.0.0.1:8080` first — every probe uses `$B`.")
    w("> **Time.** ~90 min for the read-route sweep with the loop in 14.1; the mutating routes "
      "are exercised by their owning sections, not here.")
    w("")
    w("**GENERATED FILE — do not hand-edit.** Regenerate after any route change:")
    w("")
    w("```bash")
    w("python scripts/gen_api_sweep.py           # rewrite this file")
    w("python scripts/gen_api_sweep.py --check   # CI-style staleness check")
    w("```")
    w("")
    w("Sources: `tests/_snapshots/route_surface.json` + `tests/_snapshots/route_auth.json`, "
      "both pinned by `tests/test_route_parity_guard.py` and `tests/test_route_auth_matrix.py`. "
      "If this file disagrees with the running server, that is itself a finding — see 14.2.")
    w("")
    w("## 14.0 Tier distribution & the localhost trap")
    w("")
    w("| Tier | Routes | Guard | Sweep meaning |")
    w("|---|---|---|---|")
    w(f"| `user` | {tiers['user']} | `user_guard` (`X-User-Token`) | 403 when `JARVIS_USER_TOKEN` "
      "is unset, 401 when set but missing/wrong |")
    w(f"| `admin` | {tiers['admin']} | `admin_guard` (`X-Admin-Token`) | must reject a user token "
      "as well as no token |")
    w(f"| `open` | {tiers['open']} | none by design | must expose nothing tier-gated — the "
      "highest-value leak hunt in this chapter |")
    w("")
    w("> ⚠️ **The localhost trap — read before you sweep.** Tokenless requests from the box "
      "itself are allowed **by design** (`agents/web.py` `_admin_guard`). So a sweep run on the "
      "server host proves *routing*, not *authorization*: everything will answer 200 and you will "
      "learn nothing about the guards. Every tier assertion in 14.1 must be re-run 🌐 **from a "
      "second device on the LAN** (the owner's phone works). A sweep run only on localhost must be "
      "recorded as **partial — localhost bypass**, never as a passing auth test.")
    w("")
    w("## 14.1 The sweep protocol")
    w("")
    w("Run three passes. Pass A is a cheap existence check you can automate; passes B and C are the "
      "ones that actually test security.")
    w("")
    w("**Pass A — existence & honesty (localhost, automatable).** For every read route below: "
      "expect 200, or a 4xx/503 whose body states plainly why (`{\"error\": \"presence not "
      "available\"}` is a PASS; an empty 200 that renders as fabricated data downstream is a "
      "BLOCKER). Record any 500 — an unhandled exception on a read route is at least MAJOR.")
    w("")
    w("```bash")
    w("# Pass A driver — walks every read route in this chapter and flags anything unexpected.")
    w("export B=http://127.0.0.1:8080")
    w("python - <<'EOF'")
    w("import json, os, urllib.request")
    w("B = os.environ['B']")
    w("auth = json.load(open('tests/_snapshots/route_auth.json'))")
    w("hdr = {'admin': {'X-Admin-Token': os.environ.get('JARVIS_ADMIN_TOKEN','')},")
    w("       'user':  {'X-User-Token':  os.environ.get('JARVIS_USER_TOKEN','')}, 'open': {}}")
    w("for route, tier in sorted(auth.items()):")
    w("    m, p = route.split(' ', 1)")
    w("    if m != 'GET' or '{' in p: continue          # templated + mutating: owning section")
    w("    req = urllib.request.Request(B + p, headers=hdr.get(tier, {}))")
    w("    try:")
    w("        with urllib.request.urlopen(req, timeout=20) as r: code = r.status")
    w("    except Exception as e: code = getattr(e, 'code', repr(e))")
    w("    if code != 200: print(f'{code}  {tier:5s}  {route}')")
    w("print('done — every line above needs an explanation in the run record')")
    w("EOF")
    w("```")
    w("")
    w("**Pass B — tier enforcement 🌐 (second device, the real test).** From another device on the "
      "LAN, for a sample of at least **10 `admin`**, **10 `user`** and **all `open`** routes: no "
      "token → expected 401/403; a *user* token on an *admin* route → still rejected; the correct "
      "token → 200. Any admin route answering a user token is a **BLOCKER**.")
    w("")
    w("**Pass C — payload-tier leak hunt.** For every `user`-tier and `open` route that returns a "
      "collection, read the body and ask: *does this contain anything the admin tier is meant to "
      "gate?* (drafts, tool results, secrets, payloads, household identifiers, camera data). The "
      "worked example is `GET /tasks`: it is user-tier while every `/autonomy/*` read is admin, so "
      "`format_task` (`agents/core/routers/dashboard.py`, BACKLOG **TASK-5**) strips `payload` and "
      "`result` on all three view paths — confirm both keys are **absent** from every task in "
      "`/tasks`, `/tasks?view=running` and `/tasks?view=history`, then hunt for others. Either key "
      "reappearing there, or any new instance elsewhere, is a **MAJOR** finding.")
    w("")
    w("## 14.2 Snapshot & contract drift")
    w("")
    w("| ID | Check | Do | Expect | Fail |")
    w("|----|-------|----|--------|------|")
    w("| API-000a | The running server matches the snapshots | compare `GET /openapi.json` paths "
      "against `route_surface.json` | identical sets | MAJOR — a route exists that no snapshot, "
      "auth matrix or test knows about |")
    w("| API-000b | Snapshot guards are green | `python -m pytest tests/test_route_parity_guard.py "
      "tests/test_route_auth_matrix.py -q` | pass | BLOCKER — the auth matrix is the security "
      "contract |")
    w("| API-000c | Generated TS types match | the `openapi-types` CI job "
      "(`.github/workflows/ci.yml`) / `frontend/src/api/schema.gen.ts` | no drift | MINOR |")
    w("| API-000d | This chapter is current | `python scripts/gen_api_sweep.py --check` | clean | "
      "MINOR — regenerate and note it |")
    w("")

    n = 0
    for name in sorted(groups, key=lambda g: (g.startswith("~"), g)):
        routes = groups[name]
        label = name[1:] if name.startswith("~") else f"/api/{name}"
        owner = OWNER.get(name, "—")
        w(f"## 14.3.{name.lstrip('~')} `{label}` — {len(routes)} routes · behaviour owned by §{owner}")
        w("")
        w("| ID | Method | Path | Tier | Probe | Expect |")
        w("|----|--------|------|------|-------|--------|")
        for method, path, tier in sorted(routes, key=lambda r: (r[1], r[0])):
            n += 1
            how, exp = probe(method, path, tier)
            w(f"| API-{n:03d} | `{method}` | `{path}` | `{tier}` | {how} | {exp} |")
        w("")

    w("## 14.Z Coverage ledger")
    w("")
    w("| Pass | Routes | Needs | Records |")
    w("|---|---|---|---|")
    w(f"| A — existence & honesty | {sum(1 for r in auth if r.startswith('GET ') and '{' not in r)} "
      "read routes | booted server | one line per non-200 |")
    w(f"| B — tier enforcement | ≥20 sampled + all {tiers['open']} `open` | 🌐 second device | "
      "expected vs actual code per route |")
    w("| C — payload leak hunt | every `user`/`open` collection route | booted server | body "
      "excerpt per suspected leak |")
    w(f"| Mutating routes | {sum(1 for r in auth if not r.startswith(('GET ', 'HEAD ')))} | see the "
      "§-pointer per group | exercised by owning section, not here |")
    w(f"| **Total enumerated** | **{n}** | — | — |")
    w("")
    w("## Open gaps found while writing")
    w("")
    w("- The `open` tier is the largest unaudited attack surface in the sweep "
      f"({tiers['open']} routes). Pass C is the only thing standing between it and a tier leak; "
      "budget real time for it rather than treating it as a formality.")
    w("- Templated read routes (`{id}` paths) are skipped by the Pass-A driver because they need a "
      "live id. They are covered by their owning sections — but that means a broken templated route "
      "can only be caught there, so do not treat a green Pass A as full read coverage.")
    w("- Mutating routes are deliberately not fired here. A sweep that POSTs blindly across "
      f"{sum(1 for r in auth if not r.startswith(('GET ', 'HEAD ')))} routes would mutate the "
      "owner's real state — the opposite of a safe manual.")
    w("")
    w("*Generated by `scripts/gen_api_sweep.py` from the route snapshots at the committed revision.*")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if the committed file is stale")
    args = ap.parse_args(argv)
    fresh = build()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != fresh:
            print(f"{TARGET.relative_to(ROOT)} is stale — run: python scripts/gen_api_sweep.py")
            return 1
        print(f"{TARGET.relative_to(ROOT)} is current")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(fresh, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)} ({fresh.count(chr(10))} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
