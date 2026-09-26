# 14. API surface sweep — every route, every tier

> **Scope.** A complete, generated enumeration of the HTTP surface: **531 app routes** (the figure `project-status.json` → `routes` reports) **plus 4 FastAPI doc routes** = **535 enumerated below** — the two numbers are not a contradiction, they count different things. Across **135** groups, each with its guard tier and a copy-pasteable probe. This chapter proves a route **exists and is guarded correctly**; the *owning section* proves it **behaves correctly** — follow the §-pointer in each group heading.
> **Prereqs.** A booted server and both tokens exported. `export B=http://127.0.0.1:8080` first — every probe uses `$B`.
> **Time.** ~90 min for the read-route sweep with the loop in 14.1; the mutating routes are exercised by their owning sections, not here.

**GENERATED FILE — do not hand-edit.** Regenerate after any route change:

```bash
python scripts/gen_api_sweep.py           # rewrite this file
python scripts/gen_api_sweep.py --check   # CI-style staleness check
```

Sources: `tests/_snapshots/route_surface.json` + `tests/_snapshots/route_auth.json`, both pinned by `tests/test_route_parity_guard.py` and `tests/test_route_auth_matrix.py`. If this file disagrees with the running server, that is itself a finding — see 14.2.

## 14.0 Tier distribution & the localhost trap

| Tier | Routes | Guard | Sweep meaning |
|---|---|---|---|
| `user` | 273 | `user_guard` (`X-User-Token`) | 403 when `JARVIS_USER_TOKEN` is unset, 401 when set but missing/wrong |
| `admin` | 187 | `admin_guard` (`X-Admin-Token`) | must reject a user token as well as no token |
| `open` | 75 | none by design | must expose nothing tier-gated — the highest-value leak hunt in this chapter |

