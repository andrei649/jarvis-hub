# 14. API surface sweep — every route, every tier

> **Scope.** A complete, generated enumeration of the HTTP surface: **405 app routes** (the figure `project-status.json` → `routes` reports) **plus 4 FastAPI doc routes** = **409 enumerated below** — the two numbers are not a contradiction, they count different things. Across **111** groups, each with its guard tier and a copy-pasteable probe. This chapter proves a route **exists and is guarded correctly**; the *owning section* proves it **behaves correctly** — follow the §-pointer in each group heading.
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
| `user` | 182 | `user_guard` (`X-User-Token`) | 403 when `JARVIS_USER_TOKEN` is unset, 401 when set but missing/wrong |
| `admin` | 144 | `admin_guard` (`X-Admin-Token`) | must reject a user token as well as no token |
| `open` | 83 | none by design | must expose nothing tier-gated — the highest-value leak hunt in this chapter |

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

**Pass C — payload-tier leak hunt.** For every `user`-tier and `open` route that returns a collection, read the body and ask: *does this contain anything the admin tier is meant to gate?* (drafts, tool results, secrets, payloads, household identifiers, camera data). The known instance is `GET /tasks` returning full `payload`/`result` at user tier (`agents/core/routers/dashboard.py`, BACKLOG **TASK-5**) — confirm it still leaks, then hunt for others. Each new one is a **MAJOR** finding.

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

