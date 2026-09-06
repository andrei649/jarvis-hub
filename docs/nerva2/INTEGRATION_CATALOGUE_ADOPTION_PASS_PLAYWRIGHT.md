# Integration catalogue §5 — Tier A adoption-grade pass: Playwright

> First execution of the standing recommendation in
> [`INTEGRATION_CATALOGUE_RFC.md`](INTEGRATION_CATALOGUE_RFC.md) §5: take **one** Tier A
> candidate through the full primary-source pass and the six additive §4 gates before
> touching a second. This pass is evidence, not adoption: it moves the Playwright row
> from `PARKED` (provider surface) to `PASS_RECORDED — promotion candidate`, and it
> changes no dependency, pin, manifest, provider, route, runtime or authority.

- Date: 2026-09-06 · Program #757 · Catalogue precursor PR #821 (`ccc36e8`) · #805-adjacent
- Candidate: **Playwright** (Tier A, class `reuse`, "already in-repo")
- Why Playwright and not the MCP server surface §5 named "most plausible": the pass has to be
  *adoption-grade*, i.e. primary artifacts readable and a native fallback provable. Playwright
  is the only Tier A row whose primary artifacts are already inside this checkout (licence
  file, exact resolved version, runtime seam, tests), so the pass can be completed without a
  network read that this build environment cannot make. The MCP-server pass stays next.

## Evidence level per claim

| Claim | Level | Where |
|---|---|---|
| Licence is Apache-2.0 | **Primary (read)** — `frontend/node_modules/playwright-core/LICENSE` and `frontend/node_modules/@playwright/test/LICENSE`, both 202 lines, SHA-256 `45873d00a0dd243596deb4aa23b2493b3d1f0671921bf2538ea431d7380220eb`; `playwright-core/package.json` declares `"license": "Apache-2.0"` and repository `github.com/microsoft/playwright` | in-checkout vendored package |
| Exact adoption pin (Node) | **In-repository fact** — `frontend/package.json` requests `@playwright/test ^1.62.1`; `frontend/package-lock.json` resolves `playwright 1.62.1` / `playwright-core 1.62.1` | lockfile |
| Python runtime pin | **In-repository fact (absence)** — no `playwright` entry in any `requirements*.txt` / `requirements*.lock`; the Python driver imports it lazily and refuses with `PlaywrightUnavailable` on `ImportError` (`agents/core/browser_playwright.py:130`) | lock files, driver |
| Host gate | **In-repository fact** — `JARVIS_PLAYWRIGHT_HOST` (`agents/core/operator_router.py:360`) and `host_enabled=True` + a per-request URL guard before any browser starts (`browser_playwright.py:_ensure_started`) | driver, router |
| Governance | **In-repository fact** — `GovernedBrowser` egress allowlist + SSRF filter, read-only vs risky step taxonomy, mutating steps through the approval queue (`agents/core/browser_agent.py`) | governance layer |
| Tests | **In-repository fact** — `tests/test_h28_playwright_driver.py` (10 hermetic tests with a fake Playwright runtime); reality probe `_probe_operator_browser_playwright_governed` in `agents/core/observability/operator_reality.py` | tests |
| Upstream release cadence, CVE history, API-stability policy | **Not read** — requires a network primary read of the upstream repository; recorded as the open item of gate 1 | — |

No external project was installed, run or benchmarked for this pass. The Python
`playwright` package is not present in the build environment
(`ModuleNotFoundError`), which is itself the honest state gate 6 relies on.

## #805 minimum contract fields

