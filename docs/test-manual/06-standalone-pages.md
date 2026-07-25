# 06. Standalone pages, legacy HUD, WorldView & desktop shell

> **Scope.** Every browser-reachable Nerva surface that is **not** the React v2 Console: the Mission
> Control cockpit (`GET /mission-control` + `agents/web/mission_control.html`), the Neural Mesh page
> (`GET /brain` + `agents/web/brain.html`), the **legacy static HUD** served at `GET /v1` from
> `agents/web/templates/index.html` + `agents/web/static/*.js`, the PWA layer
> (`/sw.js`, `/static/manifest.json`), the **embeddable chat widget** (`/api/admin/widgets` →
> `/api/widget/{token}`), the **WorldView** 4D stack (`worldview/`) together with the HUD's world
> surfaces (`frontend/src/modes_world.tsx`, `world_app.tsx`) and the Signal Layer at `:8787`, and the
> **Tauri desktop shell** (`desktop/src-tauri`) + the PyO3 crate (`rust/jarvis_native`). It also owns a
> deliberate, novel **legacy-vs-v2 divergence sweep** (§06.8) — run 1's false kill-switch alarm was
> exactly a `tools.js`-vs-v2-bundle divergence, and this section makes that class of bug systematic.
> **Deliberately left to siblings:** the v2 Console's own modes, panels and chat (nav rail, Projects,
> Trust, Activity timeline), agent chat quality / fabrication grading, the mobile Expo app, autonomy
> semantics, and the AI-OS host operators. Where a check here touches those, it does so only as a
> **cross-validation source** and cross-references by section number.
>
> **Prereqs for this whole section.** A running hub on `http://127.0.0.1:8080` (`python serve.py` or
> `START.bat`); Chrome/Chromium with DevTools; `curl` + `python -m json.tool`. Model backend and
> external services are **optional** — most of this section is specifically about what these pages show
> when they are absent. Two token values you will set and unset repeatedly: `JARVIS_ADMIN_TOKEN` and
> `JARVIS_USER_TOKEN`. For §06.11 you additionally need Docker + Node (`worldview/quickstart.sh`); for
> §06.12 the Rust/Tauri toolchain (most of §06.12 is designed to run *without* it).
>
> **Time.** ~4 h 30 m end to end for one tester: 20 m §06.1 · 50 m §06.2–06.5 · 25 m §06.6 ·
> 40 m §06.7 · 35 m §06.8 · 30 m §06.9 · 20 m §06.10 · 55 m §06.11 (mostly Docker waiting) ·
> 15 m §06.12 · 20 m §06.X–06.Y. Add ~40 m if you also run the WorldView `--seed-live` path.

Shared legend applies (🔑 secret/service · 🤖 model backend · 👁 visual · 🖥 owner hardware ·
🌐 second LAN device · ⏱ day boundary/restart/soak · ♿ accessibility · Auto: ✅/⚠️/❌ ·
severity BLOCKER/MAJOR/MINOR/COSMETIC).

---

## 06.1 Reachability, auth tiers & page shells

The four standalone shells and their guard tiers. Tiers are from `tests/_snapshots/route_auth.json`.
**Critical asymmetry to internalise before you start:** `GET /` , `/v1`, `/v2`, `/admin`, `/sw.js` are
**open** (the shell loads, then its JS supplies tokens), but `GET /mission-control` and `GET /brain`
are **user**-tier (`agents/core/routers/swarm.py:279`, `brain.py:177`). A browser *navigation* cannot
add an `X-User-Token` header, so with `JARVIS_USER_TOKEN` set these two pages cannot be opened at all.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-001 | Mission Control shell serves | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mission-control` (no tokens set) | `200`, `content-type: text/html` | BLOCKER | ✅tests/test_swarm_summary.py::test_http_page_and_summary |
| PGE-002 | Mission Control feed serves | `curl -s http://127.0.0.1:8080/api/swarm/summary \| python -m json.tool \| head -30` | top-level keys exactly: `generated_at, initialized, halted, agents, activity, autonomy, presence, missions, workflows, subagents, a2a, dev_locks` | BLOCKER | ✅tests/test_swarm_summary.py:25 |
| PGE-003 | Brain shell serves | `curl -s -o /dev/null -w "%{http_code}\n" .../brain` | `200` | MAJOR | ✅tests/test_brain_summary.py::test_route_registered |
| PGE-004 | Brain feed serves | `curl -s ".../api/brain/summary?range=all" \| python -m json.tool \| head` | keys incl. `range, events, sessions, tokens_in, tokens_out, loc_added, cost_eur, by_agent, by_model, by_harness, recent, rtk` | MAJOR | ✅tests/test_brain_summary.py |
| PGE-005 | Legacy HUD serves at /v1 | open `http://127.0.0.1:8080/v1` | page title **`JARVIS HUB`**; the v2 HUD at `/` has title **`NERVA · HUD`** — two *different* shells | MAJOR | ✅tests/test_endpoints.py::test_v1_serves_legacy_hud |
| PGE-006 | Legacy shell is `templates/index.html`, not `web/index.html` | DevTools → Network → the `/v1` document; check the `<script>` list | exactly **16** `<script src>` tags — `auth.js` first, `app.js` last, of which **14** carry `?v=9.9.9` (the two React bundles carry no query); **no** inline HUD markup. (`agents/web/index.html` is a 402-line orphan served by no route — see Open gaps.) | MINOR | ❌ |
| PGE-007 | Service worker serves | `curl -sI .../sw.js \| head -5` | `200`, `content-type: application/javascript` | MAJOR | ⚠️tests/test_hud_v2_parity.py:37 |
| PGE-008 | Manifest serves (StaticFiles mount, **not** a route) | `curl -s .../static/manifest.json \| python -m json.tool` | `name: "Jarvis Hub"`, `start_url:"/"`, `display:"standalone"`, 3 SVG icons. Mount is declared at `agents/web.py:715`; it deliberately has **no** entry in `route_surface.json` | MINOR | ❌ |
| PGE-009 | Security headers on every standalone shell | `for p in / /v1 /mission-control /brain /admin; do curl -sI .../$p \| grep -iE "x-frame\|x-content\|referrer\|content-security"; done` | each: `X-Frame-Options: SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, a CSP with `object-src 'none'` and `frame-ancestors 'self'` | MAJOR | ✅tests/test_hud_security_headers.py |
| PGE-010 | Feed responses are uncacheable | `curl -sI .../api/swarm/summary \| grep -i cache` | `Cache-Control: no-cache, no-store, must-revalidate` (`web_helpers.nocache_json`) | MINOR | ❌ |
| PGE-011 | favicon | `curl -sI .../favicon.ico \| grep -i content-type` | `image/svg+xml` (an `.ico` path serving SVG — intentional, `agents/web.py:726`) | COSMETIC | ❌ |

#### PGE-012 — Standalone pages are unopenable once a user token is set  🌐
- **Surface:** `GET /mission-control`, `GET /brain`  ·  **Tier:** user  ·  **Auto:** ⚠️tests/test_swarm_summary.py::test_routes_are_user_guarded (asserts the guard exists, not the browser consequence)
- **Why it matters:** the §2 setup in `docs/COWORK_QA_RUNBOOK.md` tells the tester to
  `export JARVIS_USER_TOKEN=devuser`. If that locks the owner out of the two newest pages, every
  Mission Control case below is untestable in the documented configuration.
- **Prereq:** restart the server with `JARVIS_USER_TOKEN=devuser` in the environment.
- **Steps:** 1) `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mission-control` →
  note the code. 2) Repeat with `-H "X-User-Token: devuser"`. 3) Now open
  `http://127.0.0.1:8080/mission-control` in Chrome **on the same machine** (localhost). 4) Same for
  `/brain`. 5) Compare against `http://127.0.0.1:8080/` (v2) and `/v1`, which have no guard.
- **Expected:** step 1 → `401` with body `{"detail":"user token required"}`; step 2 → `200`.
  `_user_guard` (`agents/web.py:192-205`) takes the `if USER_TOKEN:` branch **before** any localhost
  bypass, so step 3/4 must be judged on what the browser actually renders.
- **Also acceptable (honest degradation):** the browser shows a plain `{"detail":"user token
  required"}` JSON body — ugly but truthful. `/` and `/v1` still load and prompt for the token via
  `agents/web/static/auth.js` (legacy) / the v2 token field.
- **FAIL if:** the page renders its chrome (NERVA // MISSION CONTROL header, empty panels) with no
  indication that the feed is unauthorized → **MAJOR** (a green-looking cockpit over a 401 feed).
  Also **MAJOR** if the 401 body leaks a stack trace.
- **Evidence to capture:** both curl status lines + a screenshot of what Chrome shows for
  `/mission-control` with the token set, and again with it unset.

---

## 06.2 Mission Control — the header chip row

Seven chips + one token input, all in the sticky header (`mission_control.html:70-79`). Each is
rendered by `setChip()`/`textContent` from `state.sum` on a **2 s** `setInterval` (`:183-185`).
Every check below is a **cross-validation**: chip text vs `GET /api/swarm/summary` vs the chip's own
underlying endpoint. A chip that agrees with only one of the three is the bug this group exists to
catch.

| ID | Chip / element | Do | Expect (exact text) | Fail | Auto |
|----|----------------|----|---------------------|------|------|
| PGE-013 | `SYSTEM` | open the page with the server up | LED green, **`SYSTEM LIVE`** (glow). `summary.initialized == true` | MAJOR | ⚠️tests/test_swarm_summary.py |
| PGE-014 | `SYSTEM` while booting | reload during the first ~2 s after `serve.py` starts | grey LED, **`SYSTEM BOOTING`** (`initialized:false`), never LIVE | MINOR | ❌ |
| PGE-015 | `SYSTEM` halted | `curl -X POST .../api/security/kill-switch -H "X-Admin-Token: $T" -H 'Content-Type: application/json' -d '{"engage":true,"scope":"global","reason":"qa"}'` then watch ≤2 s | red LED, **`SYSTEM HALTED`**; `summary.halted == true`; `GET /api/security/kill-switch` → `{"global":true,…}`. Disengage → back to `SYSTEM LIVE` | **BLOCKER** (safety display) | ⚠️tests/test_swarm_summary.py:176 |
| PGE-016 | `AUTONOMY <mode>` | compare chip against `GET /autonomy/status` (admin) and `summary.autonomy.mode` | uppercase mode: `AUTONOMY AUTO` (green) / `AUTONOMY ASK` (**amber**) / `AUTONOMY OFF` (grey, no glow) | MAJOR | ✅tests/test_swarm_summary.py:124 |
| PGE-017 | `INTERRUPTS n/m` | compare against `GET /api/metrics/north-star` → `interrupt_budget` | `INTERRUPTS 4/4` on a quiet day; the two numbers must match `remaining`/`per_day`. With no budget object: literal `INTERRUPTS —` | MAJOR | ✅tests/test_swarm_summary.py:124 |
| PGE-018 | `A2A OFF` | with `JARVIS_A2A_ENABLED` unset | literal **`A2A OFF`**; `/.well-known/agent-card` 404s (see §on interop) | MINOR | ⚠️tests/test_swarm_summary.py |
| PGE-019 | `A2A ON · n PENDING` | enable A2A, allowlist a peer, post one signed task | `A2A ON · 1 PENDING`; `n` equals `len(GET /api/a2a/inbox?status=pending .inbox)` | MAJOR | ⚠️ |
| PGE-020 | `ADMIN` (unknown) | fresh page, `hud.admin_token` empty, admin **not** configured (localhost bypass) | grey LED, literal **`ADMIN`** — `state.adminOk` stays `null` because the localhost bypass returns 200 and sets it `true`; on a 503 during boot it stays `null` | MINOR | ❌ |
| PGE-021 | `ADMIN LINKED` | type a valid admin token in the top-right field, press Tab/Enter (the `change` event) | green glow, **`ADMIN LINKED`**; `localStorage['hud.admin_token']` now holds it | MAJOR | ❌ |
| PGE-022 | `ADMIN LOCKED` | set `JARVIS_ADMIN_TOKEN`, put a **wrong** value in the field, reload | amber LED, **`ADMIN LOCKED`**, and the approvals card gains the amber line `ADMIN LOCKED — enter the admin token (top right) to act on approvals`. Polling of `/autonomy/approvals` must then **stop** (`pollAdmin` early-returns while `adminOk===false`) — confirm in DevTools Network that no further `/autonomy/approvals` requests fire until you change the field | MAJOR | ❌ |
| PGE-023 | `FEED` healthy | steady state | blinking green LED, literal **`FEED`** | MINOR | ❌ |
| PGE-024 | `STALE FEED` | stop the server (Ctrl-C), watch ~8 s | after **3** consecutive failures the LED turns red and the text becomes **`STALE FEED`**; the rest of the page keeps its last values (frozen, not blanked) | MAJOR | ❌ |
| PGE-025 | token input is a password field | inspect `#tokIn` | `type="password"`, placeholder `admin token`, `title` mentions `X-Admin-Token — stored locally (hud.admin_token)`; the value must not be echoed in plaintext | MINOR | ❌ |

#### PGE-026 — The OWNER presence chip, all five states  ⏱
- **Surface:** `#cPresence` (`mission_control.html:74`, logic `:230-239`) · `GET/POST /api/presence/owner` · **Tier:** GET **user**, POST **admin** · **Auto:** ✅tests/test_h34_2_presence.py
- **Why it matters:** this chip is the only UI that tells the owner whether decision cards are being
  fanned out to phone channels. A wrong reading either hides escalation or implies escalation that
  isn't happening.
- **Prereq:** `JARVIS_ADMIN_TOKEN` set and entered in the page's token field. No host daemon.
- **Steps:**
  1. **Never reported.** Fresh server, no POST. Read the chip and `curl -s .../api/presence/owner`.
  2. **Present.** `curl -s -X POST .../api/presence/owner -H "X-Admin-Token: $T" -H 'Content-Type: application/json' -d '{"state":"present","source":"manual-qa"}'`
  3. **Idle.** Same with `{"state":"idle","source":"manual-qa","idle_seconds":300}`.
  4. **Away.** Same with `{"state":"away","source":"manual-qa","idle_seconds":900}`.
  5. **OS alias.** Same with `{"state":"locked","source":"manual-qa"}` — `locked` is an alias for `away`
     (`agents/core/autonomy/presence.py:_ALIASES`).
  6. **Stale.** Wait out the TTL (`ttl_seconds` in the GET body; default **900 s** = 15 min ⏱) without
     re-reporting, then read the chip again.
  7. **Rejected state.** `{"state":"banana"}` → check status code and body.
- **Expected:** 1) grey LED, literal **`OWNER —`** (because `presence.ever_reported` is `false`), and
  `GET` returns `{"state":"unknown", …, "stale":true, "away":false, "ever_reported":false}`.
  2) green-ish LED, **`OWNER PRESENT`**. 3) grey-green LED, **`OWNER IDLE`** with **no** suffix
  (`idle_is_away` defaults false). 4) **amber** LED **with glow**, text **`OWNER AWAY · AWAY→ESC`**;
  GET shows `away:true`. 5) identical to 4 (`state` normalises to `away`). 6) LED grey, text
  **`OWNER AWAY · STALE`** and GET shows `stale:true, away:false` — a dead daemon must read as
  *not away*. 7) **422** with the static body `{"error":"unsupported presence state"}` (or equivalent
  static message from `error_json`) and **no traceback**.