## 14.3.acquisition `/api/acquisition` — 7 routes · behaviour owned by §10 · 12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-008 | `GET` | `/api/acquisition/events` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-009 | `GET` | `/api/acquisition/ledger/export` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/ledger/export` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-010 | `POST` | `/api/acquisition/ledger/purge` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |
| API-011 | `GET` | `/api/acquisition/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/acquisition/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-012 | `POST` | `/api/acquisition/{name}/revoke` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |
| API-013 | `POST` | `/api/acquisition/{name}/rollback` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |
| API-014 | `POST` | `/api/acquisition/{request_id}/drive` | `admin` | mutating — needs a body; exercise it in §10 · 12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.actions `/api/actions` — 4 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-015 | `GET` | `/api/actions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/actions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-016 | `GET` | `/api/actions/pending` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/actions/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-017 | `POST` | `/api/actions/request` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-018 | `POST` | `/api/actions/{action_id}/decide` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.admin `/api/admin` — 35 routes · behaviour owned by §05 · 08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-019 | `GET` | `/api/admin/agents/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/agents/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-020 | `PUT` | `/api/admin/agents/{agent_id}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-021 | `GET` | `/api/admin/apm` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/apm` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-022 | `GET` | `/api/admin/audit` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/audit` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-023 | `GET` | `/api/admin/backup` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/backup` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-024 | `POST` | `/api/admin/backup` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-025 | `POST` | `/api/admin/backup/verify` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-026 | `GET` | `/api/admin/env` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/env` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-027 | `POST` | `/api/admin/export` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-028 | `POST` | `/api/admin/forget` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-029 | `POST` | `/api/admin/llm/test` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-030 | `GET` | `/api/admin/mcp` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/mcp` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-031 | `POST` | `/api/admin/mcp` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-032 | `DELETE` | `/api/admin/mcp/{name}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-033 | `POST` | `/api/admin/mcp/{name}/connect` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-034 | `POST` | `/api/admin/mcp/{name}/disconnect` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-035 | `POST` | `/api/admin/memory/clear` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-036 | `GET` | `/api/admin/network/calls` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/network/calls` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-037 | `GET` | `/api/admin/prompts/{agent_id}/ab` | `admin` | `GET $B/api/admin/prompts/{agent_id}/ab` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-038 | `POST` | `/api/admin/prompts/{agent_id}/ab` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-039 | `POST` | `/api/admin/prompts/{agent_id}/commit` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-040 | `GET` | `/api/admin/prompts/{agent_id}/diff` | `admin` | `GET $B/api/admin/prompts/{agent_id}/diff` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-041 | `GET` | `/api/admin/prompts/{agent_id}/history` | `admin` | `GET $B/api/admin/prompts/{agent_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-042 | `POST` | `/api/admin/prompts/{agent_id}/preview` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-043 | `POST` | `/api/admin/prompts/{agent_id}/rollback` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-044 | `GET` | `/api/admin/prompts/{agent_id}/version/{version}` | `admin` | `GET $B/api/admin/prompts/{agent_id}/version/{version}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-045 | `POST` | `/api/admin/rotate-tokens` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-046 | `GET` | `/api/admin/settings` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/settings` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-047 | `POST` | `/api/admin/settings/reseed` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-048 | `GET` | `/api/admin/settings/{category}` | `admin` | `GET $B/api/admin/settings/{category}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-049 | `PUT` | `/api/admin/settings/{category}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-050 | `GET` | `/api/admin/stats` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-051 | `GET` | `/api/admin/widgets` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/admin/widgets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-052 | `POST` | `/api/admin/widgets` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |
| API-053 | `DELETE` | `/api/admin/widgets/{token}` | `admin` | mutating — needs a body; exercise it in §05 · 08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.agent-templates `/api/agent-templates` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-054 | `GET` | `/api/agent-templates` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/agent-templates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-055 | `POST` | `/api/agent-templates/instantiate` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.agents `/api/agents` — 4 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-056 | `GET` | `/api/agents` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/agents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-057 | `GET` | `/api/agents/history` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/agents/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-058 | `GET` | `/api/agents/{agent_id}/history` | `open` | `GET $B/api/agents/{agent_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-059 | `GET` | `/api/agents/{agent_id}/soul` | `open` | `GET $B/api/agents/{agent_id}/soul` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.ambient `/api/ambient` — 4 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-060 | `GET` | `/api/ambient/monitors` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ambient/monitors` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-061 | `POST` | `/api/ambient/monitors` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-062 | `DELETE` | `/api/ambient/monitors/{monitor_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-063 | `PUT` | `/api/ambient/monitors/{monitor_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.analytics `/api/analytics` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-064 | `GET` | `/api/analytics/cost` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/cost` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-065 | `POST` | `/api/analytics/event` | `open` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-066 | `GET` | `/api/analytics/locality` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/locality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-067 | `GET` | `/api/analytics/model-tiers` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/analytics/model-tiers` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.arena `/api/arena` — 4 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-068 | `GET` | `/api/arena/leaderboard` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/arena/leaderboard` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-069 | `GET` | `/api/arena/match/{match_id}` | `open` | `GET $B/api/arena/match/{match_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-070 | `POST` | `/api/arena/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-071 | `POST` | `/api/arena/vote` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.autonomy `/api/autonomy` — 5 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-072 | `POST` | `/api/autonomy/call` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-073 | `POST` | `/api/autonomy/escalate` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-074 | `GET` | `/api/autonomy/escalation/targets` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/autonomy/escalation/targets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-075 | `POST` | `/api/autonomy/preview` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-076 | `GET` | `/api/autonomy/tasks/{task_id}/preview` | `admin` | `GET $B/api/autonomy/tasks/{task_id}/preview` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.brain `/api/brain` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-077 | `GET` | `/api/brain/summary` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/brain/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.browser `/api/browser` — 2 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-078 | `POST` | `/api/browser/check` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-079 | `POST` | `/api/browser/plan/preview` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.cameras `/api/cameras` — 4 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-080 | `GET` | `/api/cameras/events` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cameras/events` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-081 | `POST` | `/api/cameras/onvif/discover` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-082 | `POST` | `/api/cameras/search` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-083 | `GET` | `/api/cameras/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cameras/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.canvas `/api/canvas` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-084 | `GET` | `/api/canvas` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/canvas` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-085 | `POST` | `/api/canvas/clear` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-086 | `POST` | `/api/canvas/post` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-087 | `DELETE` | `/api/canvas/{el_id}` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-088 | `POST` | `/api/canvas/{el_id}/pin` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.capabilities `/api/capabilities` — 1 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-089 | `GET` | `/api/capabilities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.capture `/api/capture` — 6 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-090 | `GET` | `/api/capture` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-091 | `POST` | `/api/capture/clear` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-092 | `POST` | `/api/capture/ingest` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-093 | `GET` | `/api/capture/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/capture/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-094 | `POST` | `/api/capture/surfaces` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-095 | `DELETE` | `/api/capture/{rec_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.channels `/api/channels` — 11 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-096 | `GET` | `/api/channels/inbox` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/inbox` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-097 | `GET` | `/api/channels/inbox/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/inbox/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-098 | `GET` | `/api/channels/inbox/{thread_id}` | `user` | `GET $B/api/channels/inbox/{thread_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-099 | `POST` | `/api/channels/inbox/{thread_id}/reply` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-100 | `GET` | `/api/channels/pairing` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/pairing` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-101 | `POST` | `/api/channels/pairing/code` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-102 | `POST` | `/api/channels/pairing/decide` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-103 | `POST` | `/api/channels/pairing/request` | `open` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-104 | `GET` | `/api/channels/send-rate-limit` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/send-rate-limit` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-105 | `GET` | `/api/channels/webhook` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/channels/webhook` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-106 | `POST` | `/api/channels/{channel_id}/inbound` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.coach `/api/coach` — 3 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-107 | `POST` | `/api/coach/curriculum` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-108 | `POST` | `/api/coach/review` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-109 | `POST` | `/api/coach/session` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.codeintel `/api/codeintel` — 3 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-110 | `POST` | `/api/codeintel/reindex` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-111 | `GET` | `/api/codeintel/search` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/codeintel/search` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-112 | `GET` | `/api/codeintel/stats` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/codeintel/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.cognition `/api/cognition` — 8 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-113 | `GET` | `/api/cognition` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-114 | `GET` | `/api/cognition/ensemble` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/ensemble` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-115 | `GET` | `/api/cognition/honesty` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/honesty` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-116 | `GET` | `/api/cognition/learning` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/learning` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-117 | `GET` | `/api/cognition/memory` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/memory` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-118 | `GET` | `/api/cognition/personality` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/personality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-119 | `GET` | `/api/cognition/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-120 | `GET` | `/api/cognition/stream` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cognition/stream` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.context `/api/context` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-121 | `POST` | `/api/context/compress` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.cost `/api/cost` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-122 | `GET` | `/api/cost` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/cost` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.creative `/api/creative` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-123 | `POST` | `/api/creative/export-packs` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-124 | `POST` | `/api/creative/plan` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.dashboard `/api/dashboard` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-125 | `GET` | `/api/dashboard/today` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/dashboard/today` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.desktop `/api/desktop` — 2 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-126 | `POST` | `/api/desktop/preview` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |
| API-127 | `POST` | `/api/desktop/run` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.digest `/api/digest` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-128 | `POST` | `/api/digest/run` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.eval `/api/eval` — 4 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-129 | `GET` | `/api/eval/datasets` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/eval/datasets` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-130 | `POST` | `/api/eval/datasets/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-131 | `GET` | `/api/eval/datasets/{name}/compare` | `open` | `GET $B/api/eval/datasets/{name}/compare` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-132 | `GET` | `/api/eval/datasets/{name}/runs` | `open` | `GET $B/api/eval/datasets/{name}/runs` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.feedback `/api/feedback` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-133 | `POST` | `/api/feedback` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-134 | `GET` | `/api/feedback/summary` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/feedback/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.health `/api/health` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-135 | `GET` | `/api/health/components` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/health/components` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.house `/api/house` — 6 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-136 | `POST` | `/api/house/control/climate` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-137 | `POST` | `/api/house/control/light` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-138 | `POST` | `/api/house/control/security` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-139 | `POST` | `/api/house/security/{task_id}/challenge` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-140 | `POST` | `/api/house/security/{task_id}/confirm` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-141 | `GET` | `/api/house/state` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/house/state` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.ingestion `/api/ingestion` — 1 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-142 | `GET` | `/api/ingestion/provenance` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/ingestion/provenance` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.integrations `/api/integrations` — 4 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-143 | `GET` | `/api/integrations/social` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/integrations/social` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-144 | `POST` | `/api/integrations/social` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-145 | `GET` | `/api/integrations/writeback` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/integrations/writeback` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-146 | `POST` | `/api/integrations/writeback` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.kg `/api/kg` — 10 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-147 | `GET` | `/api/kg/entities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/entities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-148 | `POST` | `/api/kg/entities` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-149 | `DELETE` | `/api/kg/entities/{name}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-150 | `GET` | `/api/kg/entities/{name}` | `user` | `GET $B/api/kg/entities/{name}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-151 | `POST` | `/api/kg/facts` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-152 | `GET` | `/api/kg/facts/as-of` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/facts/as-of` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-153 | `GET` | `/api/kg/facts/history` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/kg/facts/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-154 | `POST` | `/api/kg/ingest` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-155 | `DELETE` | `/api/kg/relations` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-156 | `POST` | `/api/kg/relations` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.learning `/api/learning` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-157 | `POST` | `/api/learning/propose` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.llm `/api/llm` — 8 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-158 | `GET` | `/api/llm/auth-profiles` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/auth-profiles` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-159 | `POST` | `/api/llm/grammar` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-160 | `POST` | `/api/llm/load` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-161 | `POST` | `/api/llm/moe/route` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-162 | `POST` | `/api/llm/openrouter` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-163 | `POST` | `/api/llm/server/start` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-164 | `GET` | `/api/llm/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/llm/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-165 | `POST` | `/api/llm/unload` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.local-docs `/api/local-docs` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-166 | `GET` | `/api/local-docs` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/local-docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-167 | `POST` | `/api/local-docs/index` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.market `/api/market` — 5 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-168 | `POST` | `/api/market/brief` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-169 | `POST` | `/api/market/watchlist` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-170 | `GET` | `/api/market/watchlist/saved` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/market/watchlist/saved` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-171 | `POST` | `/api/market/watchlist/saved` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-172 | `DELETE` | `/api/market/watchlist/saved/{symbol}` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.mcp `/api/mcp` — 3 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-173 | `GET` | `/api/mcp/server` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/mcp/server` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-174 | `POST` | `/api/mcp/server/rpc` | `open` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-175 | `POST` | `/api/mcp/token` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.media `/api/media` — 9 routes · behaviour owned by §12

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-176 | `GET` | `/api/media` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-177 | `GET` | `/api/media/catalog` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/catalog` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-178 | `GET` | `/api/media/devices` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/devices` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-179 | `POST` | `/api/media/devices` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-180 | `DELETE` | `/api/media/devices/{device_id}` | `admin` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-181 | `POST` | `/api/media/generate` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-182 | `POST` | `/api/media/present` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-183 | `POST` | `/api/media/restore/{device_id}` | `user` | mutating — needs a body; exercise it in §12 | **401/403** with no token · state actually changes only on a valid call |
| API-184 | `GET` | `/api/media/session` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/media/session` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.memory `/api/memory` — 18 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-185 | `POST` | `/api/memory/consolidate` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-186 | `GET` | `/api/memory/decay/candidates` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/decay/candidates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-187 | `POST` | `/api/memory/decay/forget` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-188 | `GET` | `/api/memory/decay/ranking` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/decay/ranking` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-189 | `GET` | `/api/memory/entities` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/entities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-190 | `GET` | `/api/memory/eval/corpus` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/memory/eval/corpus` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-191 | `POST` | `/api/memory/eval/run` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-192 | `GET` | `/api/memory/profile` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/profile` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-193 | `GET` | `/api/memory/recall` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/recall` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-194 | `POST` | `/api/memory/remember` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-195 | `GET` | `/api/memory/search` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/search` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-196 | `POST` | `/api/memory/search-tool` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-197 | `GET` | `/api/memory/spaces` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/memory/spaces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-198 | `POST` | `/api/memory/spaces` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-199 | `POST` | `/api/memory/spaces/assign` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-200 | `POST` | `/api/memory/spaces/unassign` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-201 | `DELETE` | `/api/memory/spaces/{name}` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-202 | `GET` | `/api/memory/tool-spec` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/memory/tool-spec` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.metrics `/api/metrics` — 3 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-203 | `GET` | `/api/metrics/capabilities` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-204 | `GET` | `/api/metrics/kernel` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/kernel` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-205 | `GET` | `/api/metrics/north-star` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/metrics/north-star` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.missions `/api/missions` — 9 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-206 | `GET` | `/api/missions` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/missions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-207 | `POST` | `/api/missions` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-208 | `GET` | `/api/missions/{mission_id}` | `open` | `GET $B/api/missions/{mission_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-209 | `POST` | `/api/missions/{mission_id}/cancel` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-210 | `POST` | `/api/missions/{mission_id}/complete` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-211 | `POST` | `/api/missions/{mission_id}/pause` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-212 | `POST` | `/api/missions/{mission_id}/resume` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-213 | `POST` | `/api/missions/{mission_id}/start` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-214 | `POST` | `/api/missions/{mission_id}/steps/{idx}/finish` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.models `/api/models` — 3 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-215 | `GET` | `/api/models/info` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/models/info` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-216 | `GET` | `/api/models/local` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/models/local` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-217 | `POST` | `/api/models/local/switch` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.nodes `/api/nodes` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-218 | `GET` | `/api/nodes` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/nodes` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-219 | `POST` | `/api/nodes/register` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-220 | `DELETE` | `/api/nodes/{node_id}` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-221 | `POST` | `/api/nodes/{node_id}/dispatch` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.notes `/api/notes` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-222 | `DELETE` | `/api/notes` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-223 | `GET` | `/api/notes` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/notes` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-224 | `PUT` | `/api/notes` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-225 | `POST` | `/api/notes/rewrite` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.oauth `/api/oauth` — 4 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-226 | `GET` | `/api/oauth/auth-url` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oauth/auth-url` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-227 | `POST` | `/api/oauth/callback` | `open` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-228 | `POST` | `/api/oauth/refresh` | `admin` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-229 | `GET` | `/api/oauth/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oauth/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.onboarding `/api/onboarding` — 3 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-230 | `GET` | `/api/onboarding/command-center` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/command-center` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-231 | `POST` | `/api/onboarding/funnel` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-232 | `GET` | `/api/onboarding/wizard` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/onboarding/wizard` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.oracle `/api/oracle` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-233 | `GET` | `/api/oracle/conflicts` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oracle/conflicts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-234 | `POST` | `/api/oracle/conflicts/resolve` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-235 | `GET` | `/api/oracle/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/oracle/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-236 | `POST` | `/api/oracle/sync` | `admin` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.osint `/api/osint` — 2 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-237 | `POST` | `/api/osint/brief` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-238 | `POST` | `/api/osint/correlate` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.payments `/api/payments` — 7 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-239 | `GET` | `/api/payments` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/payments` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-240 | `GET` | `/api/payments/mandates` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/payments/mandates` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-241 | `POST` | `/api/payments/mandates` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-242 | `POST` | `/api/payments/request` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-243 | `POST` | `/api/payments/{payment_id}/approve` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-244 | `POST` | `/api/payments/{payment_id}/reject` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-245 | `POST` | `/api/payments/{payment_id}/settle` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.presence `/api/presence` — 2 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-246 | `GET` | `/api/presence/owner` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/presence/owner` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-247 | `POST` | `/api/presence/owner` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.quality `/api/quality` — 3 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-248 | `GET` | `/api/quality` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/quality` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-249 | `GET` | `/api/quality/scores` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/quality/scores` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-250 | `POST` | `/api/quality/threshold` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.reflection `/api/reflection` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-251 | `POST` | `/api/reflection/run` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-252 | `GET` | `/api/reflection/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/reflection/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.resilience `/api/resilience` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-253 | `GET` | `/api/resilience` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/resilience` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.review `/api/review` — 5 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-254 | `POST` | `/api/review/flag` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-255 | `GET` | `/api/review/queue` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/review/queue` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-256 | `GET` | `/api/review/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/review/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-257 | `POST` | `/api/review/{item_id}/dataset` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-258 | `POST` | `/api/review/{item_id}/vote` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.rooms `/api/rooms` — 6 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-259 | `GET` | `/api/rooms` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/rooms` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-260 | `POST` | `/api/rooms` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-261 | `DELETE` | `/api/rooms/{room_id}` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-262 | `GET` | `/api/rooms/{room_id}` | `user` | `GET $B/api/rooms/{room_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-263 | `GET` | `/api/rooms/{room_id}/history` | `user` | `GET $B/api/rooms/{room_id}/history` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-264 | `POST` | `/api/rooms/{room_id}/message` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.satellites `/api/satellites` — 4 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-265 | `GET` | `/api/satellites` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/satellites` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-266 | `POST` | `/api/satellites/register` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-267 | `DELETE` | `/api/satellites/{satellite_id}` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-268 | `POST` | `/api/satellites/{satellite_id}/dispatch` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.schedule `/api/schedule` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-269 | `POST` | `/api/schedule/parse` | `user` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.secrets `/api/secrets` — 4 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-270 | `GET` | `/api/secrets/broker` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/secrets/broker` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-271 | `POST` | `/api/secrets/broker` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-272 | `POST` | `/api/secrets/broker/redact` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-273 | `DELETE` | `/api/secrets/broker/{name}` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.security `/api/security` — 15 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-274 | `POST` | `/api/security/audit/action` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-275 | `POST` | `/api/security/audit/anchor` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-276 | `GET` | `/api/security/audit/anchors` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/anchors` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-277 | `GET` | `/api/security/audit/intent` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/intent` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-278 | `GET` | `/api/security/audit/verify` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/audit/verify` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-279 | `GET` | `/api/security/capabilities/check` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/capabilities/check` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-280 | `POST` | `/api/security/capabilities/issue` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-281 | `GET` | `/api/security/governance` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/governance` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-282 | `GET` | `/api/security/kill-switch` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/kill-switch` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-283 | `POST` | `/api/security/kill-switch` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-284 | `GET` | `/api/security/loop-breaker` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/security/loop-breaker` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-285 | `POST` | `/api/security/loop-breaker/reset` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-286 | `GET` | `/api/security/posture` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security/posture` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-287 | `POST` | `/api/security/scan-injection` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-288 | `POST` | `/api/security/spotlight` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.security-skills `/api/security-skills` — 6 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-289 | `GET` | `/api/security-skills/frameworks` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/frameworks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-290 | `POST` | `/api/security-skills/map` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-291 | `POST` | `/api/security-skills/playbook` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-292 | `GET` | `/api/security-skills/tactics` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/tactics` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-293 | `GET` | `/api/security-skills/technique/{tid}` | `user` | `GET $B/api/security-skills/technique/{tid}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-294 | `GET` | `/api/security-skills/techniques` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/security-skills/techniques` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.self-improvement `/api/self-improvement` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-295 | `POST` | `/api/self-improvement/enable` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-296 | `GET` | `/api/self-improvement/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/self-improvement/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.skills `/api/skills` — 10 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-297 | `GET` | `/api/skills/marketplace` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/marketplace` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-298 | `GET` | `/api/skills/marketplace/history` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/marketplace/history` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-299 | `POST` | `/api/skills/marketplace/install` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-300 | `POST` | `/api/skills/marketplace/install-zip` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-301 | `POST` | `/api/skills/marketplace/publish` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-302 | `POST` | `/api/skills/marketplace/review` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-303 | `POST` | `/api/skills/marketplace/uninstall` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-304 | `POST` | `/api/skills/marketplace/{name}/rollback` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-305 | `GET` | `/api/skills/pending` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/skills/pending` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-306 | `POST` | `/api/skills/{name}/approve` | `admin` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.status `/api/status` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-307 | `GET` | `/api/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.subagents `/api/subagents` — 2 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-308 | `GET` | `/api/subagents` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/subagents` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-309 | `POST` | `/api/subagents/spawn` | `user` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.support `/api/support` — 1 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-310 | `GET` | `/api/support/bundle` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/support/bundle` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.swarm `/api/swarm` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-311 | `GET` | `/api/swarm/summary` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/swarm/summary` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sync `/api/sync` — 3 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-312 | `GET` | `/api/sync` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/sync` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-313 | `POST` | `/api/sync/pull` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |
| API-314 | `POST` | `/api/sync/push` | `user` | mutating — needs a body; exercise it in §04 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.system `/api/system` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-315 | `GET` | `/api/system/profiles` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/system/profiles` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.toolrpc `/api/toolrpc` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-316 | `POST` | `/api/toolrpc/call` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-317 | `GET` | `/api/toolrpc/tools` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/toolrpc/tools` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.traces `/api/traces` — 3 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-318 | `GET` | `/api/traces` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/traces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-319 | `POST` | `/api/traces/clear` | `admin` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-320 | `GET` | `/api/traces/{trace_id}` | `user` | `GET $B/api/traces/{trace_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.transcripts `/api/transcripts` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-321 | `POST` | `/api/transcripts/ingest` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.trust `/api/trust` — 1 routes · behaviour owned by §04

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-322 | `GET` | `/api/trust/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/trust/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.vlm `/api/vlm` — 2 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-323 | `POST` | `/api/vlm/describe` | `user` | mutating — needs a body; exercise it in §05 | **401/403** with no token · state actually changes only on a valid call |
| API-324 | `GET` | `/api/vlm/status` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/vlm/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.voice `/api/voice` — 3 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-325 | `GET` | `/api/voice/capabilities` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/voice/capabilities` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-326 | `POST` | `/api/voice/stt` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-327 | `GET` | `/api/voice/wyoming` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/voice/wyoming` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.webhooks `/api/webhooks` — 4 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-328 | `GET` | `/api/webhooks` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/webhooks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-329 | `POST` | `/api/webhooks` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-330 | `DELETE` | `/api/webhooks/{hook_id}` | `admin` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-331 | `POST` | `/api/webhooks/{hook_id}` | `open` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.widget `/api/widget` — 3 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-332 | `GET` | `/api/widget/{token}` | `open` | `GET $B/api/widget/{token}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-333 | `GET` | `/api/widget/{token}/config` | `open` | `GET $B/api/widget/{token}/config` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |
| API-334 | `POST` | `/api/widget/{token}/message` | `open` | mutating — needs a body; exercise it in §06 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.workflows `/api/workflows` — 8 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-335 | `GET` | `/api/workflows` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/workflows` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-336 | `POST` | `/api/workflows` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-337 | `POST` | `/api/workflows/hierarchical` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-338 | `POST` | `/api/workflows/run` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-339 | `POST` | `/api/workflows/step/generate` | `user` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-340 | `GET` | `/api/workflows/traces` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/api/workflows/traces` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-341 | `DELETE` | `/api/workflows/{pipeline_id}` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |
| API-342 | `PUT` | `/api/workflows/{pipeline_id}` | `admin` | mutating — needs a body; exercise it in §10 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.worldview `/api/worldview` — 2 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-343 | `GET` | `/api/worldview/overview` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/worldview/overview` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-344 | `GET` | `/api/worldview/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/api/worldview/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.(root) `(root)` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-345 | `GET` | `/` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3..well-known `.well-known` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-346 | `GET` | `/.well-known/agent-card` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/.well-known/agent-card` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-347 | `GET` | `/.well-known/oauth-protected-resource` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/.well-known/oauth-protected-resource` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.admin `admin` — 1 routes · behaviour owned by §03 · 06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-348 | `GET` | `/admin` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/admin` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.agents `agents` — 1 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-349 | `GET` | `/agents` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/agents` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.autonomy `autonomy` — 14 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-350 | `GET` | `/autonomy/approvals` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/approvals` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-351 | `GET` | `/autonomy/brief` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/brief` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-352 | `GET` | `/autonomy/interrupts` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/interrupts` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-353 | `GET` | `/autonomy/mode` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/mode` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-354 | `POST` | `/autonomy/mode` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-355 | `GET` | `/autonomy/observer` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/observer` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-356 | `POST` | `/autonomy/observer/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-357 | `GET` | `/autonomy/policy` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/policy` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-358 | `POST` | `/autonomy/policy` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-359 | `GET` | `/autonomy/preferences/suggestions` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/preferences/suggestions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-360 | `GET` | `/autonomy/status` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-361 | `GET` | `/autonomy/tasks` | `admin` | `curl -sS -H "X-Admin-Token: $JARVIS_ADMIN_TOKEN" -o /dev/null -w "%{http_code}\n" $B/autonomy/tasks` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-362 | `POST` | `/autonomy/tasks` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-363 | `POST` | `/autonomy/tasks/{task_id}/decision` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.bench `bench` — 2 routes · behaviour owned by §10

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-364 | `GET` | `/bench` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/bench` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-365 | `GET` | `/bench/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/bench/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.brain `brain` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-366 | `GET` | `/brain` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/brain` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.chat `chat` — 2 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-367 | `POST` | `/chat` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |
| API-368 | `POST` | `/chat/stream` | `user` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.dashboard `dashboard` — 1 routes · behaviour owned by §05

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-369 | `GET` | `/dashboard` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/dashboard` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.docs `docs` — 2 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-370 | `GET` | `/docs` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/docs` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-371 | `GET` | `/docs/oauth2-redirect` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/docs/oauth2-redirect` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.favicon.ico `favicon.ico` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-372 | `GET` | `/favicon.ico` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/favicon.ico` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.healthz `healthz` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-373 | `GET` | `/healthz` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/healthz` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.heartbeat `heartbeat` — 4 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-374 | `GET` | `/heartbeat/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/heartbeat/status` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-375 | `POST` | `/heartbeat/{agent_id}/run` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-376 | `POST` | `/heartbeat/{agent_id}/start` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-377 | `POST` | `/heartbeat/{agent_id}/stop` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.learning `learning` — 3 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-378 | `GET` | `/learning` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/learning` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-379 | `POST` | `/learning/promote` | `admin` | mutating — needs a body; exercise it in §07 | **401/403** with no token · state actually changes only on a valid call |
| API-380 | `GET` | `/learning/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/learning/stats` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.memory `memory` — 4 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-381 | `GET` | `/memory` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/memory` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-382 | `POST` | `/memory/clear` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |
| API-383 | `GET` | `/memory/stats` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/memory/stats` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-384 | `GET` | `/memory/{agent_id}` | `user` | `GET $B/memory/{agent_id}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.3.metrics `metrics` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-385 | `GET` | `/metrics` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/metrics` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.mission-control `mission-control` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-386 | `GET` | `/mission-control` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/mission-control` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.openapi.json `openapi.json` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-387 | `GET` | `/openapi.json` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/openapi.json` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.plugins `plugins` — 2 routes · behaviour owned by §02

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-388 | `GET` | `/plugins` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/plugins` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-389 | `PUT` | `/plugins/{plugin_id}/toggle` | `admin` | mutating — needs a body; exercise it in §02 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.readyz `readyz` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-390 | `GET` | `/readyz` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/readyz` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.redoc `redoc` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-391 | `GET` | `/redoc` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/redoc` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sandbox `sandbox` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-392 | `POST` | `/sandbox/execute` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-393 | `GET` | `/sandbox/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sandbox/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.security `security` — 2 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-394 | `GET` | `/security` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/security` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-395 | `GET` | `/security/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/security/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sessions `sessions` — 2 routes · behaviour owned by §09

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-396 | `GET` | `/sessions` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/sessions` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-397 | `POST` | `/sessions/resume` | `user` | mutating — needs a body; exercise it in §09 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.skills `skills` — 3 routes · behaviour owned by §08

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-398 | `GET` | `/skills` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/skills` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-399 | `POST` | `/skills/import` | `user` | mutating — needs a body; exercise it in §08 | **401/403** with no token · state actually changes only on a valid call |
| API-400 | `GET` | `/skills/imported` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/skills/imported` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.status `status` — 1 routes · behaviour owned by §01

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-401 | `GET` | `/status` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/status` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.sw.js `sw.js` — 1 routes · behaviour owned by §06

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-402 | `GET` | `/sw.js` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/sw.js` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.tasks `tasks` — 1 routes · behaviour owned by §07

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-403 | `GET` | `/tasks` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/tasks` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.ticker `ticker` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-404 | `GET` | `/ticker` | `user` | `curl -sS -H "X-User-Token: $JARVIS_USER_TOKEN" -o /dev/null -w "%{http_code}\n" $B/ticker` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.tts `tts` — 2 routes · behaviour owned by §11

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-405 | `POST` | `/tts` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |
| API-406 | `POST` | `/tts/stream` | `user` | mutating — needs a body; exercise it in §11 | **401/403** with no token · state actually changes only on a valid call |

## 14.3.v1 `v1` — 1 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-407 | `GET` | `/v1` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v1` | **200** — or a documented 4xx/503 whose body says honestly why |

## 14.3.v2 `v2` — 2 routes · behaviour owned by §03

| ID | Method | Path | Tier | Probe | Expect |
|----|--------|------|------|-------|--------|
| API-408 | `GET` | `/v2` | `open` | `curl -sS -o /dev/null -w "%{http_code}\n" $B/v2` | **200** — or a documented 4xx/503 whose body says honestly why |
| API-409 | `GET` | `/v2/{path:path}` | `open` | `GET $B/v2/{path:path}` with a real id from this group's list route | **200** for a live id · **404** for a bogus one — never a fabricated record |

## 14.Z Coverage ledger

| Pass | Routes | Needs | Records |
|---|---|---|---|
| A — existence & honesty | 181 read routes | booted server | one line per non-200 |
| B — tier enforcement | ≥20 sampled + all 83 `open` | 🌐 second device | expected vs actual code per route |
| C — payload leak hunt | every `user`/`open` collection route | booted server | body excerpt per suspected leak |
| Mutating routes | 206 | see the §-pointer per group | exercised by owning section, not here |
| **Total enumerated** | **409** | — | — |

## Open gaps found while writing

- The `open` tier is the largest unaudited attack surface in the sweep (83 routes). Pass C is the only thing standing between it and a tier leak; budget real time for it rather than treating it as a formality.
- Templated read routes (`{id}` paths) are skipped by the Pass-A driver because they need a live id. They are covered by their owning sections — but that means a broken templated route can only be caught there, so do not treat a green Pass A as full read coverage.
- Mutating routes are deliberately not fired here. A sweep that POSTs blindly across 206 routes would mutate the owner's real state — the opposite of a safe manual.

*Generated by `scripts/gen_api_sweep.py` from the route snapshots at the committed revision.*