| Field | Content |
|---|---|
| Owner outcome | Deterministic browser control for governed operator tasks (H28) that today refuses honestly on a default install. |
| Alternatives | Stagehand (Tier B, TypeScript sidecar — parked), Browser Use (Tier B — parked), keep `NullBrowserDriver` only (status quo). |
| Evidence | Table above; every row labelled primary / in-repository / not read. |
| Reuse / build / reject | **Reuse** the existing driver seam; nothing is built for this pass; the *promotion* to a governed capability is the only open decision. |
| Authority / security / privacy / retention | Authority unchanged: every mutating step is an approval-queue item; navigation cannot leave the allowlist even with approval; screenshots and extracts are bounded (`max_screenshot_bytes`, `max_extract_chars`); downloads land only inside `download_dir`. No cloud hop: the browser runs on the owner host. |
| Baseline and falsification | Baseline = `NullBrowserDriver` (records calls, actuates nothing). Falsification: a governed run that reaches a non-allowlisted host, or a mutating step that executes without a queue decision, fails the pass. Both are already asserted hermetically (`test_governed_browser_blocks_before_real_driver_and_null_default_is_unchanged`, `test_governed_policy_blocks_redirects_and_subresources_inside_playwright`). |
| Isolation | Fresh browser context per driver, headless by default, per-request URL guard, no shared profile. |
| Migration and rollback | None needed: unset `JARVIS_PLAYWRIGHT_HOST` (or uninstall the Python package) and the seam returns to `NullBrowserDriver` with a named refusal. |
| Decision record | See "Decision" below; reviewer: integrator of the 2026-09-06 Nerva PR; reconsideration trigger: the upstream primary read (gate 1 open item) or an E9 measurement result. |

## The six additive §4 gates

| # | Gate | Result | Evidence / what is still owed |
|---|---|---|---|
| 1 | Primary-source pass (LICENSE, exact pin, interface inventory, dependency surface) | **PARTIAL** | LICENSE read (digest above); Node pin exact (1.62.1); interface inventory = the driver's `navigate / extract / screenshot / wait / click / type / submit / download / execute_js / upload` primitives over `playwright.async_api`; dependency surface = `playwright` (Python, optional, unpinned) + `playwright-core` 1.62.1 (Node, dev-only, e2e lane). **Owed:** a network primary read of upstream release/security policy and an exact Python pin decision. |
| 2 | Updater safety, then a manifest entry | **NOT APPLICABLE YET** | Playwright is a package dependency (Dependabot lane), not a vendored / doc-pinned source, so `.github/third-party-manifest.json` enrolment is not the right control; if a Python pin is adopted it goes into `requirements*.lock` with hashes, never into the updater manifest. |
| 3 | `nerva.capability.v1` declaration | **EXISTS AS A TOOL, NOT AS A PROVIDER RECORD** | The router publishes `tool:browser_run` (`operator_router.py`) with availability bound to the real host gate; there is no separate provider descriptor with typed inputs/outputs, privacy class, verifier and rollback. That descriptor is the promotion work, not this pass. |
| 4 | Ultron mediation | **PASS (hermetic)** | Mutating browser steps are approval-queue items in `GovernedBrowser`; off-allowlist navigation is hard-blocked before the driver is touched; no self-authorisation path exists in the driver. `grants_authority=false` is implicit today and must become an explicit immutable field on the provider record in gate 3. |
| 5 | E9 measurement | **NOT MEASURED** | No benchmark compares the Playwright route with the native `NullBrowserDriver` baseline or with an API route; every quality/latency dimension is `not_measured`. |
| 6 | Native fallback | **PASS (hermetic + build-environment fact)** | With the package absent or the flag unset, `browser_run` reports unavailable and the seam refuses with `PlaywrightUnavailable` / `PlaywrightHostDisabled`; the rest of Nerva keeps working (proven by this build environment, where the package is absent and the backend suite runs). |

## Decision

- Catalogue row: **Playwright** `PARKED (provider surface)` → **`PASS_RECORDED — promotion candidate`**.
  It is *not* adopted, promoted or enrolled by this document.
- Promotion to a governed provider capability requires, in order: close gate 1's owed network
  read and pin the Python package with hashes; write the gate 3 provider record with an explicit
  immutable `grants_authority=false`; run one E9 comparison (gate 5). Only then may a
  `nerva.capability.v1` promotion PR be opened, and it still crosses the approval queue for any
  mutating step at runtime.
- Next Tier A pass: the MCP server surface (§5's own first choice), which needs a network primary
  read this build environment could not make.

## What this document is not

- not a dependency, pin, third-party-manifest, provider, adapter, route or runtime change;
- not an owner-host proof — the "installed Playwright Chromium" line of `docs/MANUAL_TESTING.md`
  (H28) stays owner-run;
- not a #805 control-slice deliverable, and not the Hermes enrolment discussed in E8.1a–E8.1d.
