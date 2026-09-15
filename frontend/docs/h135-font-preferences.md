# H135 local font preference implementation plan

Goal: persist an owner's finite UI font override through the existing appearance contract.
Base: 02f44a7bd546fad8a7a6afec5cc1c5f155f2d9c0. Generated: 2026-09-15.
Head: implementation in this commit. Next action: parent independent review/integration.
Execution: writing-plans, executing-plans and TDD, inline; parent owns independent review and integration.

The fixed IDs are theme, system-sans, system-serif, system-mono and jetbrains-mono.
Theme uses the existing bundled Space Grotesk; JetBrains Mono is already bundled.
No downloads, arbitrary CSS, URLs, settings keys, dependencies or authority changes.
The override changes HUD body/display font only. Code and explicitly monospace UI
retain their separate --font-mono stack. Apply font-family at .hud-root explicitly:
a child CSS variable change cannot retroactively alter an inherited body font.

- [x] RED backend: finite ID roundtrip, stale value coerces to theme, unknown fields
  refused, default unconfigured with font theme, partial old-client patch preserves
  font and existing fields, stale CAS write cannot overwrite a newer font.
- [x] GREEN backend: add font default/choices to core/appearance.py and bounded
  field in routers/preferences.py. Reuse atomic document merge and revisions.
- [x] RED/GREEN frontend: extend appearance normalization and existing journal,
  App data-font and setter, Palette fixed choices, scoped styles.css mapping.
  Test old replies/cache default without boot writes, palette request, unknown
  value fallback, offline reload/retry and independent concurrent field edits.
- [x] Browser: isolated real app/API plus current source build in a temporary output
  (do not modify shipped bundle). Verify computed UI font changes, code mono stays,
  another browser restores font, look changes retain override, offline choice/retry,
  prefix and cache clearing. No provider/network font calls.
- [x] Verify focused backend/frontend (one Vitest worker), both TypeScript programs,
  scoped Ruff/diff, required schema generation if stale, local Graft freshness, then
  commit only module source/tests/guide. Parent regenerates shipped assets/global evidence.

H135 remains partial until native mobile consumes appearance. This finite local
font set is not a claim of Hermes' complete curated font catalog or webfont loader.
Existing six appearance fields, CAS, offline journal, prefix cache and ambiguous
legacy motion handling remain unchanged. Rollback is one feature revert; stored
font metadata is inert for older clients.


Verification (2026-09-15): six new backend regressions observed RED before field support;
two frontend regressions observed RED before normalization/palette/root support.
Final 19 appearance backend tests and 20 appearance frontend tests passed (new delta
+6 backend, +2 frontend). Logs /tmp/font-backend-red.log, /tmp/font-frontend-red.log,
/tmp/font-backend-green.log, /tmp/font-frontend-green.log. Existing backend emits one
Starlette TestClient/httpx deprecation warning. Both TypeScript programs passed.
Two actual Chromium tests passed at root and /one, checking all five computed UI
fonts, computed code font invariance, fresh browser restoration, look/font independence,
offline retry and cache loss recovery (/tmp/font-browser.log). No remote font requests
were introduced. Browser source build is /tmp/nerva-font-web/v2; a temporary copy of
the existing isolated base-path fixture points its static mount and HERE to that
build (/tmp/nerva-font-server.py). Shipped assets remain untouched. The committed
browser config normally uses the original fixture after the integrator rebuilds.

Scoped Ruff and diff checks passed. Full baseline Bandit 1.9.4 over agents/scripts
passed (/tmp/font-bandit.log). Generated OpenAPI types using existing cached7.13.0
added exactly the two lines for the optional font field; no route change. Graft
frontend/src TypeScript graph was built and checked fresh in /tmp/nerva-font-graft;
no added/removed/changed/stale files. Deep semantic context intentionally not built.
No full frontend/backend claim; parent runs integration coverage and shipped build.

Review routing fix: dedicated appearance-fonts.spec.ts excluded from all five generic
Playwright project entries. Matrix collection contains no dedicated font cases;
dedicated config collects exactly two tests. E2E TypeScript check passed again.
