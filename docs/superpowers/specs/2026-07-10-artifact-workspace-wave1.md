# Artifact Workspace — wave 1 (visual-artifact lane, Canvas-backed)

> Slice spec + implementation plan (product design already approved — this does not reopen scope).
> Branch: `claude/visual-artifact-lane-4st76p` · merge-independent from `codex/agent-runtime-v2-wave1`.

## Goal

Let the user **explicitly** save a completed assistant response as a governed Canvas artifact,
then inspect, pin, unpin, and delete Canvas artifacts from a new **Artifacts** tab in the
cockpit center panel. Reuses the existing `CanvasStore` + unchanged `/api/canvas*` routes.

## Non-goals

- No binary artifact store, no uploads, no native audio/video/PDF storage (separate reviewed
  slice: MIME validation, authenticated delivery, quotas, retention, export, purge contracts).
- No new HTTP routes, no route/OpenAPI/auth snapshot reseeds, no chat/SSE contract changes.
- No auto-saving — a reply is persisted only on an explicit user click.
- No mobile implementation (tracked as H18.20 handoff).

## Files

Create:
- `frontend/src/artifacts.tsx` — `ArtifactsPanel` (fetch/render/pin/unpin/delete) +
  `SaveArtifactButton` (explicit save control) + safe per-type renderers.
- `frontend/src/test/artifacts.test.tsx` — the frontend proof suite (below).
- this spec.

Modify:
- `frontend/src/app.tsx` — third center tab `Artifacts`; refresh-counter wiring after a save.
- `frontend/src/cockpit.tsx` — save control on completed non-system assistant messages
  (rendered only when the cockpit passes `onArtifactSaved`; ChatMode never shows it).
- `frontend/src/styles.css` — artifact card styles in the existing visual language.
- `agents/core/canvas.py` — `_safe_url()` rejects protocol-relative (`//…`, `/\…`) URLs.
- `tests/test_h12_18_canvas.py` — sanitizer regression tests.
- `agents/core/data_purge.py` — `canvas.json` joins `PURGE_JSON` (forget-me resets it to `{}`,
  which `CanvasStore._deserialize` loads as an empty store).
- `tests/test_data_purge_memory.py` — canvas purge expectations flipped.
- `mobile/PARITY.md` — Artifacts row (browser ✅ / mobile ⬜ / H18.20).
- `agents/web/v2/*` — regenerated only by `npm run build`.

## Security / privacy

- `_safe_url("//attacker.example/pixel")` currently passes the `startswith("/")` same-origin
  branch; browsers resolve it against the page scheme → cross-origin fetch. Fixed to return
  `""` for `//` and `/\` prefixes; `/static/...`, other single-slash paths, `https://`,
  `http://` behavior preserved.
- Saved assistant replies are user content → forget-me now resets `canvas.json` instead of
  intentionally preserving it. Scope is not broadened otherwise.
- Rendering: no `dangerouslySetInnerHTML`, no iframes/scripts. Markdown uses a React-only
  mini renderer (headings/bold/inline-code/lists); unknown markup stays literal text.
  Same-origin (`/...`, not `//`) images render; remote `http(s)` images render a consent
  placeholder and load only after an explicit click with `referrerPolicy="no-referrer"`.
  `MediaCatalog.path` is never referenced.

## Save contract (unchanged API)

`POST /api/canvas/post` with
`{"agent": <responding agent>, "type": "markdown", "payload": {"title": "Saved response",
"body": <reply, max 4000 chars>}, "pinned": false}`.
Truncation at the Canvas markdown bound (4,000) is disclosed in the control's saved state.
States: idle → saving (click-locked) → saved / saved·truncated / error (retryable).
Never shown for: user messages, system notices, empty messages, the in-flight streaming reply.

## Tests

Backend (RED first):
1. protocol-relative **link** URL rejected; 2. protocol-relative **image_ref** URL rejected;
3. `/static/...` still accepted; 4. `https://...` still accepted;
5. forget-me resets `canvas.json` and `CanvasStore` loads the post-purge file as empty.

Frontend (RED first): fetch+render all 7 canvas types · unsafe markup inert · remote image
consent gate · `referrerPolicy="no-referrer"` · exact save payload · 4,000-char truncation
disclosed · save control visibility rules (user/system/empty/in-flight) · double-click save
lock · pin/unpin endpoint calls · delete removes card · loading/empty/API-error/save-error/
refresh honesty.

## Verification

```
python -m pytest tests/test_h12_18_canvas.py tests/test_data_purge_memory.py \
  tests/test_hud_v2_parity.py tests/test_route_parity_guard.py \
  tests/test_openapi_parity_guard.py tests/test_route_auth_matrix.py -q
cd frontend && npm test -- src/test/artifacts.test.tsx && npm run typecheck && npm test && npm run build
git diff --check && git status --short
```

## Rollback

Revert the PR — the feature is additive (one tab + one per-message control); the sanitizer
fix and purge scope stand alone and are covered by regression tests.