> ⚠️ **The localhost trap — read before you sweep.** Tokenless requests from the box itself are allowed **by design** (`agents/web.py` `_admin_guard`). So a sweep run on the server host proves *routing*, not *authorization*: everything will answer 200 and you will learn nothing about the guards. Every tier assertion in 14.1 must be re-run 🌐 **from a second device on the LAN** (the owner's phone works). A sweep run only on localhost must be recorded as **partial — localhost bypass**, never as a passing auth test.

## 14.1 The sweep protocol

Run three passes. Pass A is a cheap existence check you can automate; passes B and C are the ones that actually test security.

**Pass A — existence & honesty (localhost, automatable).** For every read route below: expect 200, or a 4xx/503 whose body states plainly why (`{"error": "presence not available"}` is a PASS; an empty 200 that renders as fabricated data downstream is a BLOCKER). Record any 500 — an unhandled exception on a read route is at least MAJOR.

```bash
# Pass A driver — walks every read route in this chapter and flags anything unexpected.
export B=http://127.0.0.1:8080
python - <<'EOF'
import json, os, urllib.request
B = os.environ['B']
auth = json.load(open('tests/_snapshots/route_auth.json'))
hdr = {'admin': {'X-Admin-Token': os.environ.get('JARVIS_ADMIN_TOKEN','')},
       'user':  {'X-User-Token':  os.environ.get('JARVIS_USER_TOKEN','')}, 'open': {}}
for route, tier in sorted(auth.items()):
    m, p = route.split(' ', 1)
    if m != 'GET' or '{' in p: continue          # templated + mutating: owning section
    req = urllib.request.Request(B + p, headers=hdr.get(tier, {}))
    try:
        with urllib.request.urlopen(req, timeout=20) as r: code = r.status
    except Exception as e: code = getattr(e, 'code', repr(e))
    if code != 200: print(f'{code}  {tier:5s}  {route}')
print('done — every line above needs an explanation in the run record')
EOF
```

**Pass B — tier enforcement 🌐 (second device, the real test).** From another device on the LAN, for a sample of at least **10 `admin`**, **10 `user`** and **all `open`** routes: no token → expected 401/403; a *user* token on an *admin* route → still rejected; the correct token → 200. Any admin route answering a user token is a **BLOCKER**.

**Pass C — payload-tier leak hunt.** For every `user`-tier and `open` route that returns a collection, read the body and ask: *does this contain anything the admin tier is meant to gate?* (drafts, tool results, secrets, payloads, household identifiers, camera data). The worked example is `GET /tasks`: it is user-tier while every `/autonomy/*` read is admin, so `format_task` (`agents/core/routers/dashboard.py`, BACKLOG **TASK-5**) strips `payload` and `result` on all three view paths — confirm both keys are **absent** from every task in `/tasks`, `/tasks?view=running` and `/tasks?view=history`, then hunt for others. Either key reappearing there, or any new instance elsewhere, is a **MAJOR** finding.

## 14.2 Snapshot & contract drift

| ID | Check | Do | Expect | Fail |
|----|-------|----|--------|------|
| API-000a | The running server matches the snapshots | compare `GET /openapi.json` paths against `route_surface.json` | identical sets | MAJOR — a route exists that no snapshot, auth matrix or test knows about |
| API-000b | Snapshot guards are green | `python -m pytest tests/test_route_parity_guard.py tests/test_route_auth_matrix.py -q` | pass | BLOCKER — the auth matrix is the security contract |
| API-000c | Generated TS types match | the `openapi-types` CI job (`.github/workflows/ci.yml`) / `frontend/src/api/schema.gen.ts` | no drift | MINOR |
| API-000d | This chapter is current | `python scripts/gen_api_sweep.py --check` | clean | MINOR — regenerate and note it |

## 14.3.a2a `/api/a2a` — 7 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-001 | `POST` | `/api/a2a/card` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-002 | `GET` | `/api/a2a/inbox` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/a2a/inbox` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-003 | `POST` | `/api/a2a/inbox/{task_id}/decide` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-004 | `GET` | `/api/a2a/peers` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/a2a/peers` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-005 | `POST` | `/api/a2a/peers` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-006 | `DELETE` | `/api/a2a/peers/{peer_id}` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-007 | `POST` | `/api/a2a/task` | `open` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.acquisition `/api/acquisition` — 8 routes · behaviour owned by §10 · 12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-008 | `GET` | `/api/acquisition/events` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-009 | `GET` | `/api/acquisition/ledger/export` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/ledger/export` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-010 | `POST` | `/api/acquisition/ledger/purge` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |
| API-011 | `GET` | `/api/acquisition/requests` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/requests` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-012 | `GET` | `/api/acquisition/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-013 | `POST` | `/api/acquisition/{name}/revoke` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |
| API-014 | `POST` | `/api/acquisition/{name}/rollback` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |
| API-015 | `POST` | `/api/acquisition/{request_id}/drive` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.actions `/api/actions` — 4 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-016 | `GET` | `/api/actions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/actions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-017 | `GET` | `/api/actions/pending` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/actions/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-018 | `POST` | `/api/actions/request` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-019 | `POST` | `/api/actions/{action_id}/decide` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.admin `/api/admin` — 45 routes · behaviour owned by §05 · 08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-020 | `GET` | `/api/admin/agents/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/agents/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-021 | `PUT` | `/api/admin/agents/{agent_id}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-022 | `POST` | `/api/admin/agents/{agent_id}/description/draft` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-023 | `PUT` | `/api/admin/agents/{agent_id}/soul` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-024 | `GET` | `/api/admin/apm` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/apm` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-025 | `GET` | `/api/admin/audit` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/audit` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-026 | `GET` | `/api/admin/backup` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/backup` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-027 | `POST` | `/api/admin/backup` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-028 | `POST` | `/api/admin/backup/verify` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-029 | `GET` | `/api/admin/env` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/env` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-030 | `GET` | `/api/admin/env/sources` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/env/sources` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-031 | `POST` | `/api/admin/export` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-032 | `POST` | `/api/admin/forget` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-033 | `GET` | `/api/admin/inspector` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/inspector` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-034 | `POST` | `/api/admin/llm/providers/probe` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-035 | `POST` | `/api/admin/llm/test` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-036 | `GET` | `/api/admin/logs` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/logs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-037 | `GET` | `/api/admin/mcp` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/mcp` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-038 | `POST` | `/api/admin/mcp` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-039 | `DELETE` | `/api/admin/mcp/{name}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-040 | `POST` | `/api/admin/mcp/{name}/connect` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-041 | `POST` | `/api/admin/mcp/{name}/disconnect` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-042 | `POST` | `/api/admin/memory/clear` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-043 | `GET` | `/api/admin/network/calls` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/network/calls` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-044 | `GET` | `/api/admin/prompts/{agent_id}/ab` | `admin` | `GET $B/api/admin/prompts/{agent_id}/ab` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-045 | `POST` | `/api/admin/prompts/{agent_id}/ab` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-046 | `POST` | `/api/admin/prompts/{agent_id}/commit` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-047 | `GET` | `/api/admin/prompts/{agent_id}/diff` | `admin` | `GET $B/api/admin/prompts/{agent_id}/diff` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-048 | `GET` | `/api/admin/prompts/{agent_id}/history` | `admin` | `GET $B/api/admin/prompts/{agent_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-049 | `POST` | `/api/admin/prompts/{agent_id}/preview` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-050 | `POST` | `/api/admin/prompts/{agent_id}/rollback` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-051 | `GET` | `/api/admin/prompts/{agent_id}/version/{version}` | `admin` | `GET $B/api/admin/prompts/{agent_id}/version/{version}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-052 | `POST` | `/api/admin/rotate-tokens` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-053 | `GET` | `/api/admin/settings` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/settings` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-054 | `GET` | `/api/admin/settings/export` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/settings/export` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-055 | `POST` | `/api/admin/settings/import` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-056 | `POST` | `/api/admin/settings/reseed` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-057 | `GET` | `/api/admin/settings/{category}` | `admin` | `GET $B/api/admin/settings/{category}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-058 | `PUT` | `/api/admin/settings/{category}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-059 | `POST` | `/api/admin/settings/{category}/reset` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-060 | `GET` | `/api/admin/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-061 | `GET` | `/api/admin/tool-events` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/tool-events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-062 | `GET` | `/api/admin/widgets` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/widgets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-063 | `POST` | `/api/admin/widgets` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-064 | `DELETE` | `/api/admin/widgets/{token}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.agent-templates `/api/agent-templates` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-065 | `GET` | `/api/agent-templates` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/agent-templates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-066 | `POST` | `/api/agent-templates/instantiate` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.agents `/api/agents` — 4 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-067 | `GET` | `/api/agents` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/agents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-068 | `GET` | `/api/agents/history` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/agents/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-069 | `GET` | `/api/agents/{agent_id}/history` | `user` | `GET $B/api/agents/{agent_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-070 | `GET` | `/api/agents/{agent_id}/soul` | `user` | `GET $B/api/agents/{agent_id}/soul` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.ambient `/api/ambient` — 4 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-071 | `GET` | `/api/ambient/monitors` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ambient/monitors` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-072 | `POST` | `/api/ambient/monitors` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-073 | `DELETE` | `/api/ambient/monitors/{monitor_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-074 | `PUT` | `/api/ambient/monitors/{monitor_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.analytics `/api/analytics` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-075 | `GET` | `/api/analytics/cost` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/cost` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-076 | `POST` | `/api/analytics/event` | `open` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-077 | `GET` | `/api/analytics/locality` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/locality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-078 | `GET` | `/api/analytics/model-tiers` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/model-tiers` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.arena `/api/arena` — 4 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-079 | `GET` | `/api/arena/leaderboard` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/arena/leaderboard` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-080 | `GET` | `/api/arena/match/{match_id}` | `user` | `GET $B/api/arena/match/{match_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-081 | `POST` | `/api/arena/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-082 | `POST` | `/api/arena/vote` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.artifacts `/api/artifacts` — 5 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-083 | `GET` | `/api/artifacts` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/artifacts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-084 | `POST` | `/api/artifacts` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-085 | `DELETE` | `/api/artifacts/{artifact_id}` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-086 | `GET` | `/api/artifacts/{artifact_id}/blob` | `user` | `GET $B/api/artifacts/{artifact_id}/blob` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-087 | `POST` | `/api/artifacts/{artifact_id}/pin` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.autonomy `/api/autonomy` — 5 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-088 | `POST` | `/api/autonomy/call` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-089 | `POST` | `/api/autonomy/escalate` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-090 | `GET` | `/api/autonomy/escalation/targets` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/autonomy/escalation/targets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-091 | `POST` | `/api/autonomy/preview` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-092 | `GET` | `/api/autonomy/tasks/{task_id}/preview` | `admin` | `GET $B/api/autonomy/tasks/{task_id}/preview` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.brain `/api/brain` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-093 | `GET` | `/api/brain/summary` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/brain/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.browser `/api/browser` — 2 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-094 | `POST` | `/api/browser/check` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-095 | `POST` | `/api/browser/plan/preview` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.cameras `/api/cameras` — 4 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-096 | `GET` | `/api/cameras/events` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cameras/events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-097 | `POST` | `/api/cameras/onvif/discover` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-098 | `POST` | `/api/cameras/search` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-099 | `GET` | `/api/cameras/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cameras/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.canvas `/api/canvas` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-100 | `GET` | `/api/canvas` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/canvas` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-101 | `POST` | `/api/canvas/clear` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-102 | `POST` | `/api/canvas/post` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-103 | `DELETE` | `/api/canvas/{el_id}` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-104 | `POST` | `/api/canvas/{el_id}/pin` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.capabilities `/api/capabilities` — 1 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-105 | `GET` | `/api/capabilities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.capture `/api/capture` — 7 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-106 | `GET` | `/api/capture` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-107 | `POST` | `/api/capture/clear` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-108 | `GET` | `/api/capture/export` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture/export` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-109 | `POST` | `/api/capture/ingest` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-110 | `GET` | `/api/capture/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-111 | `POST` | `/api/capture/surfaces` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-112 | `DELETE` | `/api/capture/{rec_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.channels `/api/channels` — 15 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-113 | `GET` | `/api/channels/inbox` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/inbox` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-114 | `GET` | `/api/channels/inbox/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/inbox/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-115 | `GET` | `/api/channels/inbox/{thread_id}` | `user` | `GET $B/api/channels/inbox/{thread_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-116 | `POST` | `/api/channels/inbox/{thread_id}/reply` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-117 | `GET` | `/api/channels/pairing` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/pairing` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-118 | `POST` | `/api/channels/pairing/code` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-119 | `POST` | `/api/channels/pairing/decide` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-120 | `POST` | `/api/channels/pairing/link` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-121 | `POST` | `/api/channels/pairing/link/revoke` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-122 | `POST` | `/api/channels/pairing/request` | `open` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-123 | `POST` | `/api/channels/send` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-124 | `GET` | `/api/channels/send-rate-limit` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/send-rate-limit` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-125 | `GET` | `/api/channels/targets` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/targets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-126 | `GET` | `/api/channels/webhook` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/webhook` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-127 | `POST` | `/api/channels/{channel_id}/inbound` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.coach `/api/coach` — 3 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-128 | `POST` | `/api/coach/curriculum` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-129 | `POST` | `/api/coach/review` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-130 | `POST` | `/api/coach/session` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.codeintel `/api/codeintel` — 3 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-131 | `POST` | `/api/codeintel/reindex` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-132 | `GET` | `/api/codeintel/search` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/codeintel/search` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-133 | `GET` | `/api/codeintel/stats` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/codeintel/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.cognition `/api/cognition` — 8 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-134 | `GET` | `/api/cognition` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-135 | `GET` | `/api/cognition/ensemble` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/ensemble` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-136 | `GET` | `/api/cognition/honesty` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/honesty` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-137 | `GET` | `/api/cognition/learning` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/learning` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-138 | `GET` | `/api/cognition/memory` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/memory` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-139 | `GET` | `/api/cognition/personality` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/personality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-140 | `GET` | `/api/cognition/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-141 | `GET` | `/api/cognition/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/stream` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.commands `/api/commands` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-142 | `GET` | `/api/commands` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/commands` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.company `/api/company` — 4 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-143 | `GET` | `/api/company/runs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/company/runs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-144 | `GET` | `/api/company/runs/{run_id}` | `user` | `GET $B/api/company/runs/{run_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-145 | `POST` | `/api/company/runs/{run_id}/stop` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-146 | `GET` | `/api/company/waiting` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/company/waiting` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.context `/api/context` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-147 | `POST` | `/api/context/compress` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.context-refs `/api/context-refs` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-148 | `GET` | `/api/context-refs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/context-refs` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.cost `/api/cost` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-149 | `GET` | `/api/cost` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cost` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.creative `/api/creative` — 4 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-150 | `POST` | `/api/creative/export-packs` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-151 | `POST` | `/api/creative/plan` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-152 | `POST` | `/api/creative/publish/checklist` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-153 | `POST` | `/api/creative/publish/package` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.dashboard `/api/dashboard` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-154 | `GET` | `/api/dashboard/today` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/dashboard/today` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.design-manifest `/api/design-manifest` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-155 | `GET` | `/api/design-manifest` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/design-manifest` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.desktop `/api/desktop` — 4 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-156 | `GET` | `/api/desktop/allowlist` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/desktop/allowlist` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-157 | `POST` | `/api/desktop/plan` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-158 | `POST` | `/api/desktop/preview` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-159 | `POST` | `/api/desktop/run` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.digest `/api/digest` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-160 | `POST` | `/api/digest/run` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.eval `/api/eval` — 4 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-161 | `GET` | `/api/eval/datasets` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/eval/datasets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-162 | `POST` | `/api/eval/datasets/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-163 | `GET` | `/api/eval/datasets/{name}/compare` | `open` | `GET $B/api/eval/datasets/{name}/compare` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-164 | `GET` | `/api/eval/datasets/{name}/runs` | `open` | `GET $B/api/eval/datasets/{name}/runs` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.feedback `/api/feedback` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-165 | `POST` | `/api/feedback` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-166 | `GET` | `/api/feedback/summary` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/feedback/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.health `/api/health` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-167 | `GET` | `/api/health/components` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/health/components` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.help `/api/help` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-168 | `GET` | `/api/help/docs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/help/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-169 | `GET` | `/api/help/docs/{slug}` | `user` | `GET $B/api/help/docs/{slug}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.host `/api/host` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-170 | `GET` | `/api/host/probe` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/host/probe` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.house `/api/house` — 6 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-171 | `POST` | `/api/house/control/climate` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-172 | `POST` | `/api/house/control/light` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-173 | `POST` | `/api/house/control/security` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-174 | `POST` | `/api/house/security/{task_id}/challenge` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-175 | `POST` | `/api/house/security/{task_id}/confirm` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-176 | `GET` | `/api/house/state` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/house/state` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.ingestion `/api/ingestion` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-177 | `GET` | `/api/ingestion/provenance` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ingestion/provenance` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.integrations `/api/integrations` — 4 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-178 | `GET` | `/api/integrations/social` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/integrations/social` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-179 | `POST` | `/api/integrations/social` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-180 | `GET` | `/api/integrations/writeback` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/integrations/writeback` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-181 | `POST` | `/api/integrations/writeback` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.jobs `/api/jobs` — 15 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-182 | `GET` | `/api/jobs` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-183 | `POST` | `/api/jobs` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-184 | `GET` | `/api/jobs/blueprints` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/blueprints` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-185 | `GET` | `/api/jobs/doctor` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/doctor` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-186 | `GET` | `/api/jobs/incidents` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/incidents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-187 | `POST` | `/api/jobs/tick` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-188 | `DELETE` | `/api/jobs/{job_id}` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-189 | `GET` | `/api/jobs/{job_id}` | `admin` | `GET $B/api/jobs/{job_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-190 | `PATCH` | `/api/jobs/{job_id}` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-191 | `PUT` | `/api/jobs/{job_id}/notepad` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-192 | `POST` | `/api/jobs/{job_id}/pause` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-193 | `GET` | `/api/jobs/{job_id}/requests/{request_id}` | `admin` | `GET $B/api/jobs/{job_id}/requests/{request_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-194 | `POST` | `/api/jobs/{job_id}/resume` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-195 | `POST` | `/api/jobs/{job_id}/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-196 | `GET` | `/api/jobs/{job_id}/runs` | `admin` | `GET $B/api/jobs/{job_id}/runs` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.kg `/api/kg` — 10 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-197 | `GET` | `/api/kg/entities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/entities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-198 | `POST` | `/api/kg/entities` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-199 | `DELETE` | `/api/kg/entities/{name}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-200 | `GET` | `/api/kg/entities/{name}` | `user` | `GET $B/api/kg/entities/{name}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-201 | `POST` | `/api/kg/facts` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-202 | `GET` | `/api/kg/facts/as-of` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/facts/as-of` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-203 | `GET` | `/api/kg/facts/history` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/facts/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-204 | `POST` | `/api/kg/ingest` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-205 | `DELETE` | `/api/kg/relations` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-206 | `POST` | `/api/kg/relations` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.learning `/api/learning` — 2 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-207 | `POST` | `/api/learning/evolve` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-208 | `POST` | `/api/learning/propose` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.llm `/api/llm` — 9 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-209 | `GET` | `/api/llm/auth-profiles` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/auth-profiles` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-210 | `POST` | `/api/llm/grammar` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-211 | `POST` | `/api/llm/load` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-212 | `POST` | `/api/llm/moe/route` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-213 | `POST` | `/api/llm/openrouter` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-214 | `GET` | `/api/llm/quota` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/quota` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-215 | `POST` | `/api/llm/server/start` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-216 | `GET` | `/api/llm/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-217 | `POST` | `/api/llm/unload` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.local-docs `/api/local-docs` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-218 | `GET` | `/api/local-docs` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/local-docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-219 | `POST` | `/api/local-docs/index` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.market `/api/market` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-220 | `POST` | `/api/market/brief` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-221 | `POST` | `/api/market/watchlist` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-222 | `GET` | `/api/market/watchlist/saved` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/market/watchlist/saved` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-223 | `POST` | `/api/market/watchlist/saved` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-224 | `DELETE` | `/api/market/watchlist/saved/{symbol}` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.mcp `/api/mcp` — 3 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-225 | `GET` | `/api/mcp/server` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/mcp/server` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-226 | `POST` | `/api/mcp/server/rpc` | `open` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-227 | `POST` | `/api/mcp/token` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.media `/api/media` — 12 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-228 | `GET` | `/api/media` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-229 | `GET` | `/api/media/catalog` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/catalog` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-230 | `GET` | `/api/media/devices` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/devices` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-231 | `POST` | `/api/media/devices` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-232 | `DELETE` | `/api/media/devices/{device_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-233 | `POST` | `/api/media/export` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-234 | `POST` | `/api/media/generate` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-235 | `GET` | `/api/media/generated/{artifact_id}` | `user` | `GET $B/api/media/generated/{artifact_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-236 | `GET` | `/api/media/generation-tasks/{task_id}` | `admin` | `GET $B/api/media/generation-tasks/{task_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-237 | `POST` | `/api/media/present` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-238 | `POST` | `/api/media/restore/{device_id}` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-239 | `GET` | `/api/media/session` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/session` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.memory `/api/memory` — 22 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-240 | `POST` | `/api/memory/consolidate` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-241 | `POST` | `/api/memory/consolidate/apply` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-242 | `GET` | `/api/memory/consolidate/preview` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/consolidate/preview` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-243 | `GET` | `/api/memory/core` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/core` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-244 | `POST` | `/api/memory/core/undo` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-245 | `GET` | `/api/memory/decay/candidates` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/decay/candidates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-246 | `POST` | `/api/memory/decay/forget` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-247 | `GET` | `/api/memory/decay/ranking` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/decay/ranking` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-248 | `GET` | `/api/memory/entities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/entities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-249 | `GET` | `/api/memory/eval/corpus` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/memory/eval/corpus` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-250 | `POST` | `/api/memory/eval/run` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-251 | `GET` | `/api/memory/profile` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/profile` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-252 | `GET` | `/api/memory/recall` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/recall` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-253 | `POST` | `/api/memory/remember` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-254 | `GET` | `/api/memory/search` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/search` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-255 | `POST` | `/api/memory/search-tool` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-256 | `GET` | `/api/memory/spaces` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/spaces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-257 | `POST` | `/api/memory/spaces` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-258 | `POST` | `/api/memory/spaces/assign` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-259 | `POST` | `/api/memory/spaces/unassign` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-260 | `DELETE` | `/api/memory/spaces/{name}` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-261 | `GET` | `/api/memory/tool-spec` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/memory/tool-spec` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.metrics `/api/metrics` — 3 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-262 | `GET` | `/api/metrics/capabilities` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-263 | `GET` | `/api/metrics/kernel` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/kernel` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-264 | `GET` | `/api/metrics/north-star` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/north-star` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.missions `/api/missions` — 9 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-265 | `GET` | `/api/missions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/missions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-266 | `POST` | `/api/missions` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-267 | `GET` | `/api/missions/{mission_id}` | `user` | `GET $B/api/missions/{mission_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-268 | `POST` | `/api/missions/{mission_id}/cancel` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-269 | `POST` | `/api/missions/{mission_id}/complete` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-270 | `POST` | `/api/missions/{mission_id}/pause` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-271 | `POST` | `/api/missions/{mission_id}/resume` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-272 | `POST` | `/api/missions/{mission_id}/start` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-273 | `POST` | `/api/missions/{mission_id}/steps/{idx}/finish` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.models `/api/models` — 3 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-274 | `GET` | `/api/models/info` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/models/info` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-275 | `GET` | `/api/models/local` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/models/local` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-276 | `POST` | `/api/models/local/switch` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.nodes `/api/nodes` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-277 | `GET` | `/api/nodes` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/nodes` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-278 | `POST` | `/api/nodes/register` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-279 | `DELETE` | `/api/nodes/{node_id}` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-280 | `POST` | `/api/nodes/{node_id}/dispatch` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.notes `/api/notes` — 11 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-281 | `DELETE` | `/api/notes` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-282 | `GET` | `/api/notes` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/notes` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-283 | `PUT` | `/api/notes` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-284 | `DELETE` | `/api/notes/blocks/{block_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-285 | `PATCH` | `/api/notes/blocks/{block_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-286 | `GET` | `/api/notes/docs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/notes/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-287 | `POST` | `/api/notes/docs` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-288 | `DELETE` | `/api/notes/docs/{doc_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-289 | `GET` | `/api/notes/docs/{doc_id}` | `user` | `GET $B/api/notes/docs/{doc_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-290 | `POST` | `/api/notes/docs/{doc_id}/blocks` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-291 | `POST` | `/api/notes/rewrite` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.oauth `/api/oauth` — 4 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-292 | `GET` | `/api/oauth/auth-url` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oauth/auth-url` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-293 | `POST` | `/api/oauth/callback` | `open` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-294 | `POST` | `/api/oauth/refresh` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-295 | `GET` | `/api/oauth/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oauth/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.onboarding `/api/onboarding` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-296 | `GET` | `/api/onboarding/command-center` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/command-center` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-297 | `POST` | `/api/onboarding/funnel` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-298 | `GET` | `/api/onboarding/model-plan` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/model-plan` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-299 | `POST` | `/api/onboarding/model-pull` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-300 | `GET` | `/api/onboarding/wizard` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/wizard` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.operator `/api/operator` — 3 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-301 | `GET` | `/api/operator/benchmark` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/operator/benchmark` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-302 | `GET` | `/api/operator/benchmark/pack` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/operator/benchmark/pack` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-303 | `POST` | `/api/operator/plan` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.ops `/api/ops` — 3 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-304 | `GET` | `/api/ops/estop` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ops/estop` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-305 | `POST` | `/api/ops/estop/engage` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-306 | `POST` | `/api/ops/estop/resume` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.oracle `/api/oracle` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-307 | `GET` | `/api/oracle/conflicts` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/oracle/conflicts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-308 | `POST` | `/api/oracle/conflicts/resolve` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-309 | `GET` | `/api/oracle/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oracle/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-310 | `POST` | `/api/oracle/sync` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.osint `/api/osint` — 2 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-311 | `POST` | `/api/osint/brief` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-312 | `POST` | `/api/osint/correlate` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.packs `/api/packs` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-313 | `GET` | `/api/packs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/packs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-314 | `GET` | `/api/packs/{key}/verify` | `user` | `GET $B/api/packs/{key}/verify` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.payments `/api/payments` — 7 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-315 | `GET` | `/api/payments` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/payments` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-316 | `GET` | `/api/payments/mandates` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/payments/mandates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-317 | `POST` | `/api/payments/mandates` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-318 | `POST` | `/api/payments/request` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-319 | `POST` | `/api/payments/{payment_id}/approve` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-320 | `POST` | `/api/payments/{payment_id}/reject` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-321 | `POST` | `/api/payments/{payment_id}/settle` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.permissions `/api/permissions` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-322 | `GET` | `/api/permissions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/permissions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-323 | `POST` | `/api/permissions/{grant_id}/revoke` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.plugins `/api/plugins` — 3 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-324 | `GET` | `/api/plugins/extensions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/plugins/extensions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-325 | `POST` | `/api/plugins/extensions/activate` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-326 | `POST` | `/api/plugins/extensions/consent` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.power `/api/power` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-327 | `GET` | `/api/power` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/power` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-328 | `GET` | `/api/power/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/power/stream` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.preferences `/api/preferences` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-329 | `GET` | `/api/preferences/appearance` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/preferences/appearance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-330 | `PUT` | `/api/preferences/appearance` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.presence `/api/presence` — 2 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-331 | `GET` | `/api/presence/owner` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/presence/owner` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-332 | `POST` | `/api/presence/owner` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.quality `/api/quality` — 3 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-333 | `GET` | `/api/quality` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/quality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-334 | `GET` | `/api/quality/scores` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/quality/scores` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-335 | `POST` | `/api/quality/threshold` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.quickbar `/api/quickbar` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-336 | `GET` | `/api/quickbar/help` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/quickbar/help` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-337 | `POST` | `/api/quickbar/resolve` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.reflection `/api/reflection` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-338 | `POST` | `/api/reflection/run` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-339 | `GET` | `/api/reflection/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/reflection/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.report `/api/report` — 3 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-340 | `GET` | `/api/report/receipt/{audit_id}` | `user` | `GET $B/api/report/receipt/{audit_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-341 | `GET` | `/api/report/today` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/report/today` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-342 | `POST` | `/api/report/today/export` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.resilience `/api/resilience` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-343 | `GET` | `/api/resilience` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/resilience` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.review `/api/review` — 5 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-344 | `POST` | `/api/review/flag` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-345 | `GET` | `/api/review/queue` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/review/queue` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-346 | `GET` | `/api/review/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/review/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-347 | `POST` | `/api/review/{item_id}/dataset` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-348 | `POST` | `/api/review/{item_id}/vote` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.rooms `/api/rooms` — 6 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-349 | `GET` | `/api/rooms` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/rooms` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-350 | `POST` | `/api/rooms` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-351 | `DELETE` | `/api/rooms/{room_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-352 | `GET` | `/api/rooms/{room_id}` | `user` | `GET $B/api/rooms/{room_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-353 | `GET` | `/api/rooms/{room_id}/history` | `user` | `GET $B/api/rooms/{room_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-354 | `POST` | `/api/rooms/{room_id}/message` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.satellites `/api/satellites` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-355 | `GET` | `/api/satellites` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/satellites` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-356 | `POST` | `/api/satellites/register` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-357 | `DELETE` | `/api/satellites/{satellite_id}` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-358 | `POST` | `/api/satellites/{satellite_id}/dispatch` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.schedule `/api/schedule` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-359 | `POST` | `/api/schedule/parse` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.screen `/api/screen` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-360 | `POST` | `/api/screen/reflex` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.secrets `/api/secrets` — 4 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-361 | `GET` | `/api/secrets/broker` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/secrets/broker` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-362 | `POST` | `/api/secrets/broker` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-363 | `POST` | `/api/secrets/broker/redact` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-364 | `DELETE` | `/api/secrets/broker/{name}` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.security `/api/security` — 15 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-365 | `POST` | `/api/security/audit/action` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-366 | `POST` | `/api/security/audit/anchor` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-367 | `GET` | `/api/security/audit/anchors` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/anchors` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-368 | `GET` | `/api/security/audit/intent` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/intent` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-369 | `GET` | `/api/security/audit/verify` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/verify` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-370 | `GET` | `/api/security/capabilities/check` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/capabilities/check` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-371 | `POST` | `/api/security/capabilities/issue` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-372 | `GET` | `/api/security/governance` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/governance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-373 | `GET` | `/api/security/kill-switch` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/kill-switch` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-374 | `POST` | `/api/security/kill-switch` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-375 | `GET` | `/api/security/loop-breaker` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/loop-breaker` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-376 | `POST` | `/api/security/loop-breaker/reset` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-377 | `GET` | `/api/security/posture` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/posture` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-378 | `POST` | `/api/security/scan-injection` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-379 | `POST` | `/api/security/spotlight` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.security-skills `/api/security-skills` — 6 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-380 | `GET` | `/api/security-skills/frameworks` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/frameworks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-381 | `POST` | `/api/security-skills/map` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-382 | `POST` | `/api/security-skills/playbook` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-383 | `GET` | `/api/security-skills/tactics` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/tactics` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-384 | `GET` | `/api/security-skills/technique/{tid}` | `user` | `GET $B/api/security-skills/technique/{tid}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-385 | `GET` | `/api/security-skills/techniques` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/techniques` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.self-improvement `/api/self-improvement` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-386 | `POST` | `/api/self-improvement/enable` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-387 | `GET` | `/api/self-improvement/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/self-improvement/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.signals `/api/signals` — 5 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-388 | `GET` | `/api/signals/agent/{agent_id}` | `user` | `GET $B/api/signals/agent/{agent_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-389 | `GET` | `/api/signals/brief/{domain}` | `user` | `GET $B/api/signals/brief/{domain}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-390 | `GET` | `/api/signals/governance` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/signals/governance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-391 | `POST` | `/api/signals/governance/submit` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-392 | `GET` | `/api/signals/routed` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/signals/routed` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.skills `/api/skills` — 12 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-393 | `GET` | `/api/skills/marketplace` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/marketplace` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-394 | `GET` | `/api/skills/marketplace/history` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/marketplace/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-395 | `POST` | `/api/skills/marketplace/install` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-396 | `POST` | `/api/skills/marketplace/install-zip` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-397 | `POST` | `/api/skills/marketplace/publish` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-398 | `POST` | `/api/skills/marketplace/review` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-399 | `POST` | `/api/skills/marketplace/uninstall` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-400 | `POST` | `/api/skills/marketplace/{name}/rollback` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-401 | `GET` | `/api/skills/pending` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-402 | `GET` | `/api/skills/proposals` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/proposals` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-403 | `POST` | `/api/skills/switch` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-404 | `POST` | `/api/skills/{name}/approve` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.status `/api/status` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-405 | `GET` | `/api/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.subagents `/api/subagents` — 4 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-406 | `GET` | `/api/subagents` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/subagents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-407 | `POST` | `/api/subagents/spawn` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-408 | `POST` | `/api/subagents/{spawn_id}/steer` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-409 | `POST` | `/api/subagents/{spawn_id}/stop` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.support `/api/support` — 1 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-410 | `GET` | `/api/support/bundle` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/support/bundle` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.swarm `/api/swarm` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-411 | `GET` | `/api/swarm/summary` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/swarm/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sync `/api/sync` — 3 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-412 | `GET` | `/api/sync` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/sync` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-413 | `POST` | `/api/sync/pull` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-414 | `POST` | `/api/sync/push` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.system `/api/system` — 4 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-415 | `GET` | `/api/system/hardware` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/hardware` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-416 | `GET` | `/api/system/pressure` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/pressure` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-417 | `POST` | `/api/system/pressure/dismiss` | `user` | mutating — needs a body; exercise it in §01 | **401/403** with no token · state actually changes only on a valid call |
| API-418 | `GET` | `/api/system/profiles` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/profiles` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.system-map `/api/system-map` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-419 | `GET` | `/api/system-map` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system-map` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.toolrpc `/api/toolrpc` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-420 | `POST` | `/api/toolrpc/call` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-421 | `GET` | `/api/toolrpc/tools` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/toolrpc/tools` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.traces `/api/traces` — 3 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-422 | `GET` | `/api/traces` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/traces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-423 | `POST` | `/api/traces/clear` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-424 | `GET` | `/api/traces/{trace_id}` | `user` | `GET $B/api/traces/{trace_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.transcripts `/api/transcripts` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-425 | `POST` | `/api/transcripts/ingest` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.trust `/api/trust` — 1 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-426 | `GET` | `/api/trust/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/trust/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.vault `/api/vault` — 4 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-427 | `GET` | `/api/vault` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vault` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-428 | `POST` | `/api/vault` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-429 | `DELETE` | `/api/vault/{vault_id}` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-430 | `GET` | `/api/vault/{vault_id}` | `user` | `GET $B/api/vault/{vault_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.vlm `/api/vlm` — 4 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-431 | `POST` | `/api/vlm/composer/describe` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-432 | `GET` | `/api/vlm/composer/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vlm/composer/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-433 | `POST` | `/api/vlm/describe` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-434 | `GET` | `/api/vlm/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vlm/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.voice `/api/voice` — 5 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-435 | `GET` | `/api/voice/capabilities` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/voice/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-436 | `GET` | `/api/voice/listening` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/voice/listening` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-437 | `GET` | `/api/voice/listening/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/voice/listening/stream` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-438 | `POST` | `/api/voice/stt` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-439 | `GET` | `/api/voice/wyoming` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/voice/wyoming` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.webhooks `/api/webhooks` — 5 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-440 | `GET` | `/api/webhooks` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/webhooks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-441 | `POST` | `/api/webhooks` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-442 | `DELETE` | `/api/webhooks/{hook_id}` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-443 | `PATCH` | `/api/webhooks/{hook_id}` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-444 | `POST` | `/api/webhooks/{hook_id}` | `open` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.widget `/api/widget` — 3 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-445 | `GET` | `/api/widget/{token}` | `open` | `GET $B/api/widget/{token}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-446 | `GET` | `/api/widget/{token}/config` | `open` | `GET $B/api/widget/{token}/config` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-447 | `POST` | `/api/widget/{token}/message` | `open` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.workflows `/api/workflows` — 8 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-448 | `GET` | `/api/workflows` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/workflows` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-449 | `POST` | `/api/workflows` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-450 | `POST` | `/api/workflows/hierarchical` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-451 | `POST` | `/api/workflows/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-452 | `POST` | `/api/workflows/step/generate` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-453 | `GET` | `/api/workflows/traces` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/workflows/traces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-454 | `DELETE` | `/api/workflows/{pipeline_id}` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-455 | `PUT` | `/api/workflows/{pipeline_id}` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.worldview `/api/worldview` — 2 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-456 | `GET` | `/api/worldview/overview` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/worldview/overview` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-457 | `GET` | `/api/worldview/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/worldview/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.(root) `(root)` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-458 | `GET` | `/` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3..well-known `.well-known` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-459 | `GET` | `/.well-known/agent-card` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/.well-known/agent-card` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-460 | `GET` | `/.well-known/oauth-protected-resource` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/.well-known/oauth-protected-resource` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.admin `admin` — 1 routes · behaviour owned by §03 · 06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-461 | `GET` | `/admin` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/admin` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.agents `agents` — 1 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-462 | `GET` | `/agents` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/agents` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.autonomy `autonomy` — 14 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-463 | `GET` | `/autonomy/approvals` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/approvals` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-464 | `GET` | `/autonomy/brief` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/brief` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-465 | `GET` | `/autonomy/interrupts` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/interrupts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-466 | `GET` | `/autonomy/mode` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/mode` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-467 | `POST` | `/autonomy/mode` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-468 | `GET` | `/autonomy/observer` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/observer` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-469 | `POST` | `/autonomy/observer/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-470 | `GET` | `/autonomy/policy` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/policy` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-471 | `POST` | `/autonomy/policy` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-472 | `GET` | `/autonomy/preferences/suggestions` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/preferences/suggestions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-473 | `GET` | `/autonomy/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-474 | `GET` | `/autonomy/tasks` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/tasks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-475 | `POST` | `/autonomy/tasks` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-476 | `POST` | `/autonomy/tasks/{task_id}/decision` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.bench `bench` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-477 | `GET` | `/bench` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/bench` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-478 | `GET` | `/bench/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/bench/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.brain `brain` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-479 | `GET` | `/brain` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/brain` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.chat `chat` — 2 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-480 | `POST` | `/chat` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-481 | `POST` | `/chat/stream` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.dashboard `dashboard` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-482 | `GET` | `/dashboard` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/dashboard` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.docs `docs` — 2 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-483 | `GET` | `/docs` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-484 | `GET` | `/docs/oauth2-redirect` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/docs/oauth2-redirect` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.favicon.ico `favicon.ico` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-485 | `GET` | `/favicon.ico` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/favicon.ico` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.healthz `healthz` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-486 | `GET` | `/healthz` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/healthz` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.heartbeat `heartbeat` — 4 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-487 | `GET` | `/heartbeat/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/heartbeat/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-488 | `POST` | `/heartbeat/{agent_id}/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-489 | `POST` | `/heartbeat/{agent_id}/start` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-490 | `POST` | `/heartbeat/{agent_id}/stop` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.learning `learning` — 3 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-491 | `GET` | `/learning` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/learning` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-492 | `POST` | `/learning/promote` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-493 | `GET` | `/learning/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/learning/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.manifest.webmanifest `manifest.webmanifest` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-494 | `GET` | `/manifest.webmanifest` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/manifest.webmanifest` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.map `map` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-495 | `GET` | `/map` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/map` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.memory `memory` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-496 | `GET` | `/memory` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/memory` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-497 | `POST` | `/memory/clear` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-498 | `GET` | `/memory/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/memory/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-499 | `GET` | `/memory/{agent_id}` | `user` | `GET $B/memory/{agent_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.metrics `metrics` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-500 | `GET` | `/metrics` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/metrics` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.mission-control `mission-control` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-501 | `GET` | `/mission-control` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/mission-control` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.openapi.json `openapi.json` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-502 | `GET` | `/openapi.json` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/openapi.json` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.plugins `plugins` — 2 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-503 | `GET` | `/plugins` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/plugins` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-504 | `PUT` | `/plugins/{plugin_id}/toggle` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.readyz `readyz` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-505 | `GET` | `/readyz` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/readyz` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.redoc `redoc` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-506 | `GET` | `/redoc` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/redoc` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sandbox `sandbox` — 4 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-507 | `POST` | `/sandbox/execute` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-508 | `GET` | `/sandbox/kernels` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sandbox/kernels` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-509 | `POST` | `/sandbox/kernels/reset` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-510 | `GET` | `/sandbox/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sandbox/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.security `security` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-511 | `GET` | `/security` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/security` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-512 | `GET` | `/security/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/security/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sessions `sessions` — 8 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-513 | `GET` | `/sessions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sessions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-514 | `POST` | `/sessions/continue` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-515 | `POST` | `/sessions/resume` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-516 | `GET` | `/sessions/todo` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sessions/todo` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-517 | `DELETE` | `/sessions/{session_id}` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-518 | `POST` | `/sessions/{session_id}/archive` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-519 | `GET` | `/sessions/{session_id}/todo` | `user` | `GET $B/sessions/{session_id}/todo` with a real id from this group's list route | **200** with the plan for a live id · **200** with an empty list for an unknown one (no plan is kept for it) · **400** for an id that is not a session id — never a fabricated plan |
| API-520 | `POST` | `/sessions/{session_id}/unarchive` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.skills `skills` — 3 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-521 | `GET` | `/skills` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/skills` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-522 | `POST` | `/skills/import` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-523 | `GET` | `/skills/imported` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/skills/imported` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.status `status` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-524 | `GET` | `/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sw-v2.js `sw-v2.js` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-525 | `GET` | `/sw-v2.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sw-v2.js` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sw.js `sw.js` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-526 | `GET` | `/sw.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sw.js` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.tasks `tasks` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-527 | `GET` | `/tasks` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/tasks` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.ticker `ticker` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-528 | `GET` | `/ticker` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/ticker` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.tts `tts` — 2 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-529 | `POST` | `/tts` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-530 | `POST` | `/tts/stream` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.v1 `v1` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-531 | `GET` | `/v1` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v1` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.v2 `v2` — 4 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-532 | `GET` | `/v2` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-533 | `GET` | `/v2/manifest.webmanifest` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2/manifest.webmanifest` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-534 | `GET` | `/v2/sw-v2.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2/sw-v2.js` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-535 | `GET` | `/v2/{path:path}` | `open` | `GET $B/v2/{path:path}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.Z Coverage ledger

| Pass | Routes | Needs | Records |
|---|---|---|---|
| A — existence & honesty | 235 read routes | booted server | one line per non-200 |
| B — tier enforcement | ≥20 sampled + all 75 `open` | 🌐 second device | expected vs actual code per route |
| C — payload leak hunt | every `user`/`open` collection route | booted server | body excerpt per suspected leak |
| Mutating routes | 263 | see the §-pointer per group | exercised by owning section, not here |
| **Total enumerated** | **535** | — | — |

## Open gaps found while writing

- The `open` tier is the largest unaudited attack surface in the sweep (75 routes). Pass C is the only thing standing between it and a tier leak; budget real time for it rather than treating it as a formality.
- Templated read routes (`{id}` paths) are skipped by the Pass-A driver because they need a live id. They are covered by their owning sections — but that means a broken templated route can only be caught there, so do not treat a green Pass A as full read coverage.
- Mutating routes are deliberately not fired here. A sweep that POSTs blindly across 263 routes would mutate the owner's real state — the opposite of a safe manual.

*Generated by `scripts/gen_api_sweep.py` from the route snapshots at the committed revision.*
