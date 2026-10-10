# 14. API surface sweep — every route, every tier

> **Scope.** A complete, generated enumeration of the HTTP surface: **629 app routes** (the figure `project-status.json` → `routes` reports) **plus 4 FastAPI doc routes** = **633 enumerated below** — the two numbers are not a contradiction, they count different things. Across **137** groups, each with its guard tier and a copy-pasteable probe. This chapter proves a route **exists and is guarded correctly**; the *owning section* proves it **behaves correctly** — follow the §-pointer in each group heading.
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
| `user` | 292 | `user_guard` (`X-User-Token`) | 403 when `JARVIS_USER_TOKEN` is unset, 401 when set but missing/wrong |
| `admin` | 267 | `admin_guard` (`X-Admin-Token`) | must reject a user token as well as no token |
| `open` | 74 | none by design | must expose nothing tier-gated — the highest-value leak hunt in this chapter |

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

## 14.3.actions `/api/actions` — 5 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-016 | `GET` | `/api/actions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/actions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-017 | `POST` | `/api/actions/groups/{group_id}/reject` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-018 | `GET` | `/api/actions/pending` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/actions/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-019 | `POST` | `/api/actions/request` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-020 | `POST` | `/api/actions/{action_id}/decide` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.admin `/api/admin` — 50 routes · behaviour owned by §05 · 08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-021 | `GET` | `/api/admin/agents/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/agents/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-022 | `PUT` | `/api/admin/agents/{agent_id}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-023 | `POST` | `/api/admin/agents/{agent_id}/description/draft` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-024 | `PUT` | `/api/admin/agents/{agent_id}/soul` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-025 | `GET` | `/api/admin/apm` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/apm` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-026 | `GET` | `/api/admin/audit` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/audit` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-027 | `GET` | `/api/admin/backup` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/backup` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-028 | `POST` | `/api/admin/backup` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-029 | `POST` | `/api/admin/backup/verify` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-030 | `GET` | `/api/admin/env` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/env` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-031 | `GET` | `/api/admin/env/sources` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/env/sources` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-032 | `POST` | `/api/admin/export` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-033 | `POST` | `/api/admin/forget` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-034 | `GET` | `/api/admin/inspector` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/inspector` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-035 | `POST` | `/api/admin/llm/providers/probe` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-036 | `POST` | `/api/admin/llm/test` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-037 | `GET` | `/api/admin/logs` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/logs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-038 | `GET` | `/api/admin/mcp` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/mcp` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-039 | `POST` | `/api/admin/mcp` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-040 | `DELETE` | `/api/admin/mcp/{name}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-041 | `POST` | `/api/admin/mcp/{name}/connect` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-042 | `POST` | `/api/admin/mcp/{name}/disconnect` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-043 | `POST` | `/api/admin/memory/clear` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-044 | `GET` | `/api/admin/network/calls` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/network/calls` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-045 | `GET` | `/api/admin/prompts/{agent_id}/ab` | `admin` | `GET $B/api/admin/prompts/{agent_id}/ab` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-046 | `POST` | `/api/admin/prompts/{agent_id}/ab` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-047 | `POST` | `/api/admin/prompts/{agent_id}/commit` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-048 | `GET` | `/api/admin/prompts/{agent_id}/diff` | `admin` | `GET $B/api/admin/prompts/{agent_id}/diff` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-049 | `GET` | `/api/admin/prompts/{agent_id}/history` | `admin` | `GET $B/api/admin/prompts/{agent_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-050 | `POST` | `/api/admin/prompts/{agent_id}/preview` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-051 | `POST` | `/api/admin/prompts/{agent_id}/rollback` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-052 | `GET` | `/api/admin/prompts/{agent_id}/version/{version}` | `admin` | `GET $B/api/admin/prompts/{agent_id}/version/{version}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-053 | `GET` | `/api/admin/retention` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/retention` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-054 | `POST` | `/api/admin/rotate-tokens` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-055 | `GET` | `/api/admin/settings` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/settings` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-056 | `GET` | `/api/admin/settings/export` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/settings/export` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-057 | `POST` | `/api/admin/settings/import` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-058 | `POST` | `/api/admin/settings/reseed` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-059 | `GET` | `/api/admin/settings/resets` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/settings/resets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-060 | `POST` | `/api/admin/settings/undo` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-061 | `GET` | `/api/admin/settings/{category}` | `admin` | `GET $B/api/admin/settings/{category}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-062 | `PUT` | `/api/admin/settings/{category}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-063 | `POST` | `/api/admin/settings/{category}/reset` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-064 | `GET` | `/api/admin/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-065 | `GET` | `/api/admin/tool-events` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/tool-events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-066 | `GET` | `/api/admin/voice/commands` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/voice/commands` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-067 | `POST` | `/api/admin/voice/commands` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-068 | `GET` | `/api/admin/widgets` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/widgets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-069 | `POST` | `/api/admin/widgets` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-070 | `DELETE` | `/api/admin/widgets/{token}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.agent-templates `/api/agent-templates` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-071 | `GET` | `/api/agent-templates` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/agent-templates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-072 | `POST` | `/api/agent-templates/instantiate` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.agents `/api/agents` — 4 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-073 | `GET` | `/api/agents` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/agents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-074 | `GET` | `/api/agents/history` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/agents/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-075 | `GET` | `/api/agents/{agent_id}/history` | `user` | `GET $B/api/agents/{agent_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-076 | `GET` | `/api/agents/{agent_id}/soul` | `user` | `GET $B/api/agents/{agent_id}/soul` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.ambient `/api/ambient` — 4 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-077 | `GET` | `/api/ambient/monitors` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ambient/monitors` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-078 | `POST` | `/api/ambient/monitors` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-079 | `DELETE` | `/api/ambient/monitors/{monitor_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-080 | `PUT` | `/api/ambient/monitors/{monitor_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.analytics `/api/analytics` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-081 | `GET` | `/api/analytics/cost` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/cost` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-082 | `POST` | `/api/analytics/event` | `open` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-083 | `GET` | `/api/analytics/locality` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/locality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-084 | `GET` | `/api/analytics/model-tiers` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/model-tiers` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.arena `/api/arena` — 4 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-085 | `GET` | `/api/arena/leaderboard` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/arena/leaderboard` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-086 | `GET` | `/api/arena/match/{match_id}` | `user` | `GET $B/api/arena/match/{match_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-087 | `POST` | `/api/arena/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-088 | `POST` | `/api/arena/vote` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.artifacts `/api/artifacts` — 5 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-089 | `GET` | `/api/artifacts` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/artifacts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-090 | `POST` | `/api/artifacts` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-091 | `DELETE` | `/api/artifacts/{artifact_id}` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-092 | `GET` | `/api/artifacts/{artifact_id}/blob` | `user` | `GET $B/api/artifacts/{artifact_id}/blob` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-093 | `POST` | `/api/artifacts/{artifact_id}/pin` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.autonomy `/api/autonomy` — 6 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-094 | `POST` | `/api/autonomy/call` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-095 | `POST` | `/api/autonomy/escalate` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-096 | `GET` | `/api/autonomy/escalation/targets` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/autonomy/escalation/targets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-097 | `POST` | `/api/autonomy/kanban/dispatch` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-098 | `POST` | `/api/autonomy/preview` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-099 | `GET` | `/api/autonomy/tasks/{task_id}/preview` | `admin` | `GET $B/api/autonomy/tasks/{task_id}/preview` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.brain `/api/brain` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-100 | `GET` | `/api/brain/summary` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/brain/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.browser `/api/browser` — 2 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-101 | `POST` | `/api/browser/check` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-102 | `POST` | `/api/browser/plan/preview` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.cameras `/api/cameras` — 4 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-103 | `GET` | `/api/cameras/events` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cameras/events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-104 | `POST` | `/api/cameras/onvif/discover` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-105 | `POST` | `/api/cameras/search` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-106 | `GET` | `/api/cameras/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cameras/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.canvas `/api/canvas` — 6 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-107 | `GET` | `/api/canvas` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/canvas` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-108 | `POST` | `/api/canvas/clear` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-109 | `GET` | `/api/canvas/pointers` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/canvas/pointers` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-110 | `POST` | `/api/canvas/post` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-111 | `DELETE` | `/api/canvas/{el_id}` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-112 | `POST` | `/api/canvas/{el_id}/pin` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.capabilities `/api/capabilities` — 1 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-113 | `GET` | `/api/capabilities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.capture `/api/capture` — 7 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-114 | `GET` | `/api/capture` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-115 | `POST` | `/api/capture/clear` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-116 | `GET` | `/api/capture/export` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture/export` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-117 | `POST` | `/api/capture/ingest` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-118 | `GET` | `/api/capture/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-119 | `POST` | `/api/capture/surfaces` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-120 | `DELETE` | `/api/capture/{rec_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.channels `/api/channels` — 15 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-121 | `GET` | `/api/channels/inbox` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/inbox` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-122 | `GET` | `/api/channels/inbox/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/inbox/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-123 | `GET` | `/api/channels/inbox/{thread_id}` | `user` | `GET $B/api/channels/inbox/{thread_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-124 | `POST` | `/api/channels/inbox/{thread_id}/reply` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-125 | `GET` | `/api/channels/pairing` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/pairing` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-126 | `POST` | `/api/channels/pairing/code` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-127 | `POST` | `/api/channels/pairing/decide` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-128 | `POST` | `/api/channels/pairing/link` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-129 | `POST` | `/api/channels/pairing/link/revoke` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-130 | `POST` | `/api/channels/pairing/request` | `open` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-131 | `POST` | `/api/channels/send` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-132 | `GET` | `/api/channels/send-rate-limit` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/send-rate-limit` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-133 | `GET` | `/api/channels/targets` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/targets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-134 | `GET` | `/api/channels/webhook` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/webhook` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-135 | `POST` | `/api/channels/{channel_id}/inbound` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.coach `/api/coach` — 3 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-136 | `POST` | `/api/coach/curriculum` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-137 | `POST` | `/api/coach/review` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-138 | `POST` | `/api/coach/session` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.codeintel `/api/codeintel` — 3 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-139 | `POST` | `/api/codeintel/reindex` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-140 | `GET` | `/api/codeintel/search` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/codeintel/search` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-141 | `GET` | `/api/codeintel/stats` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/codeintel/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.cognition `/api/cognition` — 8 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-142 | `GET` | `/api/cognition` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-143 | `GET` | `/api/cognition/ensemble` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/ensemble` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-144 | `GET` | `/api/cognition/honesty` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/honesty` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-145 | `GET` | `/api/cognition/learning` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/learning` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-146 | `GET` | `/api/cognition/memory` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/memory` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-147 | `GET` | `/api/cognition/personality` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/personality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-148 | `GET` | `/api/cognition/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-149 | `GET` | `/api/cognition/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/stream` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.commands `/api/commands` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-150 | `GET` | `/api/commands` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/commands` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.company `/api/company` — 5 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-151 | `GET` | `/api/company/runs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/company/runs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-152 | `GET` | `/api/company/runs/{run_id}` | `user` | `GET $B/api/company/runs/{run_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-153 | `POST` | `/api/company/runs/{run_id}/barrier/clear` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-154 | `POST` | `/api/company/runs/{run_id}/stop` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-155 | `GET` | `/api/company/waiting` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/company/waiting` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.context `/api/context` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-156 | `POST` | `/api/context/compress` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.context-refs `/api/context-refs` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-157 | `GET` | `/api/context-refs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/context-refs` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.cost `/api/cost` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-158 | `GET` | `/api/cost` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cost` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.creative `/api/creative` — 4 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-159 | `POST` | `/api/creative/export-packs` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-160 | `POST` | `/api/creative/plan` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-161 | `POST` | `/api/creative/publish/checklist` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-162 | `POST` | `/api/creative/publish/package` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.dashboard `/api/dashboard` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-163 | `GET` | `/api/dashboard/today` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/dashboard/today` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.design-manifest `/api/design-manifest` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-164 | `GET` | `/api/design-manifest` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/design-manifest` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.desktop `/api/desktop` — 4 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-165 | `GET` | `/api/desktop/allowlist` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/desktop/allowlist` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-166 | `POST` | `/api/desktop/plan` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-167 | `POST` | `/api/desktop/preview` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-168 | `POST` | `/api/desktop/run` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.digest `/api/digest` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-169 | `POST` | `/api/digest/run` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.eval `/api/eval` — 4 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-170 | `GET` | `/api/eval/datasets` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/eval/datasets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-171 | `POST` | `/api/eval/datasets/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-172 | `GET` | `/api/eval/datasets/{name}/compare` | `open` | `GET $B/api/eval/datasets/{name}/compare` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-173 | `GET` | `/api/eval/datasets/{name}/runs` | `open` | `GET $B/api/eval/datasets/{name}/runs` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.feedback `/api/feedback` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-174 | `POST` | `/api/feedback` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-175 | `GET` | `/api/feedback/summary` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/feedback/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.health `/api/health` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-176 | `GET` | `/api/health/components` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/health/components` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.help `/api/help` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-177 | `GET` | `/api/help/docs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/help/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-178 | `GET` | `/api/help/docs/{slug}` | `user` | `GET $B/api/help/docs/{slug}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.hermes `/api/hermes` — 7 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-179 | `GET` | `/api/hermes/approvals` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/hermes/approvals` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-180 | `POST` | `/api/hermes/approvals/{task_id}/decision` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-181 | `GET` | `/api/hermes/catalog` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/hermes/catalog` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-182 | `POST` | `/api/hermes/rpc` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-183 | `POST` | `/api/hermes/start` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-184 | `GET` | `/api/hermes/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/hermes/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-185 | `POST` | `/api/hermes/stop` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.host `/api/host` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-186 | `GET` | `/api/host/probe` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/host/probe` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.house `/api/house` — 7 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-187 | `POST` | `/api/house/control/climate` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-188 | `POST` | `/api/house/control/light` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-189 | `POST` | `/api/house/control/security` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-190 | `POST` | `/api/house/presence/explain` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-191 | `POST` | `/api/house/security/{task_id}/challenge` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-192 | `POST` | `/api/house/security/{task_id}/confirm` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-193 | `GET` | `/api/house/state` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/house/state` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.ingestion `/api/ingestion` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-194 | `GET` | `/api/ingestion/provenance` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ingestion/provenance` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.integrations `/api/integrations` — 4 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-195 | `GET` | `/api/integrations/social` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/integrations/social` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-196 | `POST` | `/api/integrations/social` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-197 | `GET` | `/api/integrations/writeback` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/integrations/writeback` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-198 | `POST` | `/api/integrations/writeback` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.jobs `/api/jobs` — 20 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-199 | `GET` | `/api/jobs` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-200 | `POST` | `/api/jobs` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-201 | `GET` | `/api/jobs/blueprints` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/blueprints` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-202 | `GET` | `/api/jobs/doctor` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/doctor` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-203 | `GET` | `/api/jobs/incidents` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/incidents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-204 | `POST` | `/api/jobs/incidents/{incident_id}/ack` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-205 | `GET` | `/api/jobs/runs` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/jobs/runs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-206 | `POST` | `/api/jobs/tick` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-207 | `DELETE` | `/api/jobs/{job_id}` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-208 | `GET` | `/api/jobs/{job_id}` | `admin` | `GET $B/api/jobs/{job_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-209 | `PATCH` | `/api/jobs/{job_id}` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-210 | `PUT` | `/api/jobs/{job_id}/notepad` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-211 | `DELETE` | `/api/jobs/{job_id}/notepad/keys` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-212 | `GET` | `/api/jobs/{job_id}/notepad/keys` | `admin` | `GET $B/api/jobs/{job_id}/notepad/keys` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-213 | `PUT` | `/api/jobs/{job_id}/notepad/keys` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-214 | `POST` | `/api/jobs/{job_id}/pause` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-215 | `GET` | `/api/jobs/{job_id}/requests/{request_id}` | `admin` | `GET $B/api/jobs/{job_id}/requests/{request_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-216 | `POST` | `/api/jobs/{job_id}/resume` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-217 | `POST` | `/api/jobs/{job_id}/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-218 | `GET` | `/api/jobs/{job_id}/runs` | `admin` | `GET $B/api/jobs/{job_id}/runs` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.kanban `/api/kanban` — 48 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-219 | `GET` | `/api/kanban/assignees` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/assignees` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-220 | `DELETE` | `/api/kanban/attachments/{attachment_id}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-221 | `GET` | `/api/kanban/attachments/{attachment_id}` | `admin` | `GET $B/api/kanban/attachments/{attachment_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-222 | `GET` | `/api/kanban/board` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/board` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-223 | `GET` | `/api/kanban/boards` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/boards` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-224 | `POST` | `/api/kanban/boards` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-225 | `POST` | `/api/kanban/boards/import` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-226 | `DELETE` | `/api/kanban/boards/{slug}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-227 | `PATCH` | `/api/kanban/boards/{slug}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-228 | `POST` | `/api/kanban/boards/{slug}/export` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-229 | `POST` | `/api/kanban/boards/{slug}/switch` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-230 | `POST` | `/api/kanban/command` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-231 | `GET` | `/api/kanban/config` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/config` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-232 | `GET` | `/api/kanban/diagnostics` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/diagnostics` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-233 | `POST` | `/api/kanban/dispatch` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-234 | `POST` | `/api/kanban/estimate` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-235 | `GET` | `/api/kanban/home-channels` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/home-channels` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-236 | `DELETE` | `/api/kanban/links` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-237 | `POST` | `/api/kanban/links` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-238 | `GET` | `/api/kanban/model-options` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/model-options` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-239 | `GET` | `/api/kanban/orchestration` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/orchestration` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-240 | `PUT` | `/api/kanban/orchestration` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-241 | `GET` | `/api/kanban/profiles` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/profiles` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-242 | `PATCH` | `/api/kanban/profiles/{profile_name}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-243 | `POST` | `/api/kanban/profiles/{profile_name}/describe-auto` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-244 | `GET` | `/api/kanban/projects` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/projects` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-245 | `POST` | `/api/kanban/projects/command` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-246 | `GET` | `/api/kanban/runs/{run_id}` | `admin` | `GET $B/api/kanban/runs/{run_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-247 | `GET` | `/api/kanban/runs/{run_id}/inspect` | `admin` | `GET $B/api/kanban/runs/{run_id}/inspect` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-248 | `POST` | `/api/kanban/runs/{run_id}/terminate` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-249 | `GET` | `/api/kanban/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-250 | `POST` | `/api/kanban/tasks` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-251 | `POST` | `/api/kanban/tasks/bulk` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-252 | `DELETE` | `/api/kanban/tasks/{task_id}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-253 | `GET` | `/api/kanban/tasks/{task_id}` | `admin` | `GET $B/api/kanban/tasks/{task_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-254 | `PATCH` | `/api/kanban/tasks/{task_id}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-255 | `GET` | `/api/kanban/tasks/{task_id}/attachments` | `admin` | `GET $B/api/kanban/tasks/{task_id}/attachments` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-256 | `POST` | `/api/kanban/tasks/{task_id}/attachments` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-257 | `POST` | `/api/kanban/tasks/{task_id}/comments` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-258 | `POST` | `/api/kanban/tasks/{task_id}/decompose` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-259 | `POST` | `/api/kanban/tasks/{task_id}/estimate` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-260 | `DELETE` | `/api/kanban/tasks/{task_id}/home-subscribe/{platform}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-261 | `POST` | `/api/kanban/tasks/{task_id}/home-subscribe/{platform}` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-262 | `GET` | `/api/kanban/tasks/{task_id}/log` | `admin` | `GET $B/api/kanban/tasks/{task_id}/log` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-263 | `POST` | `/api/kanban/tasks/{task_id}/reassign` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-264 | `POST` | `/api/kanban/tasks/{task_id}/reclaim` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-265 | `POST` | `/api/kanban/tasks/{task_id}/specify` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-266 | `GET` | `/api/kanban/workers/active` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kanban/workers/active` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.kg `/api/kg` — 10 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-267 | `GET` | `/api/kg/entities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/entities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-268 | `POST` | `/api/kg/entities` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-269 | `DELETE` | `/api/kg/entities/{name}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-270 | `GET` | `/api/kg/entities/{name}` | `user` | `GET $B/api/kg/entities/{name}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-271 | `POST` | `/api/kg/facts` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-272 | `GET` | `/api/kg/facts/as-of` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/facts/as-of` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-273 | `GET` | `/api/kg/facts/history` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/facts/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-274 | `POST` | `/api/kg/ingest` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-275 | `DELETE` | `/api/kg/relations` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-276 | `POST` | `/api/kg/relations` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.learning `/api/learning` — 2 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-277 | `POST` | `/api/learning/evolve` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-278 | `POST` | `/api/learning/propose` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.llm `/api/llm` — 10 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-279 | `GET` | `/api/llm/auth-profiles` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/auth-profiles` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-280 | `POST` | `/api/llm/grammar` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-281 | `POST` | `/api/llm/load` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-282 | `POST` | `/api/llm/moe/route` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-283 | `POST` | `/api/llm/openrouter` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-284 | `GET` | `/api/llm/quota` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/quota` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-285 | `GET` | `/api/llm/roles` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/roles` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-286 | `POST` | `/api/llm/server/start` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-287 | `GET` | `/api/llm/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-288 | `POST` | `/api/llm/unload` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.local-docs `/api/local-docs` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-289 | `GET` | `/api/local-docs` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/local-docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-290 | `POST` | `/api/local-docs/index` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.market `/api/market` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-291 | `POST` | `/api/market/brief` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-292 | `POST` | `/api/market/watchlist` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-293 | `GET` | `/api/market/watchlist/saved` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/market/watchlist/saved` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-294 | `POST` | `/api/market/watchlist/saved` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-295 | `DELETE` | `/api/market/watchlist/saved/{symbol}` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.mcp `/api/mcp` — 3 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-296 | `GET` | `/api/mcp/server` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/mcp/server` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-297 | `POST` | `/api/mcp/server/rpc` | `open` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-298 | `POST` | `/api/mcp/token` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.media `/api/media` — 12 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-299 | `GET` | `/api/media` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-300 | `GET` | `/api/media/catalog` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/catalog` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-301 | `GET` | `/api/media/devices` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/devices` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-302 | `POST` | `/api/media/devices` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-303 | `DELETE` | `/api/media/devices/{device_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-304 | `POST` | `/api/media/export` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-305 | `POST` | `/api/media/generate` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-306 | `GET` | `/api/media/generated/{artifact_id}` | `user` | `GET $B/api/media/generated/{artifact_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-307 | `GET` | `/api/media/generation-tasks/{task_id}` | `admin` | `GET $B/api/media/generation-tasks/{task_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-308 | `POST` | `/api/media/present` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-309 | `POST` | `/api/media/restore/{device_id}` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-310 | `GET` | `/api/media/session` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/session` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.memory `/api/memory` — 22 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-311 | `POST` | `/api/memory/consolidate` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-312 | `POST` | `/api/memory/consolidate/apply` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-313 | `GET` | `/api/memory/consolidate/preview` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/consolidate/preview` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-314 | `GET` | `/api/memory/core` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/core` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-315 | `POST` | `/api/memory/core/undo` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-316 | `GET` | `/api/memory/decay/candidates` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/decay/candidates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-317 | `POST` | `/api/memory/decay/forget` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-318 | `GET` | `/api/memory/decay/ranking` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/decay/ranking` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-319 | `GET` | `/api/memory/entities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/entities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-320 | `GET` | `/api/memory/eval/corpus` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/memory/eval/corpus` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-321 | `POST` | `/api/memory/eval/run` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-322 | `GET` | `/api/memory/profile` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/profile` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-323 | `GET` | `/api/memory/recall` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/recall` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-324 | `POST` | `/api/memory/remember` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-325 | `GET` | `/api/memory/search` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/search` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-326 | `POST` | `/api/memory/search-tool` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-327 | `GET` | `/api/memory/spaces` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/spaces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-328 | `POST` | `/api/memory/spaces` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-329 | `POST` | `/api/memory/spaces/assign` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-330 | `POST` | `/api/memory/spaces/unassign` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-331 | `DELETE` | `/api/memory/spaces/{name}` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-332 | `GET` | `/api/memory/tool-spec` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/memory/tool-spec` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.metrics `/api/metrics` — 3 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-333 | `GET` | `/api/metrics/capabilities` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-334 | `GET` | `/api/metrics/kernel` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/kernel` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-335 | `GET` | `/api/metrics/north-star` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/north-star` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.missions `/api/missions` — 9 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-336 | `GET` | `/api/missions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/missions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-337 | `POST` | `/api/missions` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-338 | `GET` | `/api/missions/{mission_id}` | `user` | `GET $B/api/missions/{mission_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-339 | `POST` | `/api/missions/{mission_id}/cancel` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-340 | `POST` | `/api/missions/{mission_id}/complete` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-341 | `POST` | `/api/missions/{mission_id}/pause` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-342 | `POST` | `/api/missions/{mission_id}/resume` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-343 | `POST` | `/api/missions/{mission_id}/start` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-344 | `POST` | `/api/missions/{mission_id}/steps/{idx}/finish` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.models `/api/models` — 3 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-345 | `GET` | `/api/models/info` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/models/info` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-346 | `GET` | `/api/models/local` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/models/local` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-347 | `POST` | `/api/models/local/switch` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.nodes `/api/nodes` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-348 | `GET` | `/api/nodes` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/nodes` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-349 | `POST` | `/api/nodes/register` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-350 | `DELETE` | `/api/nodes/{node_id}` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-351 | `POST` | `/api/nodes/{node_id}/dispatch` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.notes `/api/notes` — 11 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-352 | `DELETE` | `/api/notes` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-353 | `GET` | `/api/notes` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/notes` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-354 | `PUT` | `/api/notes` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-355 | `DELETE` | `/api/notes/blocks/{block_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-356 | `PATCH` | `/api/notes/blocks/{block_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-357 | `GET` | `/api/notes/docs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/notes/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-358 | `POST` | `/api/notes/docs` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-359 | `DELETE` | `/api/notes/docs/{doc_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-360 | `GET` | `/api/notes/docs/{doc_id}` | `user` | `GET $B/api/notes/docs/{doc_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-361 | `POST` | `/api/notes/docs/{doc_id}/blocks` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-362 | `POST` | `/api/notes/rewrite` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.oauth `/api/oauth` — 8 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-363 | `GET` | `/api/oauth/auth-url` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oauth/auth-url` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-364 | `POST` | `/api/oauth/callback` | `open` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-365 | `POST` | `/api/oauth/nous/login` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-366 | `POST` | `/api/oauth/nous/logout` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-367 | `POST` | `/api/oauth/nous/poll` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-368 | `GET` | `/api/oauth/nous/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/oauth/nous/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-369 | `POST` | `/api/oauth/refresh` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-370 | `GET` | `/api/oauth/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oauth/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.onboarding `/api/onboarding` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-371 | `GET` | `/api/onboarding/command-center` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/command-center` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-372 | `POST` | `/api/onboarding/funnel` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-373 | `GET` | `/api/onboarding/model-plan` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/model-plan` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-374 | `POST` | `/api/onboarding/model-pull` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-375 | `GET` | `/api/onboarding/wizard` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/wizard` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.operator `/api/operator` — 3 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-376 | `GET` | `/api/operator/benchmark` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/operator/benchmark` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-377 | `GET` | `/api/operator/benchmark/pack` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/operator/benchmark/pack` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-378 | `POST` | `/api/operator/plan` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.ops `/api/ops` — 3 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-379 | `GET` | `/api/ops/estop` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ops/estop` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-380 | `POST` | `/api/ops/estop/engage` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-381 | `POST` | `/api/ops/estop/resume` | `admin` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.oracle `/api/oracle` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-382 | `GET` | `/api/oracle/conflicts` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/oracle/conflicts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-383 | `POST` | `/api/oracle/conflicts/resolve` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-384 | `GET` | `/api/oracle/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oracle/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-385 | `POST` | `/api/oracle/sync` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.osint `/api/osint` — 2 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-386 | `POST` | `/api/osint/brief` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-387 | `POST` | `/api/osint/correlate` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.packs `/api/packs` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-388 | `GET` | `/api/packs` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/packs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-389 | `GET` | `/api/packs/{key}/verify` | `user` | `GET $B/api/packs/{key}/verify` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.payments `/api/payments` — 7 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-390 | `GET` | `/api/payments` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/payments` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-391 | `GET` | `/api/payments/mandates` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/payments/mandates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-392 | `POST` | `/api/payments/mandates` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-393 | `POST` | `/api/payments/request` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-394 | `POST` | `/api/payments/{payment_id}/approve` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-395 | `POST` | `/api/payments/{payment_id}/reject` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-396 | `POST` | `/api/payments/{payment_id}/settle` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.permissions `/api/permissions` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-397 | `GET` | `/api/permissions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/permissions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-398 | `POST` | `/api/permissions/{grant_id}/revoke` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.plugins `/api/plugins` — 3 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-399 | `GET` | `/api/plugins/extensions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/plugins/extensions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-400 | `POST` | `/api/plugins/extensions/activate` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-401 | `POST` | `/api/plugins/extensions/consent` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.power `/api/power` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-402 | `GET` | `/api/power` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/power` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-403 | `GET` | `/api/power/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/power/stream` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.preferences `/api/preferences` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-404 | `GET` | `/api/preferences/appearance` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/preferences/appearance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-405 | `PUT` | `/api/preferences/appearance` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.presence `/api/presence` — 2 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-406 | `GET` | `/api/presence/owner` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/presence/owner` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-407 | `POST` | `/api/presence/owner` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.quality `/api/quality` — 3 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-408 | `GET` | `/api/quality` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/quality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-409 | `GET` | `/api/quality/scores` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/quality/scores` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-410 | `POST` | `/api/quality/threshold` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.quickbar `/api/quickbar` — 2 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-411 | `GET` | `/api/quickbar/help` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/quickbar/help` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-412 | `POST` | `/api/quickbar/resolve` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.reflection `/api/reflection` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-413 | `POST` | `/api/reflection/run` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-414 | `GET` | `/api/reflection/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/reflection/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.report `/api/report` — 3 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-415 | `GET` | `/api/report/receipt/{audit_id}` | `user` | `GET $B/api/report/receipt/{audit_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-416 | `GET` | `/api/report/today` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/report/today` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-417 | `POST` | `/api/report/today/export` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.resilience `/api/resilience` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-418 | `GET` | `/api/resilience` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/resilience` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.review `/api/review` — 5 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-419 | `POST` | `/api/review/flag` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-420 | `GET` | `/api/review/queue` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/review/queue` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-421 | `GET` | `/api/review/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/review/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-422 | `POST` | `/api/review/{item_id}/dataset` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-423 | `POST` | `/api/review/{item_id}/vote` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.rooms `/api/rooms` — 6 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-424 | `GET` | `/api/rooms` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/rooms` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-425 | `POST` | `/api/rooms` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-426 | `DELETE` | `/api/rooms/{room_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-427 | `GET` | `/api/rooms/{room_id}` | `user` | `GET $B/api/rooms/{room_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-428 | `GET` | `/api/rooms/{room_id}/history` | `user` | `GET $B/api/rooms/{room_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-429 | `POST` | `/api/rooms/{room_id}/message` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.satellites `/api/satellites` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-430 | `GET` | `/api/satellites` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/satellites` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-431 | `POST` | `/api/satellites/register` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-432 | `DELETE` | `/api/satellites/{satellite_id}` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-433 | `POST` | `/api/satellites/{satellite_id}/dispatch` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.schedule `/api/schedule` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-434 | `POST` | `/api/schedule/parse` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.screen `/api/screen` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-435 | `POST` | `/api/screen/reflex` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |

## 14.3.secrets `/api/secrets` — 4 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-436 | `GET` | `/api/secrets/broker` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/secrets/broker` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-437 | `POST` | `/api/secrets/broker` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-438 | `POST` | `/api/secrets/broker/redact` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-439 | `DELETE` | `/api/secrets/broker/{name}` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.security `/api/security` — 16 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-440 | `POST` | `/api/security/audit/action` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-441 | `POST` | `/api/security/audit/anchor` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-442 | `GET` | `/api/security/audit/anchors` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/anchors` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-443 | `GET` | `/api/security/audit/intent` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/intent` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-444 | `GET` | `/api/security/audit/verify` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/verify` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-445 | `GET` | `/api/security/capabilities/check` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/capabilities/check` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-446 | `POST` | `/api/security/capabilities/issue` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-447 | `POST` | `/api/security/data-handling/ack` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-448 | `GET` | `/api/security/governance` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/governance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-449 | `GET` | `/api/security/kill-switch` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/kill-switch` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-450 | `POST` | `/api/security/kill-switch` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-451 | `GET` | `/api/security/loop-breaker` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/loop-breaker` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-452 | `POST` | `/api/security/loop-breaker/reset` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-453 | `GET` | `/api/security/posture` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/posture` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-454 | `POST` | `/api/security/scan-injection` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-455 | `POST` | `/api/security/spotlight` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.security-skills `/api/security-skills` — 6 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-456 | `GET` | `/api/security-skills/frameworks` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/frameworks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-457 | `POST` | `/api/security-skills/map` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-458 | `POST` | `/api/security-skills/playbook` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-459 | `GET` | `/api/security-skills/tactics` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/tactics` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-460 | `GET` | `/api/security-skills/technique/{tid}` | `user` | `GET $B/api/security-skills/technique/{tid}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-461 | `GET` | `/api/security-skills/techniques` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/techniques` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.self-improvement `/api/self-improvement` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-462 | `POST` | `/api/self-improvement/enable` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-463 | `GET` | `/api/self-improvement/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/self-improvement/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.signals `/api/signals` — 5 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-464 | `GET` | `/api/signals/agent/{agent_id}` | `user` | `GET $B/api/signals/agent/{agent_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-465 | `GET` | `/api/signals/brief/{domain}` | `user` | `GET $B/api/signals/brief/{domain}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-466 | `GET` | `/api/signals/governance` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/signals/governance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-467 | `POST` | `/api/signals/governance/submit` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-468 | `GET` | `/api/signals/routed` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/signals/routed` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.skills `/api/skills` — 12 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-469 | `GET` | `/api/skills/marketplace` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/marketplace` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-470 | `GET` | `/api/skills/marketplace/history` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/marketplace/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-471 | `POST` | `/api/skills/marketplace/install` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-472 | `POST` | `/api/skills/marketplace/install-zip` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-473 | `POST` | `/api/skills/marketplace/publish` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-474 | `POST` | `/api/skills/marketplace/review` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-475 | `POST` | `/api/skills/marketplace/uninstall` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-476 | `POST` | `/api/skills/marketplace/{name}/rollback` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-477 | `GET` | `/api/skills/pending` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-478 | `GET` | `/api/skills/proposals` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/proposals` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-479 | `POST` | `/api/skills/switch` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-480 | `POST` | `/api/skills/{name}/approve` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.status `/api/status` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-481 | `GET` | `/api/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.subagents `/api/subagents` — 5 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-482 | `GET` | `/api/subagents` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/subagents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-483 | `POST` | `/api/subagents/batch` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-484 | `POST` | `/api/subagents/spawn` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-485 | `POST` | `/api/subagents/{spawn_id}/steer` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-486 | `POST` | `/api/subagents/{spawn_id}/stop` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.support `/api/support` — 1 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-487 | `GET` | `/api/support/bundle` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/support/bundle` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.swarm `/api/swarm` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-488 | `GET` | `/api/swarm/summary` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/swarm/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sync `/api/sync` — 3 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-489 | `GET` | `/api/sync` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/sync` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-490 | `POST` | `/api/sync/pull` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-491 | `POST` | `/api/sync/push` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.system `/api/system` — 4 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-492 | `GET` | `/api/system/hardware` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/hardware` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-493 | `GET` | `/api/system/pressure` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/pressure` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-494 | `POST` | `/api/system/pressure/dismiss` | `user` | mutating — needs a body; exercise it in §01 | **401/403** with no token · state actually changes only on a valid call |
| API-495 | `GET` | `/api/system/profiles` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/profiles` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.system-map `/api/system-map` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-496 | `GET` | `/api/system-map` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system-map` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.toolrpc `/api/toolrpc` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-497 | `POST` | `/api/toolrpc/call` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-498 | `GET` | `/api/toolrpc/tools` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/toolrpc/tools` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.traces `/api/traces` — 3 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-499 | `GET` | `/api/traces` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/traces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-500 | `POST` | `/api/traces/clear` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-501 | `GET` | `/api/traces/{trace_id}` | `user` | `GET $B/api/traces/{trace_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.transcripts `/api/transcripts` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-502 | `POST` | `/api/transcripts/ingest` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.trust `/api/trust` — 1 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-503 | `GET` | `/api/trust/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/trust/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.vault `/api/vault` — 4 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-504 | `GET` | `/api/vault` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vault` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-505 | `POST` | `/api/vault` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-506 | `DELETE` | `/api/vault/{vault_id}` | `user` | mutating — needs a body; exercise it in §— | **401/403** with no token · state actually changes only on a valid call |
| API-507 | `GET` | `/api/vault/{vault_id}` | `user` | `GET $B/api/vault/{vault_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.vlm `/api/vlm` — 10 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-508 | `GET` | `/api/vlm/composer/active-images` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vlm/composer/active-images` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-509 | `POST` | `/api/vlm/composer/chat-prepared` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-510 | `POST` | `/api/vlm/composer/describe` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-511 | `POST` | `/api/vlm/composer/describe-prepared` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-512 | `POST` | `/api/vlm/composer/prepare` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-513 | `POST` | `/api/vlm/composer/selected-chat` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-514 | `POST` | `/api/vlm/composer/selected-prepare` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-515 | `GET` | `/api/vlm/composer/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vlm/composer/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-516 | `POST` | `/api/vlm/describe` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-517 | `GET` | `/api/vlm/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vlm/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.voice `/api/voice` — 10 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-518 | `GET` | `/api/voice/capabilities` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/voice/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-519 | `GET` | `/api/voice/listening` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/voice/listening` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-520 | `GET` | `/api/voice/listening/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/voice/listening/stream` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-521 | `GET` | `/api/voice/mic` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/voice/mic` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-522 | `POST` | `/api/voice/mic/arm` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-523 | `POST` | `/api/voice/mic/pause` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-524 | `POST` | `/api/voice/mic/resume` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-525 | `POST` | `/api/voice/mic/stop` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-526 | `POST` | `/api/voice/stt` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-527 | `GET` | `/api/voice/wyoming` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/voice/wyoming` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.webhooks `/api/webhooks` — 5 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-528 | `GET` | `/api/webhooks` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/webhooks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-529 | `POST` | `/api/webhooks` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-530 | `DELETE` | `/api/webhooks/{hook_id}` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-531 | `PATCH` | `/api/webhooks/{hook_id}` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-532 | `POST` | `/api/webhooks/{hook_id}` | `open` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.widget `/api/widget` — 3 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-533 | `GET` | `/api/widget/{token}` | `open` | `GET $B/api/widget/{token}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-534 | `GET` | `/api/widget/{token}/config` | `open` | `GET $B/api/widget/{token}/config` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-535 | `POST` | `/api/widget/{token}/message` | `open` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.workflows `/api/workflows` — 8 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-536 | `GET` | `/api/workflows` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/workflows` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-537 | `POST` | `/api/workflows` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-538 | `POST` | `/api/workflows/hierarchical` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-539 | `POST` | `/api/workflows/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-540 | `POST` | `/api/workflows/step/generate` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-541 | `GET` | `/api/workflows/traces` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/workflows/traces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-542 | `DELETE` | `/api/workflows/{pipeline_id}` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-543 | `PUT` | `/api/workflows/{pipeline_id}` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.worldview `/api/worldview` — 2 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-544 | `GET` | `/api/worldview/overview` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/worldview/overview` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-545 | `GET` | `/api/worldview/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/worldview/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.(root) `(root)` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-546 | `GET` | `/` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3..well-known `.well-known` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-547 | `GET` | `/.well-known/agent-card` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/.well-known/agent-card` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-548 | `GET` | `/.well-known/oauth-protected-resource` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/.well-known/oauth-protected-resource` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.admin `admin` — 1 routes · behaviour owned by §03 · 06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-549 | `GET` | `/admin` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/admin` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.agents `agents` — 1 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-550 | `GET` | `/agents` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/agents` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.autonomy `autonomy` — 17 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-551 | `GET` | `/autonomy/approvals` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/approvals` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-552 | `GET` | `/autonomy/brief` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/brief` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-553 | `GET` | `/autonomy/interrupts` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/interrupts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-554 | `GET` | `/autonomy/mediation` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/mediation` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-555 | `GET` | `/autonomy/mode` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/mode` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-556 | `POST` | `/autonomy/mode` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-557 | `GET` | `/autonomy/observer` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/observer` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-558 | `POST` | `/autonomy/observer/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-559 | `GET` | `/autonomy/policy` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/policy` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-560 | `POST` | `/autonomy/policy` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-561 | `GET` | `/autonomy/preferences/suggestions` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/preferences/suggestions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-562 | `GET` | `/autonomy/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-563 | `GET` | `/autonomy/tasks` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/tasks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-564 | `POST` | `/autonomy/tasks` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-565 | `POST` | `/autonomy/tasks/groups/{group_id}/reject` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-566 | `POST` | `/autonomy/tasks/{task_id}/consent` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-567 | `POST` | `/autonomy/tasks/{task_id}/decision` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.bench `bench` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-568 | `GET` | `/bench` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/bench` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-569 | `GET` | `/bench/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/bench/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.brain `brain` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-570 | `GET` | `/brain` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/brain` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.chat `chat` — 4 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-571 | `POST` | `/chat` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-572 | `GET` | `/chat/pending` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/chat/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-573 | `POST` | `/chat/pending/{prompt_id}/answer` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-574 | `POST` | `/chat/stream` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.dashboard `dashboard` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-575 | `GET` | `/dashboard` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/dashboard` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.docs `docs` — 2 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-576 | `GET` | `/docs` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-577 | `GET` | `/docs/oauth2-redirect` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/docs/oauth2-redirect` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.favicon.ico `favicon.ico` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-578 | `GET` | `/favicon.ico` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/favicon.ico` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.healthz `healthz` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-579 | `GET` | `/healthz` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/healthz` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.heartbeat `heartbeat` — 4 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-580 | `GET` | `/heartbeat/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/heartbeat/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-581 | `POST` | `/heartbeat/{agent_id}/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-582 | `POST` | `/heartbeat/{agent_id}/start` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-583 | `POST` | `/heartbeat/{agent_id}/stop` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.learning `learning` — 3 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-584 | `GET` | `/learning` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/learning` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-585 | `POST` | `/learning/promote` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-586 | `GET` | `/learning/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/learning/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.manifest.webmanifest `manifest.webmanifest` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-587 | `GET` | `/manifest.webmanifest` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/manifest.webmanifest` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.map `map` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-588 | `GET` | `/map` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/map` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.memory `memory` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-589 | `GET` | `/memory` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/memory` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-590 | `POST` | `/memory/clear` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-591 | `GET` | `/memory/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/memory/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-592 | `GET` | `/memory/{agent_id}` | `user` | `GET $B/memory/{agent_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.metrics `metrics` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-593 | `GET` | `/metrics` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/metrics` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.mission-control `mission-control` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-594 | `GET` | `/mission-control` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/mission-control` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.openapi.json `openapi.json` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-595 | `GET` | `/openapi.json` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/openapi.json` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.plugins `plugins` — 2 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-596 | `GET` | `/plugins` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/plugins` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-597 | `PUT` | `/plugins/{plugin_id}/toggle` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.readyz `readyz` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-598 | `GET` | `/readyz` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/readyz` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.redoc `redoc` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-599 | `GET` | `/redoc` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/redoc` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sandbox `sandbox` — 4 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-600 | `POST` | `/sandbox/execute` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-601 | `GET` | `/sandbox/kernels` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sandbox/kernels` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-602 | `POST` | `/sandbox/kernels/reset` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-603 | `GET` | `/sandbox/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sandbox/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.security `security` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-604 | `GET` | `/security` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/security` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-605 | `GET` | `/security/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/security/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sessions `sessions` — 12 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-606 | `GET` | `/sessions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sessions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-607 | `POST` | `/sessions/continue` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-608 | `POST` | `/sessions/import` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-609 | `POST` | `/sessions/resolve` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-610 | `POST` | `/sessions/resume` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-611 | `GET` | `/sessions/todo` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sessions/todo` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-612 | `DELETE` | `/sessions/{session_id}` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-613 | `POST` | `/sessions/{session_id}/archive` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-614 | `POST` | `/sessions/{session_id}/pin` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-615 | `GET` | `/sessions/{session_id}/todo` | `user` | `GET $B/sessions/{session_id}/todo` with a real id from this group's list route | **200** with the plan for a live id · **200** with an empty list for an unknown one (no plan is kept for it) · **400** for an id that is not a session id — never a fabricated plan |
| API-616 | `POST` | `/sessions/{session_id}/unarchive` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-617 | `POST` | `/sessions/{session_id}/unpin` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.skills `skills` — 3 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-618 | `GET` | `/skills` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/skills` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-619 | `POST` | `/skills/import` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-620 | `GET` | `/skills/imported` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/skills/imported` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.status `status` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-621 | `GET` | `/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sw-v2.js `sw-v2.js` — 1 routes · behaviour owned by §—

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-622 | `GET` | `/sw-v2.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sw-v2.js` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sw.js `sw.js` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-623 | `GET` | `/sw.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sw.js` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.tasks `tasks` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-624 | `GET` | `/tasks` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/tasks` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.ticker `ticker` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-625 | `GET` | `/ticker` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/ticker` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.tts `tts` — 2 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-626 | `POST` | `/tts` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-627 | `POST` | `/tts/stream` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.v1 `v1` — 2 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-628 | `GET` | `/v1` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v1` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-629 | `GET` | `/v1/capabilities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/v1/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.v2 `v2` — 4 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-630 | `GET` | `/v2` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-631 | `GET` | `/v2/manifest.webmanifest` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2/manifest.webmanifest` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-632 | `GET` | `/v2/sw-v2.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2/sw-v2.js` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-633 | `GET` | `/v2/{path:path}` | `open` | `GET $B/v2/{path:path}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.Z Coverage ledger

| Pass | Routes | Needs | Records |
|---|---|---|---|
| A — existence & honesty | 262 read routes | booted server | one line per non-200 |
| B — tier enforcement | ≥20 sampled + all 74 `open` | 🌐 second device | expected vs actual code per route |
| C — payload leak hunt | every `user`/`open` collection route | booted server | body excerpt per suspected leak |
| Mutating routes | 327 | see the §-pointer per group | exercised by owning section, not here |
| **Total enumerated** | **633** | — | — |

## Open gaps found while writing

- The `open` tier is the largest unaudited attack surface in the sweep (74 routes). Pass C is the only thing standing between it and a tier leak; budget real time for it rather than treating it as a formality.
- Templated read routes (`{id}` paths) are skipped by the Pass-A driver because they need a live id. They are covered by their owning sections — but that means a broken templated route can only be caught there, so do not treat a green Pass A as full read coverage.
- Mutating routes are deliberately not fired here. A sweep that POSTs blindly across 327 routes would mutate the owner's real state — the opposite of a safe manual.

*Generated by `scripts/gen_api_sweep.py` from the route snapshots at the committed revision.*