- **Also acceptable (honest degradation):** if the orchestrator has no `owner_presence`, `GET` returns
  **503** `{"error":"presence not available"}` and the chip stays `OWNER —`.
- **FAIL if:** the chip shows `OWNER AWAY · AWAY→ESC` for a **stale** signal → **MAJOR** (implies
  escalation is armed when `is_away()` is false); or the 422 body contains a stack trace → **MAJOR**;
  or the POST succeeds without an admin token → **BLOCKER**.
- **Evidence to capture:** one screenshot per state (6 frames) plus the matching GET JSON.

#### PGE-027 — Presence POST/GET tier enforcement  🌐
- **Surface:** `/api/presence/owner` · **Tier:** GET user / POST admin · **Auto:** ✅tests/test_h34_2_presence.py, ✅tests/test_route_auth_matrix.py
- **Steps:** 1) With `JARVIS_ADMIN_TOKEN` set, `POST` with **no** header. 2) `POST` with
  `X-User-Token` only. 3) `GET` with no header from localhost with `JARVIS_USER_TOKEN` **unset**.
  4) `GET` from a second LAN device with no token 🌐.
- **Expected:** 1) `401 admin token required`. 2) `401` (a user credential does **not** satisfy
  `_admin_guard`). 3) `200`. 4) `403` with `user routes disabled from network — set JARVIS_USER_TOKEN…`.
- **FAIL if:** 1 or 2 return 200 → **BLOCKER**.

---

## 06.3 Mission Control — swarm map & live activity

#### PGE-028 — Swarm map renders the real roster, not a fixed ring  👁
- **Surface:** `#swarm` canvas (`mission_control.html:427-532`) · **Tier:** user · **Auto:** ⚠️tests/test_swarm_summary.py::test_roster_seeded_and_activity_attributed
- **Why it matters:** the map is the page's hero. A hard-coded ring would be seed data dressed as live.
- **Steps:** 1) Count the labelled green dots on the inner ring. 2)
  `curl -s .../api/swarm/summary | python -c "import json,sys;d=json.load(sys.stdin);print(len(d['agents']));print([a['id'] for a in d['agents']])"`.
  3) Compare with `curl -s .../status | python -c "import json,sys;print(json.load(sys.stdin)['agents_total'])"`.
  4) Click one dot.
- **Expected:** the ring holds `min(len(summary.agents), 24)` nodes (`layout()` slices to 24) with the
  **same ids**, `agents_total` = 17 on a stock roster. The click opens `#nodeCard` (top-right, 250 px)
  titled with the agent id and a body of exactly five lines: `model: … / events: N / tokens out: N /
  cost: N € / last: <local time or "idle">`. Clicking the **core** node or empty space hides the card.
- **Also acceptable:** an agent with no traces shows `events: 0`, `tokens out: 0`, `cost: 0 €`,
  `last: idle` and a small un-glowing dot.
- **FAIL if:** node ids don't match the feed, or the count is a constant unrelated to the roster →
  **MAJOR**. If a node reports non-zero tokens with an empty `GET /api/traces` → **BLOCKER**
  (fabricated telemetry).
- **Evidence:** screenshot of the map + the two id lists side by side.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-029 | Map legend | read bottom-left of the map panel | four items: `core` (bright), `agent` (green), `dev agent` (light blue `#9ad7ff`), `stale lock` (amber) | COSMETIC | ❌ |
| PGE-030 | Map caption | read top-left | `◇ SWARM MAP` + `inner ring · cabinet agents   outer arc · dev swarm` | COSMETIC | ❌ |
| PGE-031 | Active-agent glow | send a chat turn, watch the map within 2 s | the routed agent's dot brightens (`glow` when `last_ts` is <60 000 ms old) and its edge to the core thickens | MINOR | ❌ |
| PGE-032 | Activity pulse | send a second turn | a travelling dot animates core→agent exactly once per increment of that agent's `events` counter (`state.prevEvents` diff) | COSMETIC | ❌ |
| PGE-033 | Node radius scales with events | run ~20 turns on one agent | its radius grows `5 + min(7, log2(events+1))` — visibly larger than idle peers, never larger than ~12 px | COSMETIC | ❌ |
| PGE-034 | Window resize | drag the browser window narrower and wider | canvas re-scales with `devicePixelRatio`, labels stay legible, nothing clips outside the panel | MINOR | ❌ |
| PGE-035 | LIVE ACTIVITY empty state | fresh server, zero traffic | `▶ LIVE ACTIVITY  0 EVENTS` and the body reads exactly `no traffic yet — the swarm is quiet` | MAJOR | ❌ |
| PGE-036 | LIVE ACTIVITY row shape | after ≥1 chat turn | one row per trace: `HH:MM:SS` · agent id · intent-or-channel · model (truncated to 22 chars) · `N tk` right-aligned. Failed turns show the token count in **red** (`ok:false`) | MAJOR | ⚠️tests/test_swarm_summary.py::test_activity_capped_at_60 |
| PGE-037 | Activity cap | generate >60 turns | header counts at most `60 EVENTS`; `_ACTIVITY_CAP = 60` in `swarm.py:51` | MINOR | ✅tests/test_swarm_summary.py:111 |
| PGE-038 | **No user text in the feed** | send a chat turn containing the sentinel `PGE-038-SECRET-STRING`, then `curl -s .../api/swarm/summary \| grep -c PGE-038-SECRET-STRING` | `0`. The tracer's `text_preview` field exists (`observability/tracer.py:114`) but `swarm.py` deliberately does not copy it. Any hit is a privacy leak | **MAJOR** | ⚠️tests/test_swarm_summary.py |
| PGE-039 | Activity order | after several turns | newest first (the tracer is already newest-first; the page does not re-sort) | MINOR | ❌ |

---

## 06.4 Mission Control — approvals, the payload-free invariant, HITL

This is the highest-value group on the page: it is where governance is *displayed*, and where run 1's
lesson (compare a chat claim against a correctly grounded widget) becomes compare-the-card-against-
`/autonomy/approvals`-against-the-audit-log.

#### PGE-040 — Approvals card in **admin** mode  🔑
- **Surface:** `#approvals` (`mission_control.html:292-322`) · `GET /autonomy/approvals` **admin** · **Auto:** ⚠️tests/test_swarm_summary.py:124
- **Prereq:** `JARVIS_ADMIN_TOKEN` set + entered in the page field. At least one pending decision of
  each kind — create them with `POST /autonomy/tasks` (admin) or let the observer propose one.
- **Steps:** 1) Read the card. 2) `curl -s .../autonomy/approvals -H "X-Admin-Token: $T" | python -m json.tool`.
  3) Compare the header count, the section order, and each row.
- **Expected:** header `◉ APPROVALS  <n> PENDING` where `n == counts.total`. If any irreversible items
  exist, a **red** sub-header `NEEDS SCRUTINY — IRREVERSIBLE` **first**, then those rows, then a plain
  `REVERSIBLE` sub-header and its rows. Each row = a tag, the agent id, the title (ellipsised, `title=`
  tooltip is the task `kind`), then three buttons **`ACCEPT`** (green) / **`DEFER`** (amber) /
  **`REJECT`** (red). Tag text is literally `REVERSIBLE` (plain) or `IRREVERSIBLE` (red class `bad`).
- **Also acceptable:** with nothing pending, the body is exactly
  `approval queue clear — nothing waits on you` and the header reads `0 PENDING`.
- **FAIL if:** a task body, draft text, tool result, file path or payload field appears anywhere in the
  card → **MAJOR**; if a row shows `IRREVERSIBLE` while `/autonomy/approvals` puts it in `reversible`
  (or vice versa) → **BLOCKER** (governance display lying about irreversibility).
- **Evidence:** screenshot + the pretty-printed `/autonomy/approvals` JSON.

#### PGE-041 — Approvals card **degrades to counts** with no admin token
- **Surface:** same card, `state.adminOk === false` branch (`:311-321`) · **Auto:** ✅tests/test_swarm_summary.py:124 (whitelist), ❌ (rendering)
- **Why it matters:** the runbook's explicit requirement — tokenless must *degrade*, not error and not
  hide.
- **Steps:** 1) Clear the token field (empty string) and reload with `JARVIS_ADMIN_TOKEN` **set** on
  the server. 2) Read the card. 3) `curl -s .../api/swarm/summary | python -c "import json,sys;a=json.load(sys.stdin)['autonomy'];print(a['pending_count']);print(json.dumps(a['pending_preview'],indent=1))"`.
- **Expected:** header shows `<pending_count> PENDING` — the **same number** as admin mode. The amber
  line `ADMIN LOCKED — enter the admin token (top right) to act on approvals`. Then one row per
  preview item, **without** ACCEPT/DEFER/REJECT buttons. Because `_PREVIEW_FIELDS`
  (`swarm.py:140`) is exactly `("id","title","agent","kind","risk_tier","status","created_at")` and
  carries **no** `reversible`/`tier_name`, each row's tag falls back to `"T" + risk_tier` in the amber
  `warn` style — i.e. you should see **`T0` / `T1` / `T2` / `T3`**, never `REVERSIBLE`/`IRREVERSIBLE`.
  `pending_preview` is capped at **10** items while `pending_count` is the true total.
- **Also acceptable:** nothing pending → `0 PENDING` + `approval queue clear — nothing waits on you`
  *plus* the ADMIN LOCKED line.
- **FAIL if:** the card shows an error/blank/spinner instead of counts → **MAJOR**; if the preview
  carries any field outside the seven whitelisted ones → **MAJOR**; if the count differs from admin
  mode → **MAJOR** (two truths for one queue).
- **Evidence:** both screenshots (admin vs tokenless) + the preview JSON.

#### PGE-042 — Payload-free invariant, measured on the wire
- **Surface:** `GET /api/swarm/summary` (**user** tier) · **Auto:** ✅tests/test_swarm_summary.py:124 for `autonomy.pending_preview` only
- **Why it matters:** the runbook states the page is payload-free "by design". The *page* is; the
  **feed** is only partly. This check is written to find that.
- **Prereq:** produce three kinds of state first: (a) one pending decision with a non-trivial payload,
  (b) one **mission** with at least one finished step (`POST /api/missions`, `…/start`,
  `…/steps/0/finish`), (c) one **workflow run** (`POST /api/workflows/run`).
- **Steps:**
  ```bash
  curl -s http://127.0.0.1:8080/api/swarm/summary > /tmp/pge042.json
  python - <<'EOF'
  import json; d=json.load(open('/tmp/pge042.json'))
  print("preview fields:", {k for r in d['autonomy']['pending_preview'] for k in r})
  print("mission keys  :", sorted(d['missions'][0]) if d['missions'] else "none")
  print("plan entries  :", d['missions'][0].get('plan') if d['missions'] else "none")
  print("wf run keys   :", sorted(d['workflows']['runs'][0]) if d['workflows']['runs'] else "none")
  print("wf step keys  :", sorted(d['workflows']['runs'][0]['steps'][0]) if d['workflows']['runs'] and d['workflows']['runs'][0].get('steps') else "none")
  EOF
  ```
- **Expected (whitelisted part):** `preview fields` is exactly
  `{'id','title','agent','kind','risk_tier','status','created_at'}` — no `payload`, no `result`.
- **Expected (the part to grade):** record verbatim what `mission keys` / `plan entries` /
  `wf step keys` contain. Per source, `missions` is `m.to_dict()` with **no** whitelist
  (`swarm.py:236-237`) and `Mission.plan` is documented as
  `[{idx, title, status, result, started_at, ended_at}]` (`agents/core/autonomy/missions.py:94`);
  `workflows.runs[].steps[]` comes from `WorkflowEngine.recent()` and carries
  `input_preview` + `output_preview` — 160 characters of the rendered prompt and the model's output
  (`agents/core/workflows/engine.py:183-192`).
- **FAIL if:** a mission step `result` or a workflow `input_preview`/`output_preview` is present in
  this **user-tier** response → **MAJOR**, filed as *"the payload-free whitelist covers
  `autonomy.pending_preview` but not `missions` or `workflows.runs`"*. This is a feed-level finding
  even though the page never renders those fields — a second consumer (React port H34.4, mobile) will.
- **Evidence:** the raw `/tmp/pge042.json` (redact any real content) and the printed key sets.

| ID | HITL action | Do | Expect | Fail | Auto |
|----|-------------|----|--------|------|------|
| PGE-043 | ACCEPT | click ACCEPT on a reversible row | footer `statusLine` flashes green `task <id> accept ✓` for 4 s; row disappears within one 2 s poll; `GET /api/admin/audit` gains a matching entry; `GET /api/metrics/north-star` `accepted` increments | MAJOR | ⚠️ |
| PGE-044 | DEFER | click DEFER | flash `task <id> defer ✓`; the task leaves the pending list without executing | MAJOR | ⚠️ |
| PGE-045 | REJECT | click REJECT on the irreversible row | flash `task <id> reject ✓`; `north-star` `rejected` increments; the row leaves the card **without a manual reload** (contrast run 1's **R8**, where the *v2 Console* list didn't refresh — Mission Control calls `poll()` + `pollAdmin()` immediately after the action, `:204-205`, so this page is expected to refresh where v2 did not) | MAJOR | ⚠️ |
| PGE-046 | Action without a token | clear the token field, then (in admin-configured mode) re-render the buttons is impossible — instead call `POST /autonomy/tasks/1/decision` with no header | `401`; and via the page, a tokenless click path cannot exist because buttons are only drawn in admin mode. Confirm no buttons render tokenless | MAJOR | ✅tests/test_route_auth_matrix.py |
| PGE-047 | Action against a dead server | stop the server, click ACCEPT | red flash `task <id> accept ✗ network`; nothing silently "succeeds" | MINOR | ❌ |
| PGE-048 | Action returning 5xx | make the queue 503 (stop the orchestrator mid-boot) and click | red flash `task <id> accept ✗ (503)` — the numeric status is surfaced | MINOR | ❌ |
| PGE-049 | Double-submit guard | click ACCEPT twice as fast as possible | `state.busy` suppresses the second call — DevTools Network shows exactly **one** `POST /autonomy/tasks/{id}/decision` | MAJOR | ❌ |
| PGE-050 | A2A collapsed row | with A2A on and ≥1 pending peer task, no list opened | inside the approvals card: `A2A INBOX — 1 pending peer task` (singular/plural handled), then a row `inbound peer tasks await decision` + an **`OPEN LIST`** button | MINOR | ❌ |
| PGE-051 | A2A expanded rows | click OPEN LIST | rows of `A2A` tag · peer id · title, each with **`APPROVE`** / **`REJECT`**; the list survives the 2 s re-render because items live in `state.a2aItems` (see the comment at `:323-325`) — watch for 10 s and confirm the buttons stay clickable | MAJOR | ❌ |
| PGE-052 | A2A empty after opening | revoke/decide everything, click OPEN LIST again | `a2a inbox empty` | MINOR | ❌ |
| PGE-053 | A2A list unauthorized | clear the token, click OPEN LIST | red flash `a2a inbox ✗ (401 — set admin token)`; the card does not blank out | MAJOR | ❌ |
| PGE-054 | A2A decide round-trip | click APPROVE on one peer task | flash `a2a <id> approve ✓`; the open list refreshes itself; `GET /api/a2a/inbox` shows the new status | MAJOR | ⚠️ |

---

