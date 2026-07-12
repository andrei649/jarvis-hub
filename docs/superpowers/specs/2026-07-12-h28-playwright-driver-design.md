# H28.1 Real Playwright Driver — Design

## Goal

Provide a real asynchronous Playwright host driver that can be injected into the
existing `GovernedBrowser`. Preserve `NullBrowserDriver` as the constructor default and
leave allowlist, SSRF, approval, classification, and stop-on-block behavior unchanged.

## Non-goals

- No autonomous browser planning or action-hierarchy router (H28.2).
- No bypass around `GovernedBrowser`; the driver is an actuator, not a policy layer.
- No bundled browser binary or mandatory Playwright runtime dependency.
- No persistent browser profile, ambient cookies, API endpoint, or HUD/mobile surface.
- No unpark-list change (H28.6).

## Host seam

Add `PlaywrightBrowserDriver` in `agents/core/browser_playwright.py`. Construction is
side-effect free. The first action may launch only when the caller explicitly passes
`host_enabled=True`; `from_env()` additionally requires `JARVIS_PLAYWRIGHT_HOST=1`.
Missing Python Playwright or browser binaries return a bounded, actionable host error.

The runtime remains optional because the project installs from `requirements-beta.txt`.
An owner who enables this host seam installs it explicitly with:

```text
pip install playwright
python -m playwright install chromium
```

This follows Playwright's official async-library lifecycle: `async_playwright().start()`,
browser launch, a fresh `browser.new_context(accept_downloads=True)`, one page, then
context/browser/Playwright shutdown. A new context avoids ambient cookies and cache.

## Action surface

- `navigate`: `page.goto`, returning bounded URL/title/status metadata.
- `extract`: locator-first `inner_text`, capped to a configured character budget.
- `screenshot`: returns bounded base64 PNG bytes; no implicit filesystem write.
- `wait`: selector wait or bounded timer wait.
- `click`, `type`, `submit`, `execute_js`, `upload`, `download`: direct Playwright
  primitives, reachable only after existing `GovernedBrowser` approval.
- `download`: requires an explicit download directory, sanitizes the suggested filename,
  and uses Playwright `expect_download()` + `save_as()` because context-close deletes
  temporary downloads.

## Safety

- Explicit host consent is checked before importing or starting Playwright.
- Only `chromium`, `firefox`, and `webkit` are accepted.
- Timeouts and extraction/screenshot sizes are bounded.
- Upload paths must exist; download destinations remain inside the configured directory.
- `close()` is idempotent and closes context before browser before Playwright.
- Startup failure cleans every partially-created resource and exposes no raw exception to
  `GovernedBrowser`, whose existing error redaction stays authoritative.

## Tests

Use an injected fake matching the official async API to pin calls and lifecycle without a
browser dependency. Cover host refusal, missing dependency, fresh context, all action
families, output bounds, filename/path safety, cleanup after partial startup, idempotent
close, and proof that off-list/risky actions are still blocked before the driver. Add an
opt-in live Chromium smoke test gated by `JARVIS_PLAYWRIGHT_LIVE=1`.

## Rollback

Remove the adapter and its tests. `GovernedBrowser` and `NullBrowserDriver` remain exactly
as before.
