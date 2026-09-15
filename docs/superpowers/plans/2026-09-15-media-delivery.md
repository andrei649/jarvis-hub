# Media delivery plan

Goal: H12.26 authenticated binary attachments, then H515/H518 generation options and gallery.
Base/head at design: f75d7c326dfd378a22edc53564cdbdb6f17cc1fa. Generated 2026-09-15.
Changed paths at design: none. Next action: failing attachment regressions.
Authorization: owner requested implementation and owner-out-of-loop delivery; no additional gate.

1. Add a default-off attachment store under the data root. Fixed opaque IDs, magic-byte allowlist, 16 MiB upload/128 MiB store/200 items, pinned-aware quota eviction and opt-in TTL. Disk-backed index read afresh for every operation; no live cache can resurrect forgotten entries. Use the existing SQLite persistence convention rather than the proposed cached JsonStore: BEGIN IMMEDIATE serializes quota modifications across workers and no live index can resurrect forgotten rows.
2. Add user-guarded upload/list/blob/delete/pin routes. Parse multipart only after a bounded request stream has been collected in memory (no framework pre-auth/pre-quota temp-file spooling). Never trust a client MIME or expose paths. Shared blob resolver accepts attachments and generated IDs. Generated route remains a compatibility alias.
3. Export validated binaries with hash/size metadata and base64 bytes alongside portable data. Forget deletes binary bytes before backup per wave-2 requirement; no cache to clear. Retention uses existing sweep settings. Add Artifacts attachment controls with authenticated fetch/object URLs.
4. Extend the existing fixed ComfyUI transport and exact bound proposal with configured checkpoint selection, explicit local backend, up to four generated references, and bounded 2x pixel upscale. Advertise only supported/configured options. No cloud calls, arbitrary URL/path inputs, live ComfyUI or new authority.
5. Unify generated/cache/attached browsing behind bounded opaque delivery and honest unsupported/missing states. Keep text Canvas intact; update mobile/HUD and ledgers honestly.

Tests: spoofed MIME/active files, pre-disk size rejection, pin-aware byte/count eviction, traversal/symlinks, auth on every route, lifecycle export/hash/purge/TTL, real HTTP upload/read/delete with isolated store, UI upload/delete/download and generation option requests; existing media/runtime exact-approval regressions, frontend typecheck, route/OpenAPI guards. All Python tests use fresh temporary data root and JARVIS_TESTING=1 NERVA_PUBLIC_PROFILE=1 PYTHON_DOTENV_DISABLED=1. Single worker only.
Dependencies: existing Python 3.12 venv, frontend dependencies read-only, no new paid services. Risks: generation proof is mocked transport only; multi-reference composition must be labeled clearly; never claim a remote provider.
Rollback: attachment feature is one independent default-off commit; generation/gallery another. Revert generation before attachments if shared delivery is used; disabling attachment switch prevents writes while export/forget still covers existing data.