## 06.5 Mission Control — missions & the dev swarm

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-055 | Missions empty state | fresh server | `◆ MISSIONS  0 WORKSPACES` and body `no mission workspaces — create one from the HUD console` | MINOR | ❌ |
| PGE-056 | Mission row shape | `POST /api/missions` (user tier) with a title + `max_steps` | one row: status tag (uppercase), title, `<steps_used>/<max_steps> steps`, action buttons | MAJOR | ⚠️tests/test_missions.py |
| PGE-057 | `planned` actions | look at a freshly created mission | tag amber `PLANNED`; buttons exactly **`START`**, **`CANCEL`** (cancel styled red) | MAJOR | ✅tests/test_swarm_summary.py::test_html_selfcontained_and_wired |
| PGE-058 | `active` actions | click START | tag plain `ACTIVE`; buttons **`PAUSE`**, **`COMPLETE`**, **`CANCEL`** | MAJOR | ✅same |
| PGE-059 | `paused` actions | click PAUSE | tag amber `PAUSED`; buttons **`RESUME`**, **`CANCEL`** | MAJOR | ✅same |
| PGE-060 | terminal statuses have **no** buttons | complete or cancel a mission | tag `DONE` (amber class) / `FAILED` (red) / `CANCELLED` (red); the button group is empty — `MISSION_ACTIONS` (`:366`) has no key for them | MINOR | ✅same |
| PGE-061 | No phantom statuses | grep the page | `MISSION_ACTIONS` must key only on `planned`/`active`/`paused`; `created:[` and `running:[` must be absent (the H34.1 review bug) | MAJOR | ✅tests/test_swarm_summary.py:279 |
| PGE-062 | Illegal transition | via curl, `POST /api/missions/{id}/resume` on an **active** mission, then click the same action if a stale button is visible | non-2xx; the page flashes red `mission <id> resume ✗ (<code>)` and the row does not change | MINOR | ✅tests/test_missions.py |
| PGE-063 | Budget bound | drive a mission past `max_steps` via `…/steps/{idx}/finish` | `409` on overrun; the row's `n/m steps` never exceeds `m` | MAJOR | ✅tests/test_missions.py |
| PGE-064 | Mission cross-check | compare each row against `GET /api/missions` | same ids, titles, statuses, step counts | MAJOR | ⚠️ |
| PGE-065 | Dev swarm, lock dir absent | on a fresh clone with no `memory_logs/`, read the DEV SWARM card | `▰ DEV SWARM  0 ACTIVE · 0 FILE LOCKS` (the glyph is `&#9648;`, a black parallelogram — not a triangle), the grey note `lock dir absent (memory_logs/) — dev locks are local-only per machine`, and four dim chips `CLAUDE` `CODEX` `OPENCODE` `ANTIGRAVITY` (all `#2b3a33`, no ` · ACTIVE` suffix) | MINOR | ✅tests/test_swarm_summary.py::test_dev_locks_missing_dir |
| PGE-066 | Dev swarm, dir present but empty | run `python lock.py status` once (its import **mkdirs** the lock dir, `lock.py:30`), reload | the note disappears and the body gains `no file locks — dev swarm idle or coordinating via draft PRs` | MINOR | ✅tests/test_swarm_summary.py:226 |
| PGE-067 | Live agent lock | `python lock.py acquire claude "PGE-067 test"` , reload | `CLAUDE · ACTIVE` chip in light blue with a glow; header count `1 ACTIVE · …`; a light-blue **diamond** appears on the map's right-hand column labelled `CLAUDE`; clicking it shows `lock: PGE-067 test / since: HH:MM:SS / age: Ns` | MAJOR | ✅tests/test_swarm_summary.py:194 |
| PGE-068 | Stale lock | hand-edit the `ts` in `memory_logs/oracle/locks/claude.active` to `now - 2000` (>`_STALE_TIMEOUT` 1800 s), reload | chip turns **amber** `CLAUDE · STALE`, header `0 ACTIVE`, node card appends a `STALE` line; the map diamond is amber | MAJOR | ✅tests/test_swarm_summary.py:194 |
| PGE-069 | Unknown dev agent | `python lock.py acquire mystery "x"` | a plain row `mystery / x / <age>` below the chip strip (not in `_DEV_AGENTS`, so it gets a row not a chip) | MINOR | ⚠️ |
| PGE-070 | File locks | `python lock.py acquire-component claude agents/web/mission_control.html "PGE-070"` | a `FILE LOCKS` sub-header, then a row: entity tag `claude`, component **basename** `mission_control.html`, the task text, and the age; `title=` tooltip is the full raw path. Up to 6 small squares appear near the owning diamond on the map | MINOR | ✅tests/test_swarm_summary.py:194 |
| PGE-071 | Corrupt lock file | `echo 'not json' > memory_logs/oracle/locks/codex.active`, reload | the feed does **not** 500; that file is skipped; other locks still render | MAJOR | ✅tests/test_swarm_summary.py::test_dev_locks_corrupt_state_file |
| PGE-072 | Windows-path basename | put a lock_state key like `c:\\users\\a\\repo\\agents\\web.py` in `lock_state.json`, reload | the component column shows `web.py`, not the whole string (`_basename`, `swarm.py:62`) | MINOR | ✅tests/test_swarm_summary.py:194 |
| PGE-073 | Footer provenance line | read the bottom of the page | `LOCAL-FIRST · READ FEED /api/swarm/summary · STEERING VIA GOVERNED ENDPOINTS` | COSMETIC | ❌ |
| PGE-074 | **Workflow runs & sub-agents are in the feed but on no chip** | `curl -s .../api/swarm/summary \| python -c "import json,sys;d=json.load(sys.stdin);print(d['workflows']);print(d['subagents'])"`, then search the rendered page for those numbers | The runbook §4b says workflow runs and sub-agents must "agree with their own API" — but `mission_control.html` renders **neither**; `grep -i 'workflow\|subagent'` on the page hits only the HTML header comment (`:7`). Record as a **GAP**, not a pass | MINOR (docs/feature gap) | ✅tests/test_swarm_summary.py:176 (feed only) |
| PGE-075 | Self-contained (no CDN) | DevTools → Network, filter "3rd-party"; also `grep -c 'src="http' agents/web/mission_control.html` | zero external requests; zero matches — the page must survive with the machine's network cable unplugged | MAJOR | ✅tests/test_swarm_summary.py:279 |
| PGE-076 | Partial orchestrator never 500s | kill Qdrant/Neo4j/n8n, restart the hub, hammer `for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code} " .../api/swarm/summary; done` | twenty `200`s. Every subsystem read is wrapped in `_safe()` (`swarm.py:125`) | MAJOR | ✅tests/test_swarm_summary.py::test_partial_orch_never_raises |

---

## 06.6 Brain / Neural Mesh page (`/brain`)

`brain.html` polls `GET /api/brain/summary?range=<today|7d|30d|all>` every **2 s** (`:584`) with a
**bare `fetch()` — no auth headers at all** and a silent `.catch(()=>{})` (`:578`). That single fact
generates the most important case in this group (PGE-084).

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-077 | Boot sequence | load `/brain` cold | a full-screen `#boot` overlay: `JARVIS` + `neural mesh · cold start`, then six typed lines ending `◇ neural mesh online`, then auto-fade after ~2.9 s. `click anywhere to skip →` works immediately | COSMETIC | ❌ |
| PGE-078 | KPI tiles | after ≥1 chat turn, compare the six tiles against the feed | `EVENTS`=`events`, `CHANNELS`=`sessions`, `TOKENS IN`=`tokens_in`, `TOKENS OUT`=`tokens_out`, `AGENTS FIRED`=`loc_added`, `COST`=`cost_eur` formatted `$x.xx` | MAJOR | ✅tests/test_brain_summary.py |
| PGE-079 | Roster seeding on an idle system | fresh server, no traffic, open `/brain` | the mesh renders **every** agent as a zero-cost node (`brain.py:75-82` seeds from the roster, minus `jarvis` which is the core) — the mesh must not be empty; `#brainNodes` reads `<n> nodes · <m> edges` | MAJOR | ✅tests/test_brain_summary.py::test_roster_seeded_even_when_idle |
| PGE-080 | Range buttons | click `TODAY`, `7D`, `30D`, `ALL` in turn | the clicked button gets the `ractive` highlight; a new request fires with the matching `?range=`; `EVENTS` for `TODAY` ≤ `ALL`. An unknown value coerces to `all` server-side (`brain.py:188`) | MINOR | ✅tests/test_brain_summary.py::test_range_filters_old_traces |
| PGE-081 | Harness chips | look at the header chips | four fixed chips `LOCAL` `CLAUDE` `GEMINI` `OLLAMA`; only those present in `by_harness` are lit. On a local-only box exactly `LOCAL` is lit | MINOR | ✅tests/test_brain_summary.py::test_backend_mapping |
| PGE-082 | Cost attribution bar | after traffic | one segment per harness, widths proportional to `cost_eur`; legend values tween to the same figures; `$0 total` on a local-only box (local models cost 0) | MINOR | ⚠️ |
| PGE-083 | Live feed rows | send a turn and watch | a new row **prepends** with the `axStreamIn` animation; max 8 rows; columns `TIME / AGENT · MODEL / OUT / COST / TOOK`. No user message text appears (the feed's `recent` carries no `text_preview`) | MAJOR | ✅tests/test_brain_summary.py::test_recent_is_epoch_ms_and_capped |

#### PGE-084 — `/brain` shows a silent all-zero page when its feed is unauthorized  🌐
- **Surface:** `brain.html:578` · `GET /api/brain/summary` **user** tier · **Auto:** ❌
- **Why it matters:** this is a golden-rule case. `load()` is
  `fetch('/api/brain/summary?range=…').then(r=>r.json()).then(s=>AX.applyData(s)).catch(()=>{})` —
  **no `r.ok` check, no headers, and the error is swallowed**. A 401 body parses as JSON, so
  `applyData` either throws inside the swallowed promise or applies an object with no expected keys.
  The result is a fully-rendered cockpit reading `0 EVENTS`, `$0`, `0 nodes` — indistinguishable from
  a genuinely quiet system.
- **Prereq:** restart with `JARVIS_USER_TOKEN=devuser`.
- **Steps:** 1) `curl -s -o /dev/null -w "%{http_code}\n" .../api/brain/summary` → expect `401`.
  2) Try to open `/brain` in Chrome — per PGE-012 the shell itself is user-guarded, so you likely get a
  401 body. 3) To isolate the feed failure specifically, temporarily leave `JARVIS_USER_TOKEN` unset,
  open `/brain`, then in DevTools → Network **block** the URL pattern `*/api/brain/summary` and reload.
  4) Read every number on the page and the footer.
- **Expected (the honest outcome):** some visible degraded signal — a stale/offline badge, an error
  strip, or numbers held at `—`.
- **Also acceptable (honest degradation):** the page stays on the boot overlay, or `#footStatus` keeps
  its static pre-load text `MIT © 2026 · loopback-only · SQLite 0600 · zero egress` rather than
  asserting `live`.
- **FAIL if:** the page paints `0 EVENTS / $0 / 0 nodes` **and** `#footStatus` reads
  `JARVIS neural mesh · live · 0% unattributed · viz: Axon (MIT)` — asserting "live" over a dead feed
  → **MAJOR**.
- **Evidence:** screenshot of the blocked-feed page with the DevTools Network panel showing the
  blocked/401 request, plus the verbatim footer text.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-085 | RTK panel is honestly hidden | look for `RTK · SIGNAL COMPRESSION` | the panel is **display:none** and `SIGNAL COMPRESSION` reads `n/a` — `build_summary` returns `"rtk": None` unconditionally (`brain.py:173`), so this must never show a number | MINOR | ✅tests/test_brain_summary.py |
| PGE-086 | Budget rows show "no cap" | read the BUDGET block | three rows `DAILY` / `WEEKLY` / `MONTHLY`, each `$x.xx / no cap`, badge `—`, bar at 0 % width and 0.3 opacity — `budget_*_eur` are all `None` (`brain.py:164-166`) | MINOR | ✅tests/test_brain_summary.py |
| PGE-087 | Unpriced-models banner never fires | look for the amber `⚠ unpriced models` strip | absent — `unpriced_models` is always `[]` (`brain.py:167`) | COSMETIC | ❌ |
| PGE-088 | Footer "% unattributed" is a stub | read `#footStatus` after data loads | `… · 0% unattributed · …`. `unattributed_token_pct` is hard-coded `0` (`brain.py:168`) — record as an observation: it reads as a computed metric but is a constant | MINOR | ❌ |
| PGE-089 | HALL OF FAME cards | after traffic | four cards `♛ TOP EARNER`, `▲ BUSIEST MODEL`, `❖ MOST EFFICIENT`, `◈ BUSIEST BACKEND`; with no data each shows `—`, and MOST EFFICIENT is always `—` because `rtk` is None | MINOR | ❌ |
| PGE-090 | `—` model bucket | run a turn where the tracer records no model | `by_model` contains a literal `"—"` key and the MODELS table shows a row named `—`; judge whether that reads as honest ("unknown model") rather than as a real model name | MINOR | ⚠️ |
| PGE-091 | Mesh interaction | hover a MODELS/AGENTS table row; then hover and click a mesh node; then drag one | row hover isolates that node; node click **pins** the `#detail` card (`kind` / full name / tokens out / cost / `% of total spend` + a bar); drag stretches without pinning; `Esc`-free — click empty canvas to unpin | MINOR | ❌ |
| PGE-092 | Share-card export | click `Export PNG` | a 1100×1100 PNG downloads as `axon-recap.png` showing `J A R V I S`, `NEURAL MESH · 100% local`, SPEND / TOKENS OUT / SAVED BY RTK / TOP AGENT. Confirm **no** project, branch, host or agent-private data is baked in beyond the top agent id (the on-page card shows `project ████████ · redacted`) | MAJOR (privacy) | ❌ |
| PGE-093 | Copy to clipboard | click `Copy to clipboard` | the same image lands on the clipboard; on a browser without `ClipboardItem` the click is a silent no-op (acceptable) — verify no exception in the console | COSMETIC | ❌ |
| PGE-094 | Embed mode | open `/brain?embed=1` | boot overlay suppressed, every section except `#meshPanel` hidden, the mesh fills the viewport with no border/radius | MINOR | ❌ |
| PGE-095 | Embed inside a same-origin iframe | in DevTools console on `/`: `document.body.insertAdjacentHTML('beforeend','<iframe src="/brain?embed=1" style="width:400px;height:300px">')` | renders (X-Frame-Options is `SAMEORIGIN`). From the WorldView app on `:3000` the same iframe must be **blocked** — different origin | MINOR | ✅tests/test_hud_security_headers.py |
| PGE-096 | Canvas loop resilience | leave `/brain` open 30 min ⏱ with the DevTools console open | at most **one** `AXON loop error:` line (the loop self-mutes via `this._logged`); memory does not climb without bound; the header wave keeps animating | MINOR | ❌ |
| PGE-097 | Outbound links | click the two footer links | `github.com/andrei649/jarvis-hub` and the Axon MIT attribution open in a new tab with `rel="noopener"`. Note these are the **only** external `href`s on any standalone page | COSMETIC | ❌ |
| PGE-098 | Axon attribution present | view source | the MIT notice block at `brain.html:4-8` and `LICENSES/axon-MIT.txt` exists on disk | MINOR (licence) | ❌ |

---

## 06.7 The legacy static HUD (`/v1`)

**It is still served** (`agents/web.py:746-748`, `tests/test_endpoints.py:28`) and it is also what `/`
falls back to when `JARVIS_HUD=v1` or the v2 bundle is missing. It loads 14 scripts including
`data.js`, which ships a set of **hard-coded mock datasets**. Two of those paths render as if live —
those are the two most valuable cases in this whole section.

