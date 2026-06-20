---
name: jarvis-add-route
description: Use when adding, moving, or removing an HTTP endpoint in the jarvis hub backend (agents/web.py or agents/core/routers/*). Triggers on "add a route", "new endpoint", "new API", route 4xx/parity-test failures, or any change to app.routes.
---

# Adding a web endpoint (anti-god-object, CLN-3)

`agents/web.py` already has ~253 inline routes — **do not add new `@app.*` decorators there.**

1. **Create/open a per-domain router** `agents/core/routers/<domain>.py`. Mirror an existing one (e.g. `capture.py`): an `APIRouter`, guards imported from `routers/_deps.py`, shared state reached lazily via `from agents import web`.
2. **Add the route**, returning `_nocache_json(...)` and `503` when `orch` is None.
3. **Pick the guard:** `_admin_guard` (admin-only), `_user_guard` (exposes assistant/personal data or runs code — HF-1), or none (public read). Mutating routes MUST be guarded or in `INTENTIONALLY_OPEN` — the auth matrix gate (`tests/test_route_auth_matrix.py`) fails CI otherwise.
4. **Mount** it in `web.py` with `app.include_router(...)`.
5. **Re-seed the parity snapshot** in the SAME change: `python tests/test_route_parity_guard.py --update`. Any route surface change flags `tests/test_route_parity_guard.py` until re-seeded.
6. Polling/live-data routes: add the path to `_NO_STORE_PATHS`.

## Common mistakes
- New `@app.get` inline in `web.py` → review reject; use a router.
- Forgetting the parity re-seed → red CI.
- Mutating route with no guard → auth-matrix failure.
