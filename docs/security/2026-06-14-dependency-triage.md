# Dependency Vulnerability Triage — 2026-06-14

**Scope:** Dependabot reports **12 alerts** on `andrei649/jarvis-hub` default branch
(1 critical · 2 high · 6 moderate · 3 low). This document triages the dependency
surface against known advisories and assesses **real-world risk for this specific
deployment**.

> ## ⚠️ CAVEAT — manifest-derived, not live-alert-mapped
> There is **no Dependabot-alert MCP/API tool available in this environment**, so this
> triage was built by reading the repo's dependency **manifests + lockfiles** and
> cross-referencing my advisory knowledge (cutoff Jan 2026) with live web search.
> **The mapping below is best-effort.** It is *not* read from the live alert list, so the
> exact 12 packages/severities Dependabot is flagging may differ — in particular:
> - **pip has no lockfile in this repo.** Dependabot evaluates `requirements*.txt` by the
>   *lowest version the range admits* (the `>=` floor), not what you'd actually `pip install`
>   (which is the latest). So a "clean" floor can still be alerted on if a transitive dep
>   (e.g. `starlette` under `fastapi`) resolves low. Several of the 12 are almost certainly
>   pip-floor / transitive-Python alerts I can only infer.
> - **npm lockfiles resolve almost everything to patched versions** (see below), so most npm
>   alerts, if any, are **dev-only transitive** items. Dependabot counts dev deps too.
> To get the authoritative list, open
> `https://github.com/andrei649/jarvis-hub/security/dependabot` (or `gh api
> /repos/andrei649/jarvis-hub/dependabot/alerts`) and reconcile against this table.

---

## Threat model (why "real-risk-here" is mostly LOW)

Per `MOONSHOT.md` / `AGENTS.md` / `docs/ARCHITECTURE.md`: JARVIS is **local-first,
single-user / LAN**. The FastAPI app binds `127.0.0.1:8080`; admin/user routes are
**localhost-gated** (`_admin_guard` / `_user_guard`, HF-1 — only exposed on a network if you
explicitly set `JARVIS_USER_TOKEN`/`X-User-Token`). There is **no untrusted multi-tenant
exposure by default**. WorldView (`worldview/`) is a separate Next.js + Fastify OSINT stack
(ports 3000/4000), also operator-run. The mobile app (`mobile/`) is a personal client.

Consequences for triage:
- CVEs that need **untrusted network input** or a **multi-user/public server** → **LOW** real
  risk here (no such surface by default).