#### PGE-099 — The legacy SYSTEM widget renders the docs' *reference rig* when `/status` is unavailable  🖥
- **Surface:** left-rail `SISTEM`/`SYSTEM` bracket (`components.js:190-200`), fed by
  `JARVIS_FALLBACK_SYS` (`static/data.js:30-35`) whose values come from `static/i18n.js:180-184` ·
  **Tier:** the widget's source `GET /status` is **open** · **Auto:** ❌
- **Why it matters:** this is **run 1 BLOCKER #2 in widget form**. The fallback host is literally
  `BONOBO-WS`, CPU `Intel Core Ultra 9 · 32c`, GPU `RTX 5090 · 24GB`, RAM `42 / 192 GB`, VRAM
  `10 / 24 GB`, GPU load `30`, backend `LM Studio · 1234`, model `google/gemma-4-31b-a4b`,
  latency `2.1` — the *reference* machine from the docs, exactly what Steve fabricated. The backend
  (`agents/web.py:565-630`) is scrupulously honest (`unknown` / `none` / `0`); the frontend seeds over
  it.
- **Prereq:** the owner's real box. Note its real hostname and GPU first (`hostname`, `nvidia-smi`).
- **Steps:**
  1. Baseline: open `/v1`, read the whole SYSTEM bracket, and compare each row against
     `curl -s .../status | python -c "import json,sys;print(json.load(sys.stdin)['sys'])"`.
  2. Degrade: in DevTools → Network, **block** `*/status`, then hard-reload `/v1`.
  3. Read the SYSTEM bracket again, row by row.
  4. Second path to the same state: stop the server, then load `/v1` from the service-worker cache
     (see §06.9) and read the bracket.
- **Expected (baseline):** `HOST` = this machine's real hostname (e.g. `DESKTOP-8AV7E7F`), `CPU` the
  real model string, `BACKEND` and `MODEL` both literally **`unknown`** (`_sys_info` never fills them),
  `GPU` the real card or `none`.
- **Expected (degraded, step 3):** an honest placeholder — `—`, `unknown`, or a visible
  "server unreachable" state.
- **FAIL if:** step 3 or 4 shows `BONOBO-WS` / `RTX 5090 · 24GB` / `42 of 192 GB` / `LM Studio · 1234`
  / `google/gemma-4-31b-a4b` presented in the same style as live data → **BLOCKER**. It is the
  product's own worst case: fabricated hardware, on the reference rig's name, with no degraded marker.
- **Evidence:** side-by-side screenshots (live vs `/status` blocked) and the `/status` `sys` JSON.

#### PGE-100 — The legacy SYSTEM meters animate synthesized numbers  🖥👁
- **Surface:** `useLiveSys` (`static/enhancements.js:200-215`), consumed as `liveSys` at
  `static/app.js:149` and passed to the widget at `app.js:351` · **Auto:** ❌
- **Why it matters:** the RAM / VRAM / GPU-load / latency meters are *not* the polled values. Every
  1.4 s they are recomputed as `base + Math.sin(t*k) + (Math.random()-0.5)*0.6`, then clamped. A user
  watching a "live" needle is watching a random walk.
- **Steps:**
  1. Open `/v1`. Watch the RAM, VRAM, GPU LOAD and LATENCY rows for 30 s **without** any load on the
     machine. Note whether they move.
  2. In a second window run `nvidia-smi -l 1` and compare VRAM used, second by second, for 30 s.
  3. Read the clamp: `ram_used` is `clamp(v, 60, ram_total - 8)`. Compute your machine's real
     `ram_total` from `/status`. If `ram_total < 68`, the clamp lower bound (60) **exceeds** the upper
     bound (`ram_total-8`), and `clamp = max(60, min(hi, v))` returns **60** always.
  4. On such a machine, read the RAM row.
- **Expected (honest):** the meters track `/status` (which polls every 10 s), i.e. they step, not
  oscillate, and they agree with `nvidia-smi` within a poll interval.
- **FAIL if:** the numbers oscillate smoothly between `/status` polls while the machine is idle →
  **MAJOR** (fabricated telemetry rendered as live); if step 4 shows a RAM figure **greater than the
  machine's total RAM** (e.g. `60.0 / 32 GB`) → **MAJOR**, and note it is deterministic, not flaky.
- **Also note:** the bracket's status label is the hard-coded string `NOMINAL`
  (`components.js:190`, `i18n.js:149`) regardless of any real health signal — record as a separate
  MINOR observation.
- **Evidence:** a 30 s screen recording of the meters on an idle machine + the `/status` `sys` values
  + `nvidia-smi` output at the same timestamps.

#### PGE-101 — The Agent Dossier modal is 100 % mock data  👁
- **Surface:** double-click any agent in the left rail → `DossierModal`
  (`static/dossier-modal.js`), fed by `DOSSIER[dossierAgent]` at `static/app.js:432`, defined at
  `static/data.js` (the `const DOSSIER = {…}` block) · **Auto:** ❌
- **Why it matters:** the modal presents `model`, `channel`, `heartbeat`, `policy`, a plugin pill list,
  a skills count, a `memory_facts` count and a `soul_excerpt` as that agent's configuration. Every one
  of those is a literal in `data.js` — e.g. every agent's model reads `gemma-4-26b-a4b`, Pepper's
  plugins read `google-calendar, gmail, telegram`, Jarvis's `memory_facts` reads `22`.
- **Steps:** 1) Double-click **pepper**. Screenshot the modal. 2) Compare `MODEL` against
  `curl -s .../api/agents | python -m json.tool` and the `/status` `loaded_model`. 3) Compare the
  PLUGINS pills against `curl -s .../plugins`, and specifically against `GET /api/security/posture`
  (run 1 confirmed `google-calendar` was **unauthorized** there). 4) Compare `memory_facts` against
  `GET /memory/stats`. 5) Click **View soul** — that button *does* hit the real
  `GET /api/agents/{id}/soul`. 6) Double-click **howard**, then **argus**.
- **Expected:** every displayed field either comes from a live endpoint or is visibly labelled as a
  sample.
- **FAIL if:** the modal shows `gemma-4-26b-a4b` while the resident model is something else, or lists
  `google-calendar` as an active plugin while the posture says unauthorized → **BLOCKER** under the
  golden rule (this is exactly the Pepper-calendar fabrication, rendered by the HUD itself rather than
  by the model). Step 5 is the control: the soul text is real, which makes the surrounding fake fields
  more, not less, convincing.
- **Also expect (step 6):** `dossier-modal.js:168` early-returns `if (!agent || !dossier)`, and
  `DOSSIER`/`JARVIS_AGENT_META` cover only **15** of the **17** agents — `howard` and `argus` are
  absent. Double-clicking them must therefore do **nothing at all** (silent no-op) → **MINOR**.
- **Evidence:** the modal screenshot, the `/api/agents` JSON, the posture JSON, and a note of which
  fields disagreed.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-102 | Agent rail count | open `/v1` with the server healthy | 17 agents across the four tier groups; `howard` and `argus` appear with tier `FND` and an **empty role** label and **no glyph** (`JARVIS_AGENT_META` has no entry — `data.js:43-59`) | MINOR | ❌ |
| PGE-103 | Agent rail on a dead `/api/agents` | block `*/api/agents`, reload | the fallback (`data.js:90-101`) builds the rail from `JARVIS_AGENT_META` — exactly **15** agents, each with the hard-coded `model: 'google/gemma-4-31b-a4b'` (`data.js:98`). A count that disagrees with `/status` `agents_total: 17`, plus an invented model string → **MAJOR** | MAJOR | ❌ |
| PGE-104 | Chat round-trip 🤖 | type a message, press Enter | streams via `POST /chat/stream`; reply renders; a TTS request to `POST /tts` may follow | MAJOR | ⚠️ |
| PGE-105 | Empty submit | press Enter on an empty box | no request fires (`submit()` early-returns on empty; the server also rejects empty messages in `ChatRequest`) | MINOR | ✅ |
| PGE-106 | Ticker | watch the bottom ticker | items come from `GET /ticker` (user tier); with no signals the ticker is empty rather than showing sample headlines | MAJOR | ⚠️ |
| PGE-107 | Weather / calendar / notifications widgets | compare against `GET /dashboard` | weather falls back to city `Bucharest`/`București` with `—` values and `Loading…`; `calendar` and `notifications` fall back to **empty arrays** (`data.js:41-42`) — an honest empty is correct here | MINOR | ❌ |
| PGE-108 | ⌘K / Ctrl-K palette | press the combo | the command palette opens; `Esc` closes it and also clears focus + closes the Console | MINOR | ❌ |
| PGE-109 | ⚙ Settings menu | open it | theme · density · scanline · language · admin-token field · *Open Admin →* · the real version from `/status`; toggles for Cognition/Systems/Workflows/Observability and NetworkBrain | MINOR | ❌ |
| PGE-110 | Prefs persist pre-paint | set density=compact, reload | `<html data-density="compact">` is set by the inline script in `templates/index.html` **before** first paint — no flash of the old density | COSMETIC | ❌ |
| PGE-111 | Language toggle RO/EN | switch to RO, then EN | every label switches; the `SISTEM`↔`SYSTEM` bracket title changes; RO diacritics (`LATENȚĂ`, `ÎNCARCARE`) render correctly in the chosen font | ♿ MINOR | ❌ |
| PGE-112 | User-token prompt | set `JARVIS_USER_TOKEN`, clear `localStorage`, load `/v1`, send a chat turn | `auth.js` intercepts the 401, prompts once with `This Jarvis requires an access token.…`, stores `hud.user_token`, and **retries once**. A wrong token must not loop the prompt | MAJOR | ❌ |
| PGE-113 | Admin-token injection | put a valid admin token in ⚙, open Console → Secret Broker | `adminFetch` attaches `X-Admin-Token`; with a wrong token the panel shows `admin token required (set it in ⚙ Settings)` | MAJOR | ❌ |
| PGE-114 | Console overlay opens | click ▦ Console (or ⌘K → Console) | full-screen dialog with `role="dialog"` `aria-label="Console"`; left nav grouped **Observability**(4) / **Security**(4) / **Quality**(2) / **Autonomy**(6) / **Workspace**(2) / **Memory**(5) / **Tools**(7) — **30** panels total (`tools.js` `TOOLS` registry) | MAJOR | ❌ |
| PGE-115 | Console close paths | click the `×`, then the backdrop, then press `Esc` | all three close it | MINOR | ❌ |
| PGE-116 | Every Console panel loads or degrades honestly | click all 30 panels in order, watching the console + Network | each shows data, `No data yet.`, `Loading…`, or `⚠ <error>` — never a blank pane and never seeded numbers. Panels needing admin must say so | MAJOR | ⚠️ |
| PGE-117 | Systems panel degraded | open ▦→ or the SYSTEMS toggle with Qdrant/Neo4j/n8n **down** | memory / plugins / learning / security / bench / oauth / oracle sections show placeholders; failures land in the browser console only (`systems.js:712-762` all `console.error`) — judge whether the *user* can tell a section failed | MAJOR | ❌ |
| PGE-118 | Observability panel | open it after traffic | traces from `GET /api/traces`; the clear action calls `POST /api/traces/clear` (**admin**) — with no admin token it must surface an error, not silently no-op | MINOR | ❌ |
| PGE-119 | Workflows panel | list, then run a pipeline | `GET /api/workflows` (open) lists; `POST /api/workflows/run` (user) runs; the trace overlay populates | MINOR | ⚠️ |
| PGE-120 | **Plugin toggle reports success on a 401** | set `JARVIS_ADMIN_TOKEN`; open the SYSTEMS panel; click a plugin's enable/disable toggle; watch DevTools Network **and** the console | `PUT /plugins/{id}/toggle` is **admin**-tier but `app.js:402` calls plain `fetch` with no admin header, and only `.catch()`es network errors — a `401` body still parses as JSON, so the handler logs `plugin toggled: {...}` and dispatches `jarvis:plugins_updated`. **FAIL (MAJOR)** if the UI reports/implies success while the Network tab shows `401` and `GET /plugins` shows the plugin unchanged | MAJOR | ❌ |
| PGE-121 | Kill-Switch panel (legacy) | Console → Security → Kill-Switch, nothing halted | `✓ Operational` in the `ok` style; `GET /api/security/kill-switch` returns `{"global":false,"halted":{}}`. Engage → `⛔ HALTED — autonomous actions blocked` + a `Pre` block of the halted map. This is the *correct* derivation (`tools.js:340`) — the reference reading for the PGE-125 divergence row | **BLOCKER** | ❌ |
| PGE-122 | Audit panel | Console → Security → Audit & Intent | `✓ chain verified` or `⚠ chain unverified` from `GET /api/security/audit/intent`; entries render `actor · action — why`; `No audited actions yet.` on a fresh install | MAJOR | ⚠️ |
| PGE-123 | ♿ Console keyboard reachability | Tab through the Console with no mouse | every nav link and panel button is reachable and shows a visible focus ring; the dialog does **not** trap focus (note it if focus escapes to the page behind — the WorldView help overlay *does* trap, §06.11) | ♿ MINOR | ❌ |
| PGE-124 | Legacy HUD on a phone-sized viewport 👁 | Chrome device emulation, iPhone 14 | the mobile tab bar (`💬 Chat` / `📊 Systems`) appears; layout does not overflow horizontally; the ⚙ menu is usable | MINOR | ❌ |

---

## 06.8 Legacy-vs-v2 divergence sweep  (novel; the R7 bug class)

**Method.** For each pair below, open the legacy panel at `/v1` (Console) in one tab and the v2
equivalent at `/` in another, **on the same box at the same moment**, and call the underlying endpoint
with `curl` in a third. Three readings, one truth. A disagreement between the two UIs is a divergence
finding even when one of them is right — because the owner cannot know which. Grade each row
**AGREE / DIVERGE (which is wrong) / N-A (no v2 equivalent)**.

| ID | Endpoint (tier) | Legacy surface | v2 surface | What must match | Fail | Auto |
|----|-----------------|----------------|------------|-----------------|------|------|
| PGE-125 | `GET /api/security/kill-switch` (open) | `tools.js` KillSwitchPanel | `frontend/src/gap.tsx:355` + `modes.tsx:139` | the boolean, and the words: legacy `✓ Operational` ↔ v2 `ARMED · operational`; legacy `⛔ HALTED` ↔ v2 `ENGAGED · all agents halted`. **This is R7.** | **BLOCKER** | ⚠️ |
| PGE-126 | `GET /api/health/components` (open) | HealthPanel | Observe mode | the same component list and failed set | MAJOR | ⚠️ |
| PGE-127 | `GET /api/quality` (open) | QualityPanel | Observe | rolling average + threshold | MAJOR | ⚠️ |
| PGE-128 | `GET /api/review/queue` (open) | ReviewPanel | Observe | queue length + item ids | MAJOR | ⚠️ |
| PGE-129 | `GET /api/actions/pending` (user) | ActionsPanel | Autonomy | the same pending action ids and the same approve/reject outcome | **BLOCKER** | ⚠️ |
| PGE-130 | `GET /api/analytics/cost` (open) | CostPanel | Observe | per-agent cost and the monthly projection | MAJOR | ⚠️ |
| PGE-131 | `GET /api/security/governance` (open) | TrustScorecardPanel | Trust | pass/fail verdict + the three sub-scores | MAJOR | ⚠️ |
| PGE-132 | `GET /api/security/audit/intent` (open) | AuditPanel | Trust | chain-verified verdict and entry count | MAJOR | ⚠️ |
| PGE-133 | `GET /api/notes` (user) | NotesPanel | Workspace/Projects | the note body, and that "Rewrite with AI" writes the same store | MAJOR | ⚠️ |
| PGE-134 | `GET /api/rooms` (user) | RoomsPanel | Projects → Rooms | the same room list and the same history for one room | MAJOR | ⚠️ |
| PGE-135 | `GET /api/secrets/broker` (admin) | SecretsPanel | Admin | the same **names** and, critically, **no plaintext values** on either | **BLOCKER** | ⚠️ |
| PGE-136 | `GET /api/admin/widgets` (admin) | WidgetsPanel | Admin | the same token list | MAJOR | ✅tests/test_h10_1_chat_widget.py |
| PGE-137 | `GET /api/webhooks` (admin) | WebhooksPanel | Interop | the same webhook ids | MINOR | ⚠️ |
| PGE-138 | `GET /api/kg/facts/as-of` (user) | KGPanel | Memory | the same facts for the same `?date=` | MAJOR | ⚠️ |
| PGE-139 | `GET /api/eval/datasets` (open) | EvalPanel | Observe | the same dataset names | MINOR | ⚠️ |
| PGE-140 | `POST /api/autonomy/preview` (user) | DryRunPanel | Autonomy dry-run card | **identical** irreversibility verdict for the same `kind` — a `delete_file` must read IRREVERSIBLE in both | **BLOCKER** | ✅ |
| PGE-141 | `POST /api/schedule/parse` (user) | SchedulePanel | Autonomy | the same cron for `"every weekday at 7am"` **and** for `"în fiecare luni la 9"` | MINOR | ✅ |
| PGE-142 | `GET /status` `loaded_model` (open) | ⚙ version + SYSTEM `MODEL` row | v2 top-bar LLM badge | the same model name — and cross-check against LM Studio's own UI (**R4**) | MAJOR | ✅tests/test_llm_control_status_model.py |
| PGE-143 | `GET /api/agents` (user) | left rail | v2 roster column | the same **17** ids; legacy must not silently show 15 | MAJOR | ❌ |
| PGE-144 | `GET /api/trust/status` (open) | trust chrome | v2 `EGRESS` / `MIC` badges | strict-local and mic state agree | MAJOR | ⚠️ |

#### PGE-145 — Divergence sweep, the write direction
- **Surface:** all of the above · **Auto:** ❌
- **Why it matters:** a read divergence is confusing; a **write** divergence means one UI's action is
  invisible to the other, which is how a governance action gets lost.
- **Steps:** for each of Notes (PGE-133), Rooms (PGE-134), Widgets (PGE-136) and Kill-Switch
  (PGE-125): perform the write in the **legacy** UI, then reload the **v2** UI (no server restart) and
  confirm it appears; then reverse the direction.
- **Expected:** both directions propagate within one poll interval; both write the same store.
- **FAIL if:** a legacy-created room/note/widget is absent from v2 (or vice versa) → **MAJOR**; if a
  legacy kill-switch *engage* is not reflected in v2 → **BLOCKER**.
- **Evidence:** paired before/after screenshots per pair.

---

## 06.9 PWA — service worker, manifest, offline shell, upgrade staleness

Read this before running: `agents/web/static/sw.js` uses a **static** `CACHE_NAME = 'jarvis-hud-v3'`,
pre-caches 22 paths including **`'/'`**, serves **cache-first** for anything not matching
`EXCLUDE_PATTERNS` (`/status`, `/ticker`, `/chat`, `/tts`, `/api/`, `/plugins`, `/learning`, `/memory`,
`/bench`, `/security`), and falls back to `caches.match('/')` for failed navigations. Registration
happens **only** in the legacy shell (`agents/web/templates/index.html`, the `navigator.serviceWorker
.register('/sw.js')` block) — the v2 shell (`agents/web/v2/index.html`) registers nothing. But sw.js is
served from the root, so its **scope is `/`** and it governs the v2 HUD too.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-146 | Registration only from `/v1` | fresh profile → open `/` (v2) → DevTools → Application → Service Workers | **no** worker. Then open `/v1` → a worker appears with scope `http://127.0.0.1:8080/` and `[Service Worker] Registered successfully with scope:` in the console | MINOR | ❌ |
| PGE-147 | Precache contents | Application → Cache Storage → `jarvis-hud-v3` | exactly **21** entries: `/`, `/static/manifest.json`, `fonts.css`, `style.css`, `systems.css`, `favicon.svg`, the two React bundles, and **13** legacy JS files — all **without** a `?v=` query. Note `auth.js` is **not** precached even though the page loads it first | MINOR | ❌ |
| PGE-148 | Precache misses the real asset URLs | compare the cached keys with the Network tab's requests on `/v1` | the page requests `/static/app.js?v=9.9.9` etc., which do **not** match the cached `/static/app.js` (`caches.match` is query-sensitive by default). Record as an observation: the precache list is largely dead and assets are re-cached on first fetch with their query strings | MINOR | ❌ |
| PGE-149 | Old caches purged on activate | edit nothing; instead create a dummy cache in the console (`caches.open('jarvis-hud-v2')`), then unregister+reload to force `activate` | the console logs `[Service Worker] Clearing old cache jarvis-hud-v2` and it is deleted | MINOR | ❌ |
| PGE-150 | Network-only for dynamic paths | with the worker active, watch `/status`, `/ticker`, `/chat/stream`, `/api/swarm/summary` in Network | all served `(from network)`, never `(from ServiceWorker)` cache; a POST is never cached | MAJOR | ❌ |
| PGE-151 | Offline navigation fallback | with the worker active on `/v1`, stop the server, reload | the cached `/` shell paints instead of Chrome's dino page. **Then immediately run PGE-099 step 4** — the shell is now live-looking with no backend at all | MAJOR | ❌ |
| PGE-152 | Offline API failure shape | while offline, watch the console | excluded paths resolve to `Response.error()` — the page's own `.catch` handlers fire; there must be **no** uncaught "Failed to fetch" promise rejection from the worker | MINOR | ❌ |
| PGE-153 | Installability 👁 | Chrome → Application → Manifest, and the address-bar install affordance | manifest parses with no errors; name `Jarvis Hub`, short name `Jarvis`, standalone, portrait, theme `#00aeef`, background `#030810`. Record any Chrome warning about the SVG-only icon set | MINOR | ❌ |
| PGE-154 | Installed-app launch | install the PWA, launch it from the OS | opens `start_url` `/` (the **v2** HUD) in a standalone window; the title bar reads `Jarvis Hub` — note the brand drift vs the Nerva product name | COSMETIC | ❌ |
| PGE-155 | ♿ Manifest vs viewport | in the installed window, resize to a narrow width | no horizontal page scroll; `viewport-fit=cover` + the `apple-mobile-web-app-*` metas are present in the legacy shell only | ♿ MINOR | ❌ |

#### PGE-156 — A stale service worker serves a stale HUD after `UPDATE.bat`  ⏱
- **Surface:** `static/sw.js` + `agents/web/v2/index.html` + `UPDATE.bat` · **Auto:** ❌
- **Why it matters:** this is the "green screen over old code" failure. The owner updates, the tests
  pass, and the browser keeps running yesterday's bundle — so every other finding in this run could be
  measured against the wrong build.
- **Prereq:** a browser profile that has visited `/v1` at least once (so the worker is installed).
  Note the current bundle hash: `grep -o 'index-[A-Za-z0-9_-]*\.js' agents/web/v2/index.html` →
  today it is `index-BQpwz2br.js`.
- **Steps:**
  1. With the worker active, open `/` (v2) and confirm in Network that the document was served
     `(from ServiceWorker)` and that it references the hash from the prereq.
  2. Run `UPDATE.bat` (or simulate: `git pull` a commit that changes the v2 bundle hash — or hand-edit
     `agents/web/v2/index.html` to point at a new filename and rename the asset accordingly).
  3. Restart the server. **Do not** clear site data.
  4. Reload `/` normally (F5, not Shift-F5). Read the served document's script `src` and compare with
     the on-disk hash. Check the version in ⚙/top bar against `curl -s .../status | grep version`.
  5. Hard-reload (Shift-F5) and repeat step 4.
  6. Check Application → Service Workers for a "waiting" worker and whether `CACHE_NAME` changed.
- **Expected (honest):** step 4 serves the **new** hash — either because the worker was bypassed for
  navigations or because something invalidated the cache.
- **Also acceptable:** the page shows an explicit "a new version is available — reload" prompt.
- **FAIL if:** step 4 serves the **old** hash while the disk has the new one → **MAJOR**. Note the two
  contributing facts for the report: `CACHE_NAME` is the literal `'jarvis-hud-v3'` and nothing in
  `UPDATE.bat` touches it or the browser cache. If step 4 loads the new `index.html` but 404s on a
  purged old asset, the HUD white-screens → also **MAJOR**.
- **Evidence:** the Network panel for step 1 and step 4 (showing `(from ServiceWorker)` and the two
  hashes), the `/status` version, and the Cache Storage key list.

#### PGE-157 — Uninstalling the worker fully recovers  ⏱
- **Steps:** Application → Service Workers → **Unregister**; Application → Storage → **Clear site
  data**; reload `/`.
- **Expected:** the fresh bundle loads from the network; the SYSTEM widget shows the real host again
  (PGE-099 baseline); no worker is registered until `/v1` is visited.
- **FAIL if:** stale content survives a full clear → **MAJOR**.

---

## 06.10 Embeddable chat widget (foreign origin)

Setup once, then run the table. Routes: `POST/GET /api/admin/widgets` and
`DELETE /api/admin/widgets/{token}` are **admin**; `GET /api/widget/{token}`,
`GET /api/widget/{token}/config` and `POST /api/widget/{token}/message` are **open**.

```bash
T=$JARVIS_ADMIN_TOKEN
TOK=$(curl -s -X POST http://127.0.0.1:8080/api/admin/widgets \
  -H "X-Admin-Token: $T" -H 'Content-Type: application/json' \
  -d '{"title":"Nerva QA","color":"#4f46e5","position":"bottom-left","greeting":"Salut! Cu ce te ajut?"}' \
  | python -c "import json,sys;print(json.load(sys.stdin)['widget']['token'])")
mkdir -p /tmp/pge-widget && cat > /tmp/pge-widget/host.html <<EOF
<!doctype html><meta charset="utf-8"><title>PGE foreign origin</title>
<h1>A different origin</h1>
<script src="http://127.0.0.1:8080/api/widget/$TOK"></script>
EOF
python -m http.server 9099 --directory /tmp/pge-widget   # → http://127.0.0.1:9099/host.html
```
(`http://127.0.0.1:9099` is a distinct **origin** from `:8080` — different port — so this is a genuine
cross-origin embed.)

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-158 | Issue returns defaults | inspect the POST response | `{"ok":true,"widget":{title,color,position,greeting,token}}`; unknown keys in the body are dropped (`WidgetStore.issue` filters to `_DEFAULTS`) | MINOR | ✅tests/test_h10_1_chat_widget.py::test_issue_applies_defaults_and_overrides |
| PGE-159 | Issue requires admin | repeat the POST with no header | `401` | **BLOCKER** | ✅tests/test_route_auth_matrix.py |
| PGE-160 | Snippet content type | `curl -sI ".../api/widget/$TOK" \| grep -i content-type` | `application/javascript`; the body contains the token and the theme values | MAJOR | ✅tests/test_h10_1_chat_widget.py::test_render_snippet_embeds_token_and_theme |
| PGE-161 | Bubble renders on the foreign page 👁 | open `http://127.0.0.1:9099/host.html` | a 56 px round `💬` bubble in the **bottom-left** (because `position` contains `left`), filled `#4f46e5`, `z-index 2147483647` | MAJOR | ❌ |
| PGE-162 | Greeting on first open | click the bubble | a 320 px panel opens with header `Nerva QA` in the accent colour and one bot message `Salut! Cu ce te ajut?`; the greeting is added **once** (guarded by `!log`) — close and reopen to confirm it is not duplicated | MINOR | ❌ |
| PGE-163 | Message round-trip 🤖 | type `hello` + Enter | your text right-aligned in the accent colour, then the reply left-aligned; DevTools shows `POST /api/widget/{token}/message` | MAJOR | ✅tests/test_h10_1_chat_widget.py::test_widget_endpoints |
| PGE-164 | **CORS blocks the round-trip by default** | with `JARVIS_CORS_ORIGINS` **unset**, do PGE-163 | the browser blocks the cross-origin `fetch`; the panel shows exactly `(connection error)` and the console shows a CORS error. This is the expected default (`agents/web.py:416-424` only adds `CORSMiddleware` when the env list is non-empty) | MAJOR if it instead *succeeds* (unexpected wildcard CORS) | ❌ |
| PGE-165 | CORS allowlist works | restart with `JARVIS_CORS_ORIGINS=http://127.0.0.1:9099`, redo PGE-163 | the reply arrives; the response carries `access-control-allow-origin: http://127.0.0.1:9099` | MAJOR | ⚠️ |
| PGE-166 | Wrong origin still blocked | serve the same file on port 9098 and load it | blocked — only the listed origin works | MAJOR | ⚠️ |
| PGE-167 | Theme override | issue a second widget with `{"color":"#f0645c","position":"bottom-right","title":"Nerva"}` and embed it | bubble right-side, red, header `Nerva` | MINOR | ✅tests/test_h10_1_chat_widget.py |
| PGE-168 | Config read | `curl -s ".../api/widget/$TOK/config"` | the config JSON, **including** the token — note that this open endpoint echoes the token to anyone who already has it (not an escalation, but record it) | MINOR | ✅ |
| PGE-169 | Invalid token fails closed | `curl -s -o /dev/null -w "%{http_code}\n" .../api/widget/deadbeef` and `…/deadbeef/message -d '{"message":"x"}'` | `404` `{"error":"not found"}` for both — never a generic bubble, never a chat reply | **BLOCKER** | ✅tests/test_h10_1_chat_widget.py::test_widget_endpoints |
| PGE-170 | Revoked token fails closed | `curl -X DELETE .../api/admin/widgets/$TOK -H "X-Admin-Token: $T"`, then reload the foreign page | the snippet request now `404`s → **no bubble at all**; a still-open tab's next message gets `404` and the panel shows the error text, not a reply | **BLOCKER** | ✅tests/test_h10_1_chat_widget.py::test_get_update_revoke_persistence |
| PGE-171 | Revoke requires admin | `curl -X DELETE .../api/admin/widgets/$TOK` with no header | `401` | **BLOCKER** | ✅tests/test_route_auth_matrix.py |
| PGE-172 | Empty message rejected | `curl -s -X POST ".../api/widget/$TOK/message" -H 'Content-Type: application/json' -d '{}'` | `400 {"error":"message required"}` | MINOR | ✅ |
| PGE-173 | Orchestrator failure degrades honestly | stop the model backend, send a widget message | HTTP **200** with `{"reply":"", "error":"request failed"}` (`error_json(e, 200, …)`) → the panel prints `request failed`, not an invented answer. Confirm the server log carries the real exception and the client body does **not** | MAJOR | ⚠️ |
| PGE-174 | Widget replies are escaped | ask the widget (🤖) to reply with `<img src=x onerror=alert(1)>` | rendered as visible text, not executed — `add()` replaces `<` with `&lt;` before `innerHTML`. Any alert box → **BLOCKER** | **BLOCKER** | ❌ |
| PGE-175 | Snippet injection via theme fields | `curl -s -X POST .../api/admin/widgets -H "X-Admin-Token: $T" -H 'Content-Type: application/json' -d '{"color":"#fff\";window.__pge175=1;//","title":"a\\\\","greeting":"b\"c"}'` then `curl -s ".../api/widget/<new>"` and read the JS | `render_snippet` (`agents/core/widget.py`) substitutes `color`/`position` **verbatim** and only replaces `"`→`'` in `title`/`greeting`. Inspect whether the emitted JS is still syntactically valid and whether `__pge175` would execute on an embedding page. An admin-authored value that lands as executable JS on a **third-party** site is a stored-XSS vector → report **MAJOR** with the file pointer; do **not** deploy the widget anywhere real | MAJOR | ❌ |
| PGE-176 | Rate limiting from a LAN device 🌐 | from a second device, POST >`JARVIS_RATE_LIMIT` (default 120) widget messages in a minute | `429` + `Retry-After`; localhost is exempt | MINOR | ✅ |