- CVEs in **dev-server tooling** (esbuild/vite serve, test harnesses) → **LOW** (dev-only, not
  shipped; the build output is what's vendored — see `frontend/package.json`).
- CVEs in **parsers that ingest external/untrusted data** (OSINT ingestion workers, email/web
  scraping, XML/HTML, the ingestion pipeline `agents/core/ingestion/`) → **higher** relative
  risk, because that data path is genuinely attacker-influenced.

---

## Summary table

> `current` = version resolved in the lockfile (npm) or the declared floor (pip, no lockfile).
> Items marked **PATCHED** are already at/above the fixed version — they should **not** be
> generating an alert at the resolved version, and are listed so you can confirm Dependabot
> isn't alerting on a stale graph.

| Package | Eco | Current → Fixed | Severity | Real-risk-here | Action |
|---|---|---|---|---|---|
| **starlette** (transitive via `fastapi>=0.136.3`) | pip | range admits <1.0.1 → **1.0.1** (CVE-2026-48710 "BadHost") | **Critical** | **Low–Med** | **Pin `starlette>=1.0.1`** (and bump fastapi to a release that requires it). Strongest critical candidate. |
| **esbuild** (root devDep, transitive of vite) | npm | **0.21.5 → 0.25.0** (GHSA-67mh-4wv8-2f99) | Moderate | **Low** | Bump root `vite`/esbuild; dev-server only. |
| **python-multipart** (transitive via fastapi forms) | pip | range may admit <0.0.18 → **0.0.18+** (ReDoS/part-flood DoS) | High/Mod | **Low** | Pin `python-multipart>=0.0.18` if it shows. |
| **urllib3** (transitive, if pulled by any pip dep) | pip | <2.6.3 → **2.6.3** (CVE-2025-66418/66471, CVE-2026-21441 decompression-bomb DoS) | Mod | **Low–Med** | Pin `urllib3>=2.6.3` only if it appears in the graph. |
| **aiokafka / websockets / httpx / pydantic / sgp4 / h3** (ingestion-workers floors) | pip | low `>=` floors | Low/Mod | **Low** | Raise floors to current for hygiene; no confirmed advisory at floor. |
| mapbox-gl | npm | **3.5.2** — no advisory found for 3.x | — | Low | No action (CVE-2022-38216 is old gl-*native*, not 3.x JS). |
| next | npm | **16.2.9** — PATCHED (RCE GHSA-9qr9-h5gf-34mp fixed 16.0.7; May-2026 batch fixed 16.2.6) | — | Low | No action; already past all known fixes. |
| react / react-dom (worldview) | npm | **19.2.7** — PATCHED (RSC DoS fixed 19.2.5/.6) | — | Low | No action. |
| react (mobile) | npm | **19.2.3** — affected range, but **RN, no `react-server-dom-*`** | (Mod) | **Low** | Optional bump to 19.2.6; RSC code path not present. |
| vite (root) | npm | **5.4.21** — PATCHED (CVE-2025-62522 fixed in 5.4.21) | — | Low | No action. |
| @xmldom/xmldom (mobile) | npm | **0.8.13 / 0.9.10** — PATCHED (CVE-2026-41672/3/4) | — | Low | No action. |
| protobufjs (worldview) | npm | **7.6.3** — PATCHED (>7.5.5) | — | Low | No action. |
| cryptography | pip | **>=48.0.1** — PATCHED (CVE-2026-39892 is <46.0.7) | — | Low | No action. |
| ws / send / serve-static / semver / minimatch (mobile transitive) | npm | all PATCHED | — | Low | No action. |

---

## Per-finding attack-path notes

### 1. CRITICAL — Starlette `CVE-2026-48710` ("BadHost") — via `fastapi`
- **What:** Starlette did not validate the HTTP `Host` header before using it to reconstruct
  `request.url`. A single malformed character lets an unauthenticated attacker bypass
  access controls keyed off the reconstructed URL/host. Fixed in **Starlette 1.0.1** (2026-05-21).
- **Where in repo:** `requirements.txt` / `requirements-beta.txt` pin `fastapi>=0.136.3` but **no
  explicit starlette pin and no lockfile**, so the resolved starlette is whatever fastapi's
  range allows. This is the most plausible source of the single **critical** alert.
- **Attack path here:** JARVIS binds `127.0.0.1` and gates admin/user routes; the bypass only
  matters if you **expose the HUD on a LAN** (via `JARVIS_USER_TOKEN`) and rely on
  host/URL-based gating. Default localhost-only → **Low**. If LAN-exposed → **Medium** (it's an
  access-control bypass). Treat as the top fix regardless because it's cheap and the severity
  is high upstream.

### 2. MODERATE — esbuild `GHSA-67mh-4wv8-2f99` (dev-server CORS) — root lockfile
- **What:** esbuild ≤0.24.2 sets `Access-Control-Allow-Origin: *` on its dev server, so any
  website you visit while the dev server runs can read your source. Fixed **0.25.0** (CVSS 5.3).
- **Where:** **root** `package-lock.json` resolves `esbuild 0.21.5` (a transitive dev dep of
  `vite 5.4.21`, used only by the HUD test tooling — `package.json` is `jarvis-hub-hud-tests`,
  dev-only; the HUD ships as **vendored scripts, no bundler**). `worldview/` and `worldview/mcp`
  already resolve esbuild **0.28.0** (patched).
- **Attack path here:** Requires a developer to (a) run the esbuild/vite dev server and (b)
  browse a malicious page concurrently. Not part of any shipped artifact. → **Low**.

### 3. HIGH/MOD — python-multipart DoS (ReDoS / unbounded parts) — via fastapi forms
- **What:** Older `python-multipart` had a Content-Type ReDoS (CVE-2024-24762, fixed 0.0.7) and
  an unbounded-parts OOM (CVE-2023-30798). FastAPI pulls it transitively when form/multipart
  endpoints exist (the voice STT endpoint posts a raw body, but other routes may use forms).
- **Attack path here:** Needs an attacker to POST crafted multipart to a reachable endpoint.
  Localhost-gated → **Low**. Pin `python-multipart>=0.0.18` if Dependabot lists it.

### 4. MOD — urllib3 decompression-bomb DoS (CVE-2025-66418 / 66471 / 2026-21441)
- **What:** urllib3 <2.6.3 can over-allocate on highly-compressed responses (DoS). Fixed **2.6.3**.
- **Where:** Not directly listed. `httpx` uses `httpcore` (not urllib3), so urllib3 only enters
  if another pip dep (e.g. a `requests`-using library) pulls it. Without a lockfile I can't
  confirm it's in the graph. If Dependabot flags it, the path is **outbound HTTP to a hostile
  server** (web/OSINT fetch in `plugins/websearch.py`, ingestion). That's a real external-data
  path → **Low–Medium**. Pin `urllib3>=2.6.3` if present.

### 5. LOW — ingestion-worker floors (`worldview/ingestion-workers/requirements.txt`)
- `aiokafka>=0.11`, `httpx>=0.27`, `websockets>=12`, `pydantic>=2.7`, `sgp4>=2.23`, `h3>=4.0`.
- No confirmed advisory at these floors. These workers **do ingest external OSINT** (ADS-B/AIS/
  TLE), so the parsers are the highest-value attack surface in the repo — but the named libs
  themselves have no current CVE at-floor. The likely Dependabot hits here, if any, are
  low-severity hygiene flags or transitive (e.g. a urllib3/certifi pull). → **Low**; raise
  floors when convenient.

### 6. Confirmed-PATCHED (listed to reconcile against a possibly-stale alert graph)
- `next 16.2.9` — past the RCE fix (16.0.7) **and** the May-2026 batch (16.2.6).
- `react/react-dom 19.2.7` (worldview) — past the RSC DoS fixes (19.2.5/.6).
- `vite 5.4.21` (root) — is itself the fix for CVE-2025-62522.
- `@xmldom/xmldom 0.8.13` & `0.9.10` (mobile) — both are fixed releases for CVE-2026-41672/3/4.
- `protobufjs 7.6.3` (worldview) — above the <=7.5.5 affected range.
- `cryptography>=48.0.1` — above the <46.0.7 affected range.
- `ws 7.5.11`/`8.21.0`, `send 0.19.2`, `serve-static 1.16.3`, `semver 6.3.1`, `minimatch 3.1.5`
  (mobile transitive) — all at/above their fix versions.
- `mapbox-gl 3.5.2` — no advisory found for the 3.x JS line (CVE-2022-38216 is gl-native).

If Dependabot is still alerting on any of these, it's likely scanning a **stale commit** or a
manifest range (not the resolved lock) — re-run/refresh the dependency graph.

---

## Prioritized recommendations

### Do now (cheap, meaningful)
1. **Pin `starlette>=1.0.1`** in `requirements.txt` + `requirements-beta.txt` (and bump
   `fastapi` to a release that depends on starlette ≥1.0.1). Clears the likely **critical**
   alert; closes a real (if low-probability-here) auth-control bypass before any LAN exposure.
2. **Bump root dev `vite`/`esbuild`** so esbuild resolves **≥0.25.0** (`npm i -D vite@latest`
   in the repo root, or add an `overrides: { "esbuild": ">=0.25.0" }`). Clears the moderate
   esbuild dev-server alert. Dev-only, zero shipped impact.
3. **Pin `python-multipart>=0.0.18` and `urllib3>=2.6.3`** *iff* the live alert list confirms
   them (they're transitive; only add the pin if they're actually in the graph and flagged).

### Low-risk-here — can wait / hygiene
4. Raise the loose floors in `worldview/ingestion-workers/requirements.txt`
   (`httpx>=0.28`, `websockets` to current, `pydantic` to current, `aiokafka` to current) to
   stop Dependabot floor-alerts and keep the OSINT parser surface current. No urgent CVE.
5. Optionally bump **mobile `react` 19.2.3 → 19.2.6** for parity, though the vulnerable
   `react-server-dom-*` packages are not used in React Native.

### Needs care (don't blind-bump)
6. **WorldView deck.gl/luma.gl pins are intentional** (`worldview/package.json` `overrides`):
   `@deck.gl/core/extensions/mesh-layers` pinned to `9.0.27` and the luma.gl stack to `9.0.15`,
   because `^9.0.15` floats to `9.3.x` which **renamed exports** and the `deckExtensionsShim`
   aliases `ClipExtension` against the pinned core. **Do not let Dependabot bump these** — an
   unpinned extensions copy hoisting to 9.3.x mismatches the 9.0.27 `Layer` class. None of
   these are flagged for a CVE; if a deck/luma alert ever appears, coordinate a whole-stack
   version bump, not a single-package bump. Keep Dependabot config ignoring this cluster.
7. The npm graph is mostly current; **don't mass-`npm audit fix --force`** on the worldview
   workspace — it can pull deck.gl/luma.gl off the pinned line. Apply per-package.

---

## How to reconcile with the live alerts (when a tool/`gh` is available)

```bash
gh api /repos/andrei649/jarvis-hub/dependabot/alerts \
  --jq '.[] | select(.state=="open") |
        {pkg:.dependency.package.name, eco:.dependency.package.ecosystem,
         sev:.security_advisory.severity, ghsa:.security_advisory.ghsa_id,
         vuln:.security_vulnerability.vulnerable_version_range,
         fix:.security_vulnerability.first_patched_version.identifier,
         manifest:.dependency.manifest_path}'
```
Map each row to the table above; anything not covered here is a transitive item the
manifests don't surface directly (expected for a no-Python-lockfile repo).