---

## 06.11 WorldView stack + the HUD's world surfaces

Three **independent** services; keep them straight or you will misattribute failures:
- **WorldView backend-api** — Fastify, `http://127.0.0.1:4000` (`worldview/quickstart.sh` step 4).
- **WorldView frontend** — Next.js, `http://localhost:3000` (`npm run dev --workspace frontend`;
  quickstart does **not** start it).
- **Signal Layer** — `http://localhost:8787`, default mode `replay`
  (`services/signal-layer/src/config.mjs`), started by `START.bat`/`./start.sh` or
  `docker compose -f docker-compose.worldview.yml up`.

The Nerva HUD's world surface (`frontend/src/modes_world.tsx`) is opened from the **`WORLD`** button
fixed at bottom-left of the v2 HUD, or the `W` key, or `#world` / `?world=1`
(`frontend/src/world_app.tsx`). It reads WorldView through **our** backend
(`GET /api/worldview/overview`, **open** tier) and the Signal Layer **directly**.

#### PGE-177 — Everything down: honest "not connected", no fabricated markers
- **Surface:** `modes_world.tsx` · `GET /api/worldview/status`, `GET /api/worldview/overview` (both **open**) · **Auto:** ✅tests/test_worldview_status_route.py, ✅tests/test_worldview_plugin.py
- **Prereq:** no WorldView, no Signal Layer running. `curl -s .../api/worldview/overview` first.
- **Steps:** 1) Read the overview JSON. 2) Open the v2 HUD, press `W`. 3) Read the whole panel.
- **Expected:** overview → `{"connected": false, "api_url": …, "recon": null}` (or `api_url:null` when
  the plugin isn't loaded). The panel shows the offline card: heading
  `SIGNAL LAYER UNAVAILABLE`, the text naming `http://localhost:8787` and the three start commands, a
  `retry` button, then a `SURFACES` block whose WorldView row reads `WorldView / 4D geospatial stack`
  with the tag **`not connected`** (red `gated` class) plus the line
  `start it: cd worldview && ./quickstart.sh`.
- **Also acceptable:** the tag `checking…` (amber `scoped`) for the first render before the first poll.
- **FAIL if:** any satellite pass, AOI, signal or map marker is displayed → **BLOCKER**; if the tag
  reads `connected` while `overview.connected` is false → **BLOCKER**.
- **Evidence:** the overview JSON + a screenshot of the offline card.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-178 | WorldView infra comes up | `cd worldview && ./quickstart.sh` | steps 1–4 print in order; Postgres readiness loop passes; `recon_windows` exists; the API listens on `http://127.0.0.1:4000`. First boot can take minutes (image pull + initdb) | MAJOR | ❌ |
| PGE-179 | Health probe | `curl -s http://127.0.0.1:4000/health` | a JSON body with a `service` field — this exact route is what `WorldViewPlugin.status()` probes (`agents/core/plugins/worldview.py:179-188`) | MAJOR | ✅tests/test_worldview_plugin.py |
| PGE-180 | HUD flips to `connected` | with the API up, reload the World panel | overview → `connected:true` + `service`; the SURFACES row tag turns **`connected`** (green `allow`) and the `start it:` hint disappears | MAJOR | ✅tests/test_worldview_status_route.py |
| PGE-181 | Recon windows appear | after the demo seed | the row is followed by `3 recon windows · N due alerts` and up to three lines `sat 40115 · sar over hormuz @ HH:MM:SS` — matching `db/seed/demo.sql` (`recon_windows`: norad `40115`, aoi `hormuz`, sensor `sar`, at +10 min / +2 h / +8 h) | MAJOR | ⚠️tests/test_worldview_plugin.py |
| PGE-182 | Connected but no recon data | `./quickstart.sh --down` the DB while leaving the API up (or query an AOI with no windows) | the line `connected · no recon data` — never an empty-but-confident window list | MAJOR | ✅tests/test_worldview_status_route.py |
| PGE-183 | Plugin fails fast, not slow | with the API port closed, time the panel load: `time curl -s .../api/worldview/overview` | seconds, not tens of seconds — `_get` uses a 5 s per-attempt timeout, 2 retries, and a circuit breaker at 3 failures; `recon_overview` issues its two sub-calls concurrently | MINOR | ✅tests/test_worldview_plugin.py |
| PGE-184 | `open` provenance | `curl -s .../api/worldview/overview` from a second LAN device 🌐 with no token | `200` — both worldview routes are **open** tier by design; confirm the body carries no household/AOI data beyond the demo scenario | MINOR | ✅tests/test_route_auth_matrix.py |

#### PGE-185 — The Hormuz **demo** seed reaches the Nerva HUD with no DEMO badge
- **Surface:** `modes_world.tsx` `WorldViewSurfaceRow` vs WorldView's own `worldview/frontend/lib/uiMode.ts` · **Auto:** ❌
- **Why it matters:** WorldView's own globe has a first-class provenance system: `isDemoFeed()` scans
  features for `properties.source === 'demo'` and `MODE_META.demo` paints an **amber `DEMO`** pill,
  frame and timeline note — its own copy states *"It never passes demo data as real"*
  (`worldview/frontend/components/SystemStatus.tsx:158`). The Nerva HUD renders the same seeded rows with no such
  marker, and the reason is in the read projection.
- **Steps:**
  1. Seed the demo scenario (`quickstart.sh` step 3, or `make db-seed`).
  2. `docker compose exec -T timescaledb psql -U worldview -d worldview -c "select norad_id,aoi_id,source from recon_windows;"`
     → confirm `source = demo` on all three rows.
  3. `curl -s http://127.0.0.1:4000/recon/windows | python -m json.tool` → look for a `source` field.
  4. `curl -s http://127.0.0.1:8080/api/worldview/overview | python -m json.tool` → look for `source`.
  5. Open the Nerva World panel and read the three `sat 40115 · sar over hormuz` lines.
  6. Open WorldView's own UI at `http://localhost:3000` (`npm run dev --workspace frontend`) and read
     the app-bar pill.
- **Expected:** step 6 shows an amber **`DEMO`** pill with the note **`synthetic data`**. Step 5 should
  carry an equivalent marker.
- **FAIL if:** steps 3–4 have no `source` field and step 5 shows the demo passes as plain live recon
  windows → **MAJOR**, with the root cause: the recon read projection
  (`worldview/backend-api/src/repositories/recon.ts`, `SELECT_COLUMNS`) omits `source`, so provenance
  is dropped before it can reach either `/recon/windows` or `/api/worldview/overview`. Two surfaces,
  one database, only one of them honest.
- **Evidence:** the psql output, both JSON bodies, and the two screenshots (Nerva panel vs WorldView
  app bar) side by side.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-186 | WorldView app bar states | drive `L` (live), scrub with `←/→` (historical), stop the API (offline) | the pill follows `MODE_META`: `LIVE`/`real feed` green · `DEMO`/`synthetic data` amber · `HISTORICAL`/`as of … UTC` · `REPLAY`/window+speed violet · `OFFLINE`/`feed unreachable` red. The connection chip reads `WS OPEN` / `CONNECTING` / `RECONNECTING` / `DISCONNECTED`, and in historical mode `HTTP · AS-OF` rather than a fake failure | MAJOR | ⚠️worldview/frontend vitest |
| PGE-187 | deck.gl globe renders 👁 | open `:3000` with data seeded | the globe/map paints; `G` toggles 2.5D map ↔ 3D globe; layer keys `1`–`5` toggle layers | MAJOR | ❌ |
| PGE-188 | No Mapbox token → honest basemap note | with `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` unset | an amber line at the bottom-left of the stage: `BASEMAP · COASTLINES (NO MAPBOX TOKEN) — add NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN=pk… to worldview/frontend/.env.local + restart for street tiles, or switch to 3D GLOBE (no token needed)`; coastline background layers render instead of tiles | MINOR | ❌ |
| PGE-189 | WebGL failure diagnoses itself 👁 | Chrome → disable hardware acceleration (or run with `--disable-gpu`), reload `:3000` | `GlobeErrorBoundary` shows `This machine can't render the globe.` + three numbered remedies + the truncated error message + a `RELOAD ⟳` button — **not** a black screen | MAJOR | ❌ |
| PGE-190 | API up, DB empty | truncate the seed, keep the API up | the `empty` variant: `Connected — no data in this window yet.` + `npm run db:seed` guidance | MAJOR | ❌ |
| PGE-191 | API down while frontend up | stop the API, keep `:3000` | the `down` variant: `WorldView is up — its data feed isn't.` naming the API URL; and the amber honesty footer `The demo feed is synthetic — WorldView will badge it. It never passes demo data as real.` | MAJOR | ❌ |
| PGE-192 | No flash on a healthy connect | reload `:3000` with everything healthy | the SystemStatus overlay never appears — a 2.5 s grace timer (`graceElapsed`) suppresses it. Contrast with run 1's cosmetic v2 "OFFLINE flash" finding, which lacks this guard | COSMETIC | ❌ |
| PGE-193 | ♿ Help overlay focus trap | press `?` on `:3000`, then Tab repeatedly, then `Esc` | `role="dialog" aria-modal="true"`, focus enters the card and **cycles inside it**; `Esc` closes; click-away closes. The listed shortcuts are exactly `Space / L / ← → / Esc / 1–5 / G / ?` and come from the same `lib/shortcuts.ts` the handler uses — so help can never advertise a binding that doesn't ship | ♿ MINOR | ⚠️ |
| PGE-194 | Demo lens is cosmetic and off by default | look for a `LENS · MONO GRADE` chip | absent unless the tour enables it; when on, `✕ OFF` dismisses it; it is a DOM overlay, so exported images must not contain it | COSMETIC | ❌ |
| PGE-195 | Signal Layer health | `curl -s http://127.0.0.1:8787/healthz \| python -m json.tool` | `{"service":"jarvis-signal-layer","ok":true,"mode":"replay",…}` — `mode` is `replay` unless `JARVIS_SIGNAL_LAYER_MODE=live` | MAJOR | ✅scripts/worldview-smoke.sh (→ `services/signal-layer` `npm test`) |
| PGE-196 | World panel metric strip | with the Signal Layer up | five badges `GLOBAL`, `PROVIDER`, `MODE`, `FRESHNESS`, `SIGNALS`; `MODE` reads **`REPLAY`** and `FRESHNESS` reads `GOOD` or amber `STALE PRESENT` | MAJOR | ❌ |
| PGE-197 | Metric strip fallbacks are literals | stop the Signal Layer but keep at least one of `brief`/`payload` cached in state (or read the source) | `PROVIDER` falls back to the literal `worldmonitor` and `MODE` to the literal `replay` even with `health === null` (`modes_world.tsx:200-201`) — record whether that reads as a live provider claim; observation-level **MINOR** | MINOR | ❌ |
| PGE-198 | Signals + evidence provenance | with the replay provider serving | each signal card shows `type · severity · confidence` and a claim-status tag; selecting one lists evidence rows with `sourceFamily`, `reliability`, `cached …`, `fetched …` and a `fresh`/`stale` tag. An unselectable/empty state reads `No relevant signals returned.` / `No source details returned for this signal.` | MAJOR | ⚠️ |
| PGE-199 | Ask Argus degrades honestly 🤖 | stop the Signal Layer, click `ask world analyst` | the answer box prints `Signal Layer unavailable: <reason>` — never an invented world assessment | **BLOCKER** | ⚠️ |
| PGE-200 | Signal Layer bearer token 🔑 | restart it with `SIGNAL_LAYER_API_TOKEN=secret`, reload the World panel | the HUD sends no `Authorization` header, so every call 401s and the panel shows `SIGNAL LAYER UNAVAILABLE`. Record the gap: "unavailable" is honest but conflates *unreachable* with *unauthorized* → **MINOR** | MINOR | ✅services/signal-layer/test/auth.mjs |
| PGE-201 | Signal Layer CORS from a LAN device 🌐 | open the HUD from a phone at `http://192.168.x.x:8080` and press `W` | blocked: the Signal Layer binds `127.0.0.1` by default and `isAllowedOrigin` only auto-allows `localhost`/`127.0.0.1`/`::1`. The panel must say unavailable rather than silently show nothing | MINOR | ✅services/signal-layer/test/core.mjs |
| PGE-202 | Port-collision trap | run WorldView frontend **and** WorldMonitor together | WorldView owns `:3000`; `docker-compose.worldview.yml` maps WorldMonitor to `:3100` for exactly this reason. If both claim 3000, the HUD's `open` link (hard-coded `http://localhost:3000` at `modes_world.tsx:86`) opens the wrong app → **MINOR** | MINOR | ❌ |
| PGE-203 | `open` link honesty | click `open` on the WorldView SURFACES row **with only the API running** | it navigates to `http://localhost:3000`, which is **not** started by `quickstart.sh` → the browser shows a connection error. The row said `connected` (the API is up) while the link target is down. Record as **MINOR**: the badge and the link describe two different services | MINOR | ❌ |
| PGE-204 | `scripts/worldview-smoke.sh` does what its name says | `bash scripts/worldview-smoke.sh` | it `cd`s to `services/signal-layer` and runs `npm test` — i.e. it smoke-tests the **Signal Layer**, not the WorldView stack. Verify it passes, and record the naming mismatch as an observation | MINOR | ✅ (it *is* the test) |
| PGE-205 | WorldView Makefile targets exist | `cd worldview && make help` | the 11 advertised targets; spot-check `make db-seed` and `make dev-api` actually run | MINOR | ❌ |
| PGE-206 | Teardown leaves nothing running | `./quickstart.sh --down` then `docker ps` | the timescaledb + redis containers are gone; the HUD's WorldView row returns to `not connected` within 30 s (its poll interval) | MINOR | ❌ |

---

## 06.12 Desktop shell (Tauri) & the native crate

Everything here except PGE-213/214 is verifiable **without** a Rust toolchain.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| PGE-207 | Shell config points at the local HUD | `python -m json.tool desktop/src-tauri/tauri.conf.json` | one window, 1280×820, resizable, `url: "http://127.0.0.1:8080/"`; `build.devUrl` the same | MINOR | ❌ |
| PGE-208 | Shell CSP is loopback-only | read `app.security.csp` | `default-src 'self' http://127.0.0.1:8080`, `connect-src` adds `ws://` + `wss://` on the same host, `object-src 'none'`, `frame-ancestors 'self'`; **no** wildcard host. `img-src` does include `https:` — note it | MAJOR | ❌ |
| PGE-209 | Version drift | `grep version desktop/src-tauri/tauri.conf.json desktop/src-tauri/Cargo.toml; grep __version__ agents/__init__.py` | conf and Cargo both read **0.9.2** while the app is **0.11.0** — a shipped installer would advertise a two-minor-old version. Record as **MINOR** (single-source-of-truth drift) | MINOR | ❌ |
| PGE-210 | Brand drift | `grep productName desktop/src-tauri/tauri.conf.json` | `"Jarvis Hub"` — the product renamed to **Nerva** on 2026-07-19 (CLAUDE.md). Same in `static/manifest.json` (PGE-008). Record as **COSMETIC**, one finding covering both | COSMETIC | ❌ |
| PGE-211 | Build assets are missing | `ls desktop/dist desktop/src-tauri/icons` | **both absent**. `build.frontendDist` is `"../dist"` and `bundle.icon` is `["icons/icon.png"]`, and `desktop/README.md` lists the icon as a prerequisite — so `cargo tauri build` cannot succeed on a clean checkout. Record as **MINOR** (documented host-side prerequisite) but state it explicitly so nobody reports "the desktop app doesn't build" as a new bug | MINOR | ❌ |
| PGE-212 | Tray promises vs code | read `desktop/src-tauri/src/main.rs` against `desktop/README.md` | README says "tray + wake-word listener hook in `setup()`"; `setup()` is an empty `Ok(())` and there is **no tray menu** — only `trayIcon` in the conf with `menuOnLeftClick: false`. So a built app has an icon whose clicks do nothing. Record as **MINOR** doc-vs-code gap | MINOR | ❌ |
| PGE-213 | Dev run 🖥 | with the toolchain installed and the hub on :8080: `cd desktop && cargo tauri dev` | a native window renders the **v2 HUD**; chat works; the CSP does not block any HUD request (watch the webview console) | MAJOR | ❌ |
| PGE-214 | Autostart plugin 🖥⏱ | in the dev run, enable autostart, reboot | the app relaunches on login; disabling it stops that. `tauri-plugin-autostart` is wired with an empty arg vector | MINOR | ❌ |
| PGE-215 | Native crate is optional | `python -c "import jarvis_native"` on a box where it was never built | `ModuleNotFoundError`, and the hub still runs — `agents/core/native_fallback.py` is the pure-Python path. Confirm `/status` and a chat turn work unchanged | MAJOR | ⚠️ |
| PGE-216 | Native crate parity 🖥 | if built (`maturin develop --release`), compare `jarvis_native.cosine_similarity`, `top_k_similar`, `count_tokens` against the Python fallback on the same inputs | identical results (`count_tokens` is whitespace splitting in both) | MINOR | ⚠️ |
| PGE-217 | 0.64 host overlay is **not shipped** | `grep -n "0.64" BACKLOG.md` and search `route_surface.json` for a quickbar route | `agents/core/quickbar.py` (the offline command service) exists, but the Tauri always-on-top overlay + global shortcut registration are owner-gated remaining work, and there is **no** HTTP route for it. **Do not write a test for the floating bar** — record it as a known gap | — (gap) | ✅tests/test_quickbar.py (service only) |

---

## 06.X Degraded & honest-state matrix

What every surface in this section **must** show per condition. Any cell showing plausible-looking data
instead of the stated state is a finding at the severity in the last column.

| Condition | Mission Control | `/brain` | Legacy HUD `/v1` | PWA | Widget | WorldView + World panel | Desktop shell | Severity if wrong |
|---|---|---|---|---|---|---|---|---|
| Server stopped | after 3 polls: red `STALE FEED`, last values frozen; actions flash `✗ network` | feed poll fails silently — see PGE-084 | offline shell may paint from cache; SYSTEM widget must **not** show `BONOBO-WS` | cached `/` shell loads; `/api/*` resolve to `Response.error()` | bubble renders (script may be cached by the host page); message → `(connection error)` | `not connected` + `start it:` hint | native window shows the webview's own error page | BLOCKER if any surface asserts live data |
| No model backend 🤖 | unaffected (read-only feed) | `0 EVENTS`, `$0`, roster-seeded mesh | chat returns an honest error; SYSTEM `MODEL` = `unknown` | n/a | `200` + `{"reply":"","error":"request failed"}` | Ask Argus prints `Signal Layer unavailable: …` if the layer is down; otherwise a real replay answer | as HUD | BLOCKER if any reply is invented |
| Qdrant/Neo4j/n8n down | feed still `200` twenty times (PGE-076) | unaffected | Systems panel sections show placeholders | n/a | n/a | unaffected | n/a | MAJOR if the feed 500s |
| No admin token | `ADMIN` grey or `ADMIN LOCKED`; approvals degrade to counts + `T<n>` tags, **no buttons**; `/autonomy/approvals` polling stops | unaffected (feed is user-tier) | admin panels show `admin token required (set it in ⚙ Settings)` | n/a | issuing a token 401s | unaffected (both worldview routes are open) | n/a | MAJOR if a card errors or hides instead of degrading |
| `JARVIS_USER_TOKEN` set | page navigation itself 401s (PGE-012) | same, plus a silent all-zero page if only the feed is blocked | `auth.js` prompts once, stores, retries | worker may serve the cached shell over a 401 feed | unaffected (widget routes are open) | worldview routes open; Signal Layer unaffected | as HUD | MAJOR |
| No host presence daemon | `OWNER —` (grey) | n/a | n/a | n/a | n/a | n/a | n/a | MAJOR if it claims AWAY |
| Presence signal stale (>TTL) | `OWNER <STATE> · STALE`, grey, **not** away | n/a | n/a | n/a | n/a | n/a | n/a | MAJOR if `AWAY→ESC` shows |
| Empty DB / fresh install | `0 EVENTS` / `0 PENDING` / `0 WORKSPACES` with the four literal empty strings | mesh seeded from roster, all KPIs 0 | empty calendar/notifications arrays; empty ticker | precache populated, nothing else | no widgets listed | `not connected` | n/a | MAJOR if any seeded corpus appears |
| No dev-lock dir | `lock dir absent (memory_logs/) — dev locks are local-only per machine`; four dim chips | n/a | n/a | n/a | n/a | n/a | n/a | MINOR |
| Lock dir present, empty | `no file locks — dev swarm idle or coordinating via draft PRs` | n/a | n/a | n/a | n/a | n/a | n/a | MINOR |
| A2A disabled | `A2A OFF`; no A2A block in the approvals card | n/a | n/a | n/a | n/a | n/a | n/a | MINOR |
| WorldView API down, frontend up | n/a | n/a | n/a | n/a | n/a | `WorldView is up — its data feed isn't.` + start steps | n/a | MAJOR |
| WorldView API up, DB empty | n/a | n/a | n/a | n/a | n/a | `Connected — no data in this window yet.` + seed steps; HUD row `connected · no recon data` | n/a | MAJOR |
| Demo seed loaded | n/a | n/a | n/a | n/a | n/a | WorldView app bar: amber `DEMO` / `synthetic data`. **Nerva panel: currently unbadged — PGE-185** | n/a | MAJOR |
| No WebGL | n/a | mesh canvas is 2D — should still draw | NetworkBrain is 2D | n/a | n/a | `This machine can't render the globe.` + 3 remedies | n/a | MAJOR if black screen |
| No Mapbox token | n/a | n/a | n/a | n/a | n/a | amber `BASEMAP · COASTLINES (NO MAPBOX TOKEN)` note | n/a | MINOR |
| Offline / air-gapped 🌐 | zero external requests (PGE-075) | only the two footer `<a href>`s are external | fonts are local (`/static/fonts`) | designed for this | host page must be local too | Mapbox tiles fail → coastline fallback | CSP forbids non-loopback | MAJOR if any page needs a CDN |
| Post-`UPDATE.bat`, worker installed ⏱ | n/a | n/a | n/a | **must not serve the old bundle** (PGE-156) | n/a | n/a | n/a | MAJOR |

---

## 06.Y Negative, adversarial & abuse cases

| ID | Attack / abuse | Do | Expect | Fail | Auto |
|----|----------------|----|--------|------|------|
| PGE-218 | Forged admin token on the page | put `hud.admin_token = "x"*512` in localStorage, reload Mission Control | `ADMIN LOCKED`; approvals degrade; polling of `/autonomy/approvals` stops; no 500 in the log | MAJOR | ✅tests/test_route_auth_matrix.py |
| PGE-219 | Admin token in a URL | `.../mission-control?token=devadmin` | ignored — there is no query-param auth path anywhere in `agents/web.py`. If it works → **BLOCKER** | BLOCKER | ✅ |
| PGE-220 | Tier confusion | `POST /autonomy/tasks/1/decision -H "X-User-Token: devuser"` | `401` — a user credential must never satisfy `_admin_guard` | BLOCKER | ✅tests/test_route_guard_contracts.py |
| PGE-221 | Path traversal on a mission action | `POST /api/missions/../../status` and `POST /api/missions/1/../cancel` | `404`/`405`, never a match on another route | MAJOR | ✅tests/test_route_parity_guard.py |
| PGE-222 | Non-numeric ids from the page | in the console call `decide("abc","accept")` and `missionAct("1;drop","cancel")` | `Number()` coerces to `NaN` / `1` → the request either 404s or hits the sanitised id; the flash reports a numeric status. No SQL/None reaches the store | MAJOR | ⚠️ |
| PGE-223 | Oversized payload | `curl -X POST .../api/widget/$TOK/message -H 'Content-Type: application/json' -d "{\"message\":\"$(python -c 'print("A"*200000)')\"}"` | a bounded rejection (413/400/422) or a bounded honest reply — never an OOM, never a 60 s hang | MAJOR | ⚠️ |
| PGE-224 | 10 000-char chat input | paste 10 000 chars into the legacy HUD chat and the widget | both accept or reject cleanly; the UI does not freeze; no layout break | MINOR | ⚠️ |
| PGE-225 | Empty + whitespace-only input | send `""`, `"   "`, `"\n\n"` to widget and legacy chat | rejected client-side or `400`; **no** LLM call fires (watch the tracer) | MINOR | ✅ |
| PGE-226 | HTML/JS injection via a dev-lock message | `python lock.py acquire claude '<img src=x onerror=alert(1)>'` then reload Mission Control | the chip tooltip and any row show the text **escaped** (`esc()` covers `& < > " '`); no alert | MAJOR | ❌ |
| PGE-227 | Injection via a mission title | create a mission titled `</span><script>alert(1)</script>` | escaped in the MISSIONS row; no script executes | MAJOR | ❌ |
| PGE-228 | Injection via an agent id | if you can register an agent id containing `"` | escaped in the map label and node card | MINOR | ❌ |
| PGE-229 | Quote in an A2A task id | craft an inbox item whose id contains `'` | the `APPROVE` button either works or is inert — `esc()` turns `'` into `&#39;`, which the HTML attribute decodes back into the JS string literal, so the handler may be a syntax error. Fails **closed** (button does nothing) is acceptable; script execution is a **BLOCKER** | MAJOR | ❌ |
| PGE-230 | RO diacritics everywhere | use `Ștefan · măsurătoare · țară · încărcare` as a mission title, a widget greeting, a dev-lock message and a chat message | rendered correctly (no mojibake) in Mission Control rows, the widget panel, the legacy HUD and `/brain` feed rows; all files are UTF-8 | MINOR | ⚠️ |
| PGE-231 | Emoji + RTL + zero-width | title `🛰️ العربية​test` | renders without breaking the flex layout or the canvas label metrics | COSMETIC | ❌ |
| PGE-232 | Rapid clicking a moving row | with 10+ pending decisions, click ACCEPT repeatedly while the 2 s poll re-renders | exactly one decision per click, and the decision applies to the **id baked into the clicked button** — verify each flashed `task <id>` matches what you meant to act on. `state.busy` must suppress overlapping calls | MAJOR | ❌ |
| PGE-233 | Concurrent writes from two tabs | open Mission Control in two tabs; accept the same task in both within 1 s | the second gets a non-2xx (already decided) and flashes `✗ (<code>)`; the audit log has exactly **one** decision for that task | MAJOR | ⚠️ |
| PGE-234 | Legacy + Mission Control fighting | engage the kill-switch in the legacy Console while Mission Control is open | Mission Control's `SYSTEM HALTED` chip appears within 2 s; disengaging from Mission Control's side is reflected in the legacy panel on its next reload | MAJOR | ❌ |
| PGE-235 | Back-button mid-flow | click OPEN LIST on the A2A block, then press Back, then Forward | the page re-initialises cleanly (`state.a2aOpen` resets); no duplicated listeners, no double-firing polls (check Network for exactly 2 requests/2 s) | MINOR | ❌ |
| PGE-236 | Refresh mid-decision | click ACCEPT and hit F5 within ~100 ms | the decision either applied once or not at all — never twice. Verify against `GET /api/admin/audit` | MAJOR | ⚠️ |
| PGE-237 | Restart mid-operation ⏱ | start a mission, kill the server with `SIGKILL`, restart, reload Mission Control | the mission's persisted status is consistent (no half-transitioned row); dev locks older than 30 min read `STALE` rather than `ACTIVE` | MAJOR | ⚠️ |
| PGE-238 | Clock skew ⏱ | set the OS clock 2 days **back**, reload Mission Control and `/brain` | dev-lock ages must not render as negative (`_age` clamps at 0, `swarm.py:55`); `/brain` `TODAY` may legitimately show 0 events. Set the clock 2 days **forward**: all locks read `STALE`, activity timestamps are in the future — confirm nothing crashes and record how it reads | MINOR | ⚠️ |
| PGE-239 | Leap into a new day ⏱ | leave `/brain` open across local midnight with `TODAY` selected | `EVENTS` resets at the UTC day boundary (`_today_start` uses UTC — note the discrepancy with local midnight as an observation) | MINOR | ✅tests/test_brain_summary.py::test_range_filters_old_traces |
| PGE-240 | Feed flooding | drive 500 chat turns, then load Mission Control and `/brain` | Mission Control caps activity at 60 rows; `/brain` caps `recent` at 60 and the feed DOM at 8 rows; neither page's memory grows unbounded over 10 min | MAJOR | ✅tests/test_swarm_summary.py:111 |
| PGE-241 | 2 s poll under a slow feed | throttle to "Slow 3G" in DevTools with Mission Control open | requests may overlap (there is no in-flight guard on `poll`/`pollAdmin`) — confirm the UI does not flicker between stale and fresh states, and that request count stays bounded | MINOR | ❌ |
| PGE-242 | Rate limit vs the 2 s poll 🌐 | open Mission Control from a second LAN device with a valid user token for 5 min | authenticated requests are exempt from `JARVIS_RATE_LIMIT`; a **tokenless** device at 2 requests/s would exceed 120/min → `429 + Retry-After`, and the page should show `STALE FEED` rather than a blank | MAJOR | ✅ |
| PGE-243 | Reverse-proxy spoofing 🌐 | with `JARVIS_TRUSTED_PROXY` unset, request `/api/swarm/summary` from a LAN device sending `X-Forwarded-For: 127.0.0.1` | `403` — `_real_client_host` returns `""` for an untrusted proxy and fails closed (HF-7) | BLOCKER | ✅ |
| PGE-244 | CSP kill-switch | set `JARVIS_DISABLE_CSP=1`, restart, check headers | the CSP header disappears (documented escape hatch). Confirm this is **not** the default and note it in the run record if the owner's box has it set | MAJOR | ✅tests/test_hud_security_headers.py |
| PGE-245 | Clickjacking a standalone page | host `<iframe src="http://127.0.0.1:8080/mission-control">` on the `:9099` foreign origin | blocked by `X-Frame-Options: SAMEORIGIN` + `frame-ancestors 'self'` | MAJOR | ✅tests/test_hud_security_headers.py |
| PGE-246 | Widget token brute force | request 200 random `/api/widget/<random>` paths | all `404`; tokens are `secrets.token_urlsafe(12)`; the LAN rate limiter applies to a non-local caller | MAJOR | ✅ |
| PGE-247 | localStorage poisoning | set `hud.user_token` to a 1 MB string, reload `/v1` | the header is sent and rejected; the page prompts once and recovers; no crash | MINOR | ❌ |
| PGE-248 | Two HUDs, one worker | with the worker installed from `/v1`, open `/v1` and `/` simultaneously and interact in both | no cross-talk: `/` gets the v2 bundle (or the cache-first copy — PGE-156), `/v1` the legacy one; localStorage keys `hud.admin_token` / `hud.user_token` are shared by design, so a token set in one applies to the other. Confirm that is the observed behaviour | MINOR | ❌ |

---

## 06.Z Coverage ledger

| Group | Cases | Needs | Auto-covered | Notes |
|---|---|---|---|---|
| 06.1 Reachability, auth tiers & shells | 12 (PGE-001…012) | server only; 🌐 for PGE-012's LAN variant | 6 fully, 3 partial | PGE-012 is the gate for all of 06.2–06.6 |
| 06.2 Mission Control header chips | 15 (013…027) | 🔑 admin token; ⏱ for the presence TTL | 4 ✅ · 6 ⚠️ | PGE-026 is the six-state presence walk |
| 06.3 Swarm map & activity | 12 (028…039) | 👁; 🤖 for traffic | 3 ⚠️ | PGE-038 is a privacy cross-check |
| 06.4 Approvals & payload-free | 15 (040…054) | 🔑 admin; A2A enabled for 050–054 | 1 ✅ (whitelist) · rest ⚠️/❌ | PGE-042 is the feed-level leak measurement |
| 06.5 Missions & dev swarm | 22 (055…076) | filesystem write for locks | 8 ✅ · 4 ⚠️ | PGE-074 is a documented-but-absent surface |
| 06.6 Brain / Neural Mesh | 22 (077…098) | 👁; ⏱ for the 30 min soak | 8 ✅ · 2 ⚠️ | PGE-084 is the silent-zeros case |
| 06.7 Legacy static HUD | 26 (099…124) | 🖥 for 099/100; 🤖 for chat; ♿ for 123 | ~4 ⚠️ · mostly ❌ | 099/100/101 are the three seed-as-live cases |
| 06.8 Divergence sweep | 21 (125…145) | both HUDs + curl, same moment | all ⚠️ (logic tested, parity not) | novel; PGE-125 re-proves R7 |
| 06.9 PWA | 12 (146…157) | ⏱ for the upgrade cycle | 1 ⚠️ · rest ❌ | PGE-156 is the stale-bundle case |
| 06.10 Widget | 19 (158…176) | 🔑 admin; a second local origin; 🌐 for 176 | 9 ✅ · 2 ⚠️ | PGE-175 is a security observation, not a deploy |
| 06.11 WorldView + world surfaces | 30 (177…206) | Docker + Node; 👁; ♿ for 193 | 8 ✅ · 6 ⚠️ | PGE-185 is the demo-provenance gap |
| 06.12 Desktop shell & crate | 11 (207…217) | 🖥 only for 213/214/216 | 2 ⚠️ · 1 ✅ (quickbar) | 9 of 11 need no build |
| 06.Y Negative & adversarial | 31 (218…248) | 🌐 for 242/243; ⏱ for 237–239 | 11 ✅ · 8 ⚠️ | route-guard matrix carries most of the auth side |
| **Total** | **248 cases (PGE-001 … PGE-248)** | 4 need 🖥, 6 need 🌐, 6 need ⏱, 3 need 🔑-class services, 5 are ♿ | **≈54 ✅ · ≈52 ⚠️ · ≈142 ❌** | the ❌ mass is exactly why this section exists: rendering, provenance and staleness are invisible to the offline suite |

---

## Open gaps found while writing

Observations only — **no code was changed.** Each is a pointer for the owner to triage.

1. **`agents/web/index.html` is a dead 402-line file.** No route serves it; `GET /` and `GET /v1` read
   `agents/web/templates/index.html` (`agents/web.py:740,743,748`). It still carries the unescaped
   `innerHTML` news sink flagged in `docs/research/2026-06-23-independent-audit-merged.md:85`
   (`agents/web/index.html:369` region). Dead code that looks like the shipped shell will mislead the
   next reader — and any future route that serves it reintroduces the sink.
2. **`GET /mission-control` and `GET /brain` are user-guarded page shells.** Every other shell (`/`,
   `/v1`, `/v2`, `/admin`) is open, with the JS supplying tokens. A browser navigation cannot send
   `X-User-Token`, so setting `JARVIS_USER_TOKEN` — which the QA runbook §2 instructs — makes both
   pages unopenable (`agents/core/routers/swarm.py:279`, `brain.py:177`). Either the shells should be
   open like their siblings, or the runbook needs a warning. **Test: PGE-012.**
3. **`brain.html` sends no auth headers and swallows every error.** `load()` at
   `agents/web/brain.html:578` is `fetch(...).then(r=>r.json()).then(applyData).catch(()=>{})` — no
   `r.ok`, no `X-User-Token`, no visible failure. `mission_control.html:149-155` does it correctly
   (`H()` attaches both tokens) and shows `STALE FEED` after 3 failures. **Test: PGE-084.**
4. **The user-tier swarm feed carries mission step results and workflow prompt/output previews.**
   `_PREVIEW_FIELDS` (`agents/core/routers/swarm.py:140`) protects `autonomy.pending_preview`, but
   `missions` is a raw `m.to_dict()` (`:236-237`) and `Mission.plan` is documented as containing
   `result` per step (`agents/core/autonomy/missions.py:94`), while `workflows.runs[].steps[]` from
   `WorkflowEngine.recent()` carries `input_preview` + `output_preview` — 160 chars of rendered prompt
   and model output (`agents/core/workflows/engine.py:183-192`). The page renders none of it, so this
   is a feed-tier leak, not a visible one — but the React port (H34.4) and mobile will consume the same
   feed. `tests/test_swarm_summary.py:176` asserts *passthrough* with toy dicts, so the suite cannot
   catch it. **Test: PGE-042.**
5. **Mission Control never renders workflow runs or sub-agents**, though `COWORK_QA_RUNBOOK.md` §4b
   lists both as chips to cross-check and `build_swarm_summary` computes both. The only occurrence of
   "workflow" in the page is the HTML header comment (`agents/web/mission_control.html:7`).
   **Test: PGE-074** (recorded as a gap, not a pass).
6. **The legacy HUD's fallback hardware is the docs' reference rig.**
   `agents/web/static/i18n.js:180-184` defines `env.fallback_host = 'BONOBO-WS'`,
   `env.fallback_gpu = 'RTX 5090 · 24GB'`, `env.fallback_model = 'google/gemma-4-31b-a4b'`, and
   `static/data.js:30-35` adds `ram_used: 42, ram_total: 192, vram_used: 10, gpu_load: 30,
   latency: 2.1`. The backend is scrupulously honest (`agents/web.py:565-630` yields
   `unknown`/`none`/`0`); the frontend seeds over it whenever `/status` is unreachable or returns
   `{"status":"starting"}`. This is run-1 BLOCKER #2 rendered by the HUD itself. **Test: PGE-099.**
7. **`useLiveSys` synthesizes the SYSTEM meters.** `agents/web/static/enhancements.js:200-215`
   recomputes RAM/VRAM/GPU-load/latency every 1.4 s as `base + sin(t·k) + random()`, and
   `static/app.js:149,351` feeds that (`liveSys`, not `sys`) to the widget. The RAM clamp is
   `clamp(v, 60, ram_total - 8)`, so on any machine with under 68 GB the displayed "used" RAM is pinned
   at **60 GB** — potentially above the machine's total. The bracket's status label is also the
   hard-coded literal `NOMINAL` (`components.js:190` / `i18n.js:149`). **Test: PGE-100.**
8. **The Agent Dossier modal is entirely mock data.** `static/app.js:432` passes
   `DOSSIER[dossierAgent]` from the `const DOSSIER` block in `static/data.js`; the modal presents
   `model` (always `gemma-4-26b-a4b`), `channel`, `heartbeat`, `policy`, a plugin pill list, a skills
   count, `memory_facts` and a `soul_excerpt` as configuration. Only the separate **View soul** button
   hits a real endpoint (`GET /api/agents/{id}/soul`), which makes the fake fields around it more
   convincing. **Test: PGE-101.**
9. **`data.js` ships six more unused mock datasets to every legacy-HUD visitor** —
   `MEMORY_STATS` (47 sessions / 1284 vectors / 89 KG entities), `LEARNING` (847 interactions / 91 %),
   `SECURITY`, `BENCH` (p50 4.2 s / p95 7.8 s), `PLUGINS` (11 plugins, all `enabled: true`),
   `ROUTING_DECISION`, `ORCHESTRATION_TRACE`. None is referenced outside `data.js`, so they are dead
   weight — but they are one `||` away from being rendered, and `COGNITION_SCORING` in the same file
   contains apparently personal keywords (`raiffeisen`, `digitaholic`, `cosmina`, `bmw`, `max`) in a
   committed, browser-served file. Worth an owner decision on both counts (privacy + dead seed data).
10. **The legacy plugin toggle reports success on a 401.** `PUT /plugins/{plugin_id}/toggle` is
    **admin**-tier, but `static/app.js:402` calls plain `fetch` with no admin header and only catches
    *network* errors; a 401 body parses as JSON, so the handler logs `plugin toggled:` and dispatches
    `jarvis:plugins_updated` as if it worked. **Test: PGE-120.**
11. **`JARVIS_AGENT_META` and `DOSSIER` cover 15 of 17 agents** (`static/data.js:43-59`). `howard` and
    `argus` get tier `FND`, an empty role and no glyph on the happy path, and on the `/api/agents`
    failure path the rail renders only 15 agents each labelled with the hard-coded model
    `google/gemma-4-31b-a4b` (`data.js:98`) — a count that contradicts `/status` `agents_total: 17`.
    Double-clicking either agent opens nothing (`dossier-modal.js:168`). **Tests: PGE-102, 103, 101.**
12. **The service worker can pin a stale HUD indefinitely.** `static/sw.js` has a static
    `CACHE_NAME = 'jarvis-hud-v3'`, precaches `'/'`, and serves navigations cache-first. Registration
    happens only in the legacy shell (`templates/index.html`) but its scope is `/`, so it governs the
    **v2** HUD at `/`. `UPDATE.bat` bumps neither the cache name nor the browser state. Separately, the
    precache list omits the `?v=9.9.9` query the legacy page actually requests, so `caches.match`
    misses those entries and the precache is mostly inert. **Tests: PGE-147, 148, 156.**
13. **`render_snippet` does not escape widget theme values.** `agents/core/widget.py` substitutes
    `color` and `position` verbatim into JS string literals and only replaces `"` → `'` in `title` and
    `greeting`. A backslash or a crafted `color` value yields arbitrary JS in a script that is
    deliberately served to a **third-party** website. Admin-tier to set, so not privilege escalation —
    but it is stored XSS against the embedding site. **Test: PGE-175.**
14. **WorldView drops demo provenance before it can reach Nerva.** The seed marks rows
    `source='demo'` (`worldview/db/seed/demo.sql`, `recon_windows`), and WorldView's own frontend uses
    exactly that field to paint an amber `DEMO` pill (`worldview/frontend/lib/uiMode.ts:isDemoFeed`,
    `MODE_META.demo`) while its copy promises *"It never passes demo data as real"*
    (`worldview/frontend/components/SystemStatus.tsx:158`). But `SELECT_COLUMNS` in
    `worldview/backend-api/src/repositories/recon.ts` omits `source`, so `/recon/windows` cannot carry
    it, so `/api/worldview/overview` cannot carry it, so the Nerva World panel renders demo satellite
    passes unbadged. **Test: PGE-185.**
15. **`modes_world.tsx` falls back to literal service names.** `PROVIDER` defaults to `'worldmonitor'`
    and `MODE` to `'replay'` even when `health` is `null` (`frontend/src/modes_world.tsx:200-201`), so a
    dead provider still reads as a named live one. Also, the `open` button is hard-coded to
    `http://localhost:3000` (`:86`) — the Next.js frontend, which `quickstart.sh` does not start — so
    the row can say `connected` (the API is up) next to a link that fails. **Tests: PGE-197, 203.**
16. **The World panel sends no bearer token to the Signal Layer.** With `SIGNAL_LAYER_API_TOKEN` set
    (`services/signal-layer/src/config.mjs`), `getJson`/`postJson` in `modes_world.tsx:47-61` omit
    `Authorization`, so everything 401s and the panel reports `SIGNAL LAYER UNAVAILABLE` — honest, but
    it conflates *unreachable* with *unauthorized*. **Test: PGE-200.**
17. **`scripts/worldview-smoke.sh` does not smoke WorldView.** Its two lines `cd`
    to `services/signal-layer` and run `npm test`. There is **no** `scripts/worldview-smoke.sh`
    (that directory holds `demo-feed.mjs` and `seed-live.mjs`). A reader following the name will test
    the wrong service. **Test: PGE-204.**
18. **The desktop shell cannot be built from a clean checkout, and its metadata has drifted.**
    `desktop/dist` and `desktop/src-tauri/icons/` do not exist, while `tauri.conf.json` requires
    `frontendDist: "../dist"` and `bundle.icon: ["icons/icon.png"]`; `productName` is `"Jarvis Hub"`
    (pre-Nerva) and both `tauri.conf.json` and `Cargo.toml` say version **0.9.2** against
    `agents/__init__.py` **0.11.0**. `desktop/README.md` promises "tray menu + wake-word listener" in
    `setup()`, which is an empty `Ok(())`. **Tests: PGE-209 … 212.**
19. **`static/manifest.json` is still branded "Jarvis Hub"** with an SVG-only icon set — flag whether
    Chrome warns about installability on the owner's version. **Tests: PGE-008, 153, 154.**
20. **Two brain-feed fields are hard-coded constants that read as computed metrics:**
    `unattributed_token_pct: 0` and `unpriced_models: []` (`agents/core/routers/brain.py:167-168`), so
    the footer always asserts `0% unattributed` and the amber unpriced-models banner can never fire.
    `rtk: None` and `budget_*_eur: None` are handled honestly by the page (panel hidden, `no cap`).
    **Tests: PGE-085 … 088.**
21. **`/brain`'s `TODAY` range is UTC, not local.** `_today_start` (`brain.py:46-48`) uses
    `timezone.utc`, so on the owner's local timezone the `TODAY` window rolls over at a time other than
    local midnight. **Test: PGE-239.**
22. **Could not verify (needs the owner's box or a running stack):** the actual rendered appearance of
    every case marked 👁, whether Chrome's install prompt accepts the SVG-only manifest, whether the
    stale-worker scenario (PGE-156) reproduces on the owner's specific Chrome version, the deck.gl
    globe render and the WebGL-failure boundary, `cargo tauri dev`/`build` behaviour, and whether
    `jarvis_native` is built on the owner's machine. Every one of these is written as a step a tester
    executes, not as an asserted result.

*Line numbers in this file were correct at the revision it was written against; re-grep before relying
on any `file:line` pointer.*
