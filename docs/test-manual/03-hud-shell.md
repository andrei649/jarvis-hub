# 03. HUD v2 shell — chrome, navigation, chat pane

> **Scope.** Everything that frames the panels: the served bundle and its build identity, the TopBar
> (clock, badges, toggles), the situation Ticker, the nav Rail (all 16 modes + 3 separators), the
> command Palette, the left RosterColumn and right ContextColumn, the four overlays (Ambient, Cinema,
> Console, Provenance/Dossier), the cockpit chat pane (composer, streaming, stop, transcript
> rehydration, rich-text rendering), the FIRST RUN gate and onboarding dial, demo mode + LiveSourceChip
> provenance, and the cross-cutting layer (localStorage prefs, analytics beacon, responsive breakpoints,
> keyboard-only operation, reduced motion, contrast). **Deliberately left to siblings:** the *contents*
> of each capability mode and each Console panel (§04, §05), the Neural Mesh canvas internals (§05),
> the voice loop (§06), Mission Control / standalone pages / legacy `/v1` HUD (§07), mobile & WorldView
> (§08), agent answer quality and the fabrication rail itself (§02). Where a shell check needs a panel
> as a cross-check witness, it names the panel but grades only the shell.
>
> **Prereqs for this whole section.** Nerva booted from the repo root (`python serve.py`, default
> `JARVIS_PORT=8080` — `serve.py:67`); Chrome or Edge on the RTX 5090 Windows box; the v2 bundle present
> at `agents/web/v2/index.html` + `agents/web/v2/assets/` (already committed — `agents/web.py:751-767`
> returns a 503 "HUD v2 not built" page if it is missing); DevTools available (Console, Network,
> Application → Local Storage, device-toolbar). For the whole-section baseline run **do not** set
> `JARVIS_USER_TOKEN` (localhost is exempt — `agents/web.py:201-208`); §03.Y turns it on deliberately.
> A model backend (LM Studio / Ollama) is needed only for the 🤖 cases.
>
> **Time.** ~3 h 15 m for one tester end to end: 25 m boot/build identity + TopBar, 20 m nav + palette,
> 25 m overlays, 30 m columns, 40 m chat pane, 25 m first-run (needs two clean profiles), 20 m demo/
> provenance, 20 m responsive + keyboard + a11y, 20 m the adversarial set. Add 30 m if you rebuild the
> bundle (SHL-002).

Legend markers used here: 🔑 real secret/service · 🤖 model backend · 👁 visual judgement ·
🖥 owner hardware · 🌐 second LAN device · ⏱ restart/day boundary/soak · ♿ accessibility.
`Auto:` ✅ covered offline · ⚠️ partial · ❌ none.

---

## 03.1 Boot, build identity & the cold-navigation contract

#### SHL-001 — the served bundle is the bundle you are testing
- **Surface:** `GET /v2` (SPA shell) · **Tier:** open · **Auto:** ⚠️`frontend/e2e/hud.spec.ts` (mounts in real Chromium, no uncaught errors)
- **Why it matters:** run 1's false Kill-Switch "ENGAGED" was traced to *the committed v2 bundle*
  diverging from source. Every 👁 case below grades pixels, so you must first know which code painted them.
- **Steps:** 1) `curl -s http://127.0.0.1:8080/v2 | findstr assets` 2) note the hashed filenames.
  3) `dir agents\web\v2\assets` 4) compare.
- **Expected:** the `<script type="module" src>` and `<link rel=stylesheet href>` in the response name
  files that exist under `agents/web/v2/assets/`. On this revision `index.html` references
  `/v2/assets/index-BQpwz2br.js` + `/v2/assets/index-BhuUO_6F.css`, and both files are present.
- **FAIL if:** a referenced asset 404s (the HUD will paint a blank `#root`) → **BLOCKER**.
- **Evidence:** the two filenames + `git rev-parse --short HEAD`, recorded in §0 of the run record.

#### SHL-002 — source ↔ bundle parity (do this once per run) 👁
- **Surface:** `frontend/` build · **Auto:** ❌
- **Steps:** 1) `cd frontend && npm ci && npm run typecheck && npm test` → typecheck clean, **373**
  vitest tests pass (the count in `project-status.json`). 2) `npm run build` → output lands in
  `../agents/web/v2` (`frontend/package.json` description). 3) `git status --short agents/web/v2`.
- **Expected:** either no diff (the committed bundle *is* the current source) or a diff you then use
  for the rest of the run — reload the HUD after building so §03.2-03.11 grade current code.
- **Also acceptable:** a diff limited to the asset hash + `index.html` reference (deterministic-build noise).
- **FAIL if:** the vitest count differs from `project-status.json` → **MAJOR** (finding in its own right);
  the build errors → **BLOCKER**.
- **Evidence:** `npm test` tail, `git status` output.

#### SHL-003 — cold navigation must not assert "unreachable" (run-1 cosmetic regression) 👁⏱
- **Surface:** TopBar DATA badge (`shell.tsx:42`) + RosterColumn empty text (`shell.tsx:204`) · **Auto:** ❌
- **Why it matters:** the HUD's first paint is a first impression *and* an honesty claim. State defaults
  are `serverUp=false` (`app.tsx:107`) and `agents=[]` (`app.tsx:70`), and the first poll only lands
  after `loadJarvisData` resolves (`app.tsx:354-371`).
- **Prereq:** server confirmed healthy first: `curl -s http://127.0.0.1:8080/readyz` and `/status` both 200.
- **Steps:** 1) open a **fresh tab**, DevTools open with "Disable cache" ticked, Network throttled to
  "Slow 4G" so the frame is easy to catch. 2) navigate to `http://127.0.0.1:8080/v2`. 3) screenshot within
  the first second. 4) let it settle 5 s and screenshot again.
- **Expected (the fix):** the first paint shows a *neutral* connecting state — LLM badge `○ —`
  (tooltip "LLM state unknown"), DATA badge neither green nor claiming failure, and the roster body
  saying something like "connecting…". After settle: `AGENTS 17 en`, DATA `● LIVE` or `○ EMPTY`, roster
  populated.
- **Known-current behaviour (expected to reproduce on this build):** first paint shows DATA
  `○ OFFLINE` with tooltip **"server unreachable"** and the roster body **"roster offline — server
  unreachable"** while `/status` was answering 200 the whole time.
- **FAIL if:** the false-unreachable flash is still there → **MINOR (cosmetic)**, log it once against
  the §R "Cold-navigation" row. If the state does **not** self-correct within two 30 s poll cycles → **MAJOR**.
- **Evidence:** both screenshots + the `/status` 200 timestamp from the same session.

#### SHL-004 — "server up, roster empty" must not read as "server unreachable" 👁
- **Surface:** `shell.tsx:204` · **Auto:** ❌
- **Why it matters:** `RosterColumn` prints "roster offline — server unreachable" on the single condition
  `agents.length===0`, with no reference to `serverUp`. `/status` is **open** tier but `/api/agents` is
  **user** tier — so a token-protected instance yields serverUp `true` + roster `[]`.
- **Prereq:** restart with `JARVIS_USER_TOKEN=devuser` set (see SHL-178 for the token-prompt path).
- **Steps:** 1) load `/v2`. 2) dismiss the token prompt (press Cancel). 3) read the DATA badge and the roster body.
- **Expected:** DATA badge is *not* OFFLINE (the server answered `/status`), and the roster says something
  that distinguishes "not authorized / no roster" from "server unreachable".
- **FAIL if:** the roster claims the server is unreachable while the DATA badge shows LIVE/EMPTY in the
  same frame — two shell widgets contradicting each other on the same fact → **MAJOR**.
- **Evidence:** one screenshot containing both widgets.

---

## 03.2 TopBar — clock, badges, toggles

All rows below are read from `frontend/src/shell.tsx:31-71` unless noted. Every badge has a `title`
tooltip; hover each and record the tooltip verbatim — the tooltip *is* the honesty statement.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-005 | Wordmark + subtitle | Read top-left | `JARVIS` (l1) over `PERSONAL INTELLIGENCE · OS` (EN) / `INTELIGENȚĂ PERSONALĂ · OS` (RO) | MINOR — brand drift, see gap G1 | ❌ |
| SHL-006 | Clock ticks | Watch 3 s | `HH:MM:SS`, 24 h, zero-padded, updates every 1 s (`primitives.tsx:56-62`) | MINOR | ❌ |
| SHL-007 | Date line | Read under the clock | `DDD NN MMM YYYY`, e.g. `SAT 25 JUL 2026`; RO gives `SÂM`/`IUL` (`primitives.tsx:64-69`) | MINOR | ❌ |
| SHL-008 | AGENTS badge count | Compare to `curl -s /status \| python -m json.tool` `agents_total` | Badge `N en`; N == `agents_total` (17 on this repo — 17 `agents/*/SOUL.md`) | MAJOR if divergent | ❌ |
| SHL-009 | AGENTS running suffix | Trigger a long chat turn, watch the badge | ` · N ▶` appears only while an agent's status is `busy`/`active` (`mesh.tsx:62-65`) | MINOR | ⚠️`frontend/src/test/mesh.test.tsx` (predicate only) |
| SHL-010 | LLM `● READY` 🤖 | Load a model in LM Studio, reload | Green `● READY`, tooltip `model loaded: <exact model id>`; the id equals `/status` `loaded_model` | BLOCKER if the tooltip names a model that is not resident | ❌ |
| SHL-011 | LLM `○ NO MODEL` 🤖 | Eject the model in LM Studio, keep the server running, wait one 30 s poll | Amber `○ NO MODEL`, tooltip `LM Studio reachable but no model is loaded` | MAJOR | ❌ |
| SHL-012 | LLM `○ OFFLINE` | Quit LM Studio and Ollama entirely, wait one poll | Grey `○ OFFLINE`, tooltip `no local LLM backend reachable` | MAJOR | ❌ |
| SHL-013 | LLM `○ —` (4th state) | First paint, or force `residency_state:"unknown"` | Grey `○ —`, tooltip `LLM state unknown` (`shell.tsx:40` fallback; backend can emit `unknown` — `local_model_inventory.py:446`) | MINOR | ❌ |
| SHL-014 | DATA `● LIVE` | Any tile carrying real data | Green `● LIVE`, tooltip `live backend data` | MAJOR | ⚠️`frontend/src/test/loaders.test.ts` (`out.live` derivation) |
| SHL-015 | DATA `○ EMPTY` | Server up, nothing connected, no model | Grey `○ EMPTY`, tooltip `server up — no live data yet (connect plugins / load a model)` | **BLOCKER if it shows LIVE with nothing connected** | ⚠️ same |
| SHL-016 | DATA `◐ DEMO` | Click `○ demo` | Amber `◐ DEMO`, tooltip `demo data — seeded sample, not your live backend`; demo wins over LIVE/OFFLINE (`shell.tsx:41`) | BLOCKER if DEMO can read as LIVE | ✅`frontend/src/test/demo-mode.test.tsx` |
| SHL-017 | %-LOCAL hidden when unknown | Fresh install, no routed runs, a cloud key set (`ANTHROPIC_API_KEY`) | The `% LOCAL` badge is **absent** (`app.tsx:122-123`: null → hidden) | **BLOCKER if it shows a number** | ⚠️`frontend/src/test/cinema.test.tsx` (same rule in Cinema) |
| SHL-018 | %-LOCAL from strict-local | No cloud keys at all | Badge shows `100%` and the EGRESS badge shows `⊘ SEALED`; the two must agree (`oauth.py:200`) | MAJOR if 100% without SEALED | ✅`tests/test_trust_api.py` |
| SHL-019 | %-LOCAL from real runs | After ≥1 routed chat turn, `curl -s /api/analytics/locality` | Badge value == `local_pct`; endpoint returns `null` before the first routed run (`analytics.py:132-144`) | MAJOR | ✅`tests/test_trust_api.py`, run-history locality |
| SHL-020 | EGRESS `↗ HYBRID` 🔑 | `set ANTHROPIC_API_KEY=…`, restart, reload | `↗ HYBRID`, tooltip `hybrid — a cloud backend is reachable` | **BLOCKER if it still claims SEALED with a live cloud path** | ✅`tests/test_trust_api.py` |
| SHL-021 | MIC `⊘ MUTED` | `set JARVIS_MIC_MUTED=1`, restart, reload | `⊘ MUTED`, tooltip `microphone muted (JARVIS_MIC_MUTED)`; the composer mic button dims to 40 % opacity (`cockpit.tsx:226`) | MAJOR — a false "muted" is a privacy claim | ✅`tests/test_trust_api.py` |
| SHL-022 | MIC `● ON` | Unset the var, restart | `● ON`, tooltip `microphone live` | MAJOR | ✅ same |
| SHL-023 | demo toggle button | Click `○ demo` then `exit demo` | Label flips `○ demo` → `◐ demo`, button turns amber, URL gains `?demo=1`, banner appears; exiting removes the param with `replaceState` (no new history entry) | MAJOR | ✅`frontend/src/test/demo-mode.test.tsx` |
| SHL-024 | language toggle | Click the globe button twice | The button label shows the **current** language (`EN` → click → `RO`); rail labels, panel titles, clock date names and the composer placeholder switch together | MAJOR | ⚠️`frontend/src/test/i18n-completeness.test.ts` (key parity only) |
| SHL-025 | AMBIENT button | Click it | Ambient overlay opens (see SHL-083) | MINOR | ❌ |
| SHL-026 | ⌘K button | Click it | Palette opens focused on its input | MINOR | ⚠️`frontend/src/test/palette-tweaks.test.tsx` |
| SHL-027 | No accent control in the TopBar | Look for a theme swatch | There is **none** — accent is palette-only (`shell.tsx:271-274`); `accent` is passed to TopBar but unused | — (documentation check, not a defect) | ❌ |

#### SHL-028 — RO does not silently fall back to a key 👁
- **Surface:** every `t.*` string in the shell · **Auto:** ✅`frontend/src/test/i18n-completeness.test.ts`
- **Why it matters:** the offline gate proves EN and RO have identical key sets with no blanks
  (62 keys each), so a raw key can never render. What it does **not** prove is that a visible string is
  *in* the i18n table at all.
- **Steps:** 1) switch to RO. 2) walk cockpit → agents → chat → each of the 13 other modes. 3) look for
  any literal token like `cogempty`, `killTitle`, `undefined` or `[object Object]`.
- **Expected:** no raw keys anywhere. Localized: rail labels (`Cabină / Chat / Proiecte / Agenți /
  Încredere / Memorie / Autonomie / Construire / Observă / Interop / Finanțe / Sănătate / Cunoaștere /
  Familie / Comunicări / Admin`), column heads (`ECHIPĂ`, `SISTEM`, `COADĂ DECIZII`, `VREME`, `AZI`,
  `PULS`, `REȚEA NEURALĂ`), tabs (`CONVERSAȚIE`, `COGNIȚIE`, `Artefacte`), composer
  (`VOCE · LOCAL`, `Vorbește sau scrie o comandă…`, `TRIMITE`), ticker head (`SITUAȚIE`, `TOTUL NOMINAL`).
- **Expected-and-known:** a large set of shell strings is **hardcoded English** and stays English in RO —
  record it, do not file 20 separate bugs. At minimum: all six badge values and tooltips, `roster offline
  — server unreachable`, `queue clear ✓`, `weather not connected`, `calendar not connected`,
  `no activity yet`, every Palette entry name, `FIRST RUN` / `let's get you to a working assistant` /
  `continue to cockpit →`, the DEMO banner, the `◇ WELCOME` banner, `Not connected` / `Design preview` /
  `◐ enable DEMO`, the `⚠ No reply …` notice, and the whole CONSOLE overlay.
- **FAIL if:** a raw i18n key renders → **MAJOR**. The hardcoded-English set → **MINOR** (one finding).
- **Evidence:** RO screenshots of cockpit + one empty mode + the first-run gate.

#### SHL-029 — RO diacritics render, do not tofu 👁♿
- **Steps:** in RO read `INTELIGENȚĂ`, `Agenți`, `Încredere`, `Sănătate`, `Cunoaștere`, `în așteptare`,
  and the Saturday date abbreviation `SÂM`.
- **Expected:** `Ț ț Ă ă Î î Ș ș Â â` all render as glyphs in both the UI font (Space Grotesk) and the
  mono font (JetBrains Mono). Both are self-hosted with a `unicode-range` that includes U+0000-00FF and
  U+0131/0152-0153 (`styles.css:6-22`) — `ș`/`ț` (U+0219/U+021B) are **outside** that range and fall back
  to the system font.
- **FAIL if:** any character shows as `□`/`?` → **MAJOR**. A visible font mismatch mid-word (fallback
  kicking in for `ș`/`ț`) → **COSMETIC**, but record it: `Auto:` ✅`frontend/src/test/self-hosted-fonts.test.ts`
  only proves the fonts are local, not that they cover Romanian.
- **Evidence:** zoomed screenshot of `Sănătate` and `în așteptare`.

---

## 03.3 Ticker

#### SHL-030 — the ticker header must not claim a state it cannot know 👁
- **Surface:** `shell.tsx:73-97`; feed = `GET /ticker` (**user**) via `loaders.ts:132-144` · **Auto:** ❌
- **Why it matters:** golden rule. The header is hardcoded: a pulsing **red** dot, the red label
  `SITUATION`, and the fixed text `ALL NOMINAL` (`t.allnominal`) — with **no dependence on `items`**.
- **Steps:** 1) live install, no plugins: read the ticker header. 2) generate a real alert-severity item
  (`curl -s /ticker` and confirm at least one row has `pri` mapping to `hi` or `warn` —
  `loaders.ts:140`). 3) read the header again while that item scrolls past.
- **Expected:** with zero items the header shows an honest "no signals yet"; with a `hi`/`warn` item on
  screen the header does **not** say ALL NOMINAL.
- **Known-current behaviour:** the header says `ALL NOMINAL` in **both** cases. Run 1 recorded exactly
  this shape (a real GECKO finance alert scrolling while other surfaces claimed all-clear).
- **FAIL if:** `ALL NOMINAL` is displayed with a `hi`-class item visible → **MAJOR** (green-looking
  screen over a real alert). With zero items → **MINOR**.
- **Evidence:** screenshot with the alert item and the header in the same frame + `curl -s /ticker` output.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-031 | Item shape | Read one scrolling item | `AGENT` (accent) · *verb* (italic) · text · a 34 px progress bar filled to `bar`% · `│` separator (`styles.css:118-127`) | MINOR | ❌ |
| SHL-032 | Severity colour | Compare to `curl -s /ticker` | `pri:high`→ agent name red, `warn`→ amber, `ok`→ green, else accent (`loaders.ts:140`, `styles.css:122`) | MAJOR if a `high` row renders neutral | ❌ |
| SHL-033 | Duplicate items are cosmetic | Count visible items vs `/ticker` length | The track renders `[...items, ...items]` for a seamless marquee (`shell.tsx:75`) — you will see each item **twice**. Not a bug; do not file it | — | ❌ |
| SHL-034 | Hidden in chat mode | Press `9` (or click Chat) | The whole ticker bar disappears (`app.tsx:396` `hidden={mode==='chat'}`); it returns on any other mode | MINOR | ❌ |
| SHL-035 | Calm motion slows it | Palette → `Motion · Calm`, watch | Scroll duration doubles 58 s → 115 s (`styles.css:117`) | COSMETIC | ⚠️`frontend/src/test/palette-tweaks.test.tsx` |
| SHL-036 | Demo ticker is watermarked | Enable demo | 8 seeded items appear (PEPPER/ULTRON/STARK/VISION/GECKO/FRIDAY/HEPHAESTUS/ULTRON — `data.ts:102-111`) **and** the DATA badge reads `◐ DEMO` | BLOCKER if seeded items show with DATA `● LIVE` | ✅`frontend/src/test/app-demo-exit.test.tsx` |

---

## 03.4 Rail & mode navigation

The rail is built from `MODES` (`shell.tsx:9-29`): **16 modes + 3 separators = 19 array entries**.
Separators sit after `memory`, after `interop`, and after `family`. No entry sets `locked:true` on this
revision — see gap G2. The `Tabs` component exists but is unreachable: `ia` is hardcoded to `'rail'`
(`app.tsx:58`) — see gap G3.

For each row: click the rail button, then re-reach the same mode from the Palette, then (where a hotkey
exists) from the keyboard. All three must land on the same view.

| ID | Mode | Rail label EN / RO | Hotkey | Reached by palette entry | Expect (live, nothing connected) | Fail |
|----|------|--------------------|--------|--------------------------|----------------------------------|------|
| SHL-037 | `cockpit` | Cockpit / Cabină | `1` | `Cockpit` | 3-column cockpit: roster, mesh+chat, context column | MAJOR |
| SHL-038 | `chat` | Chat / Chat | `9` | `Chat · focus` | Full-width focus chat, ticker hidden, head `DIRECT LINE · NERVA` | MAJOR |
| SHL-039 | `projects` | Projects / Proiecte | — | `Projects · rooms & missions` | Renders **always** (no live gate — `app.tsx:584`); Rooms/Missions/Activity panels each with their own honest empty state | MAJOR |
| SHL-040 | `agents` | Agents / Agenți | `2` | `Agents` | Agents grid + the right context column | MAJOR |
| SHL-041 | `trust` | Trust / Încredere | `3` | `Trust Center` | `ModeEmpty`: `TRUST & GOVERNANCE` / **Not connected** / "No live data from the backend for this view yet…" / `◐ enable DEMO` | MAJOR |
| SHL-042 | `memory` | Memory / Memorie | `4` | `Memory & Knowledge` | Live once `/memory/stats` answers (open tier) — the chip should read LIVE | MAJOR |
| SHL-043 | `autonomy` | Autonomy / Autonomie | `5` | `Autonomy` | `ModeEmpty` "Not connected" unless `/autonomy/brief` or `/autonomy/observer` answered (**admin** tier → expect empty without an admin token) | MAJOR |
| SHL-044 | `build` | Build / Construire | `6` | `Build` | `ModeEmpty` / live from `/api/workflows` + `/sandbox/status` | MAJOR |
| SHL-045 | `observe` | Observe / Observă | `7` | `Observe` | `ModeEmpty` / live from `/bench/stats`, `/api/quality`, `/api/resilience`, `/api/traces` | MAJOR |
| SHL-046 | `interop` | Interop / Interop | `8` | `Interop` | `ModeEmpty` / live from `/api/a2a/peers`, `/api/admin/mcp`, `/api/webhooks` | MAJOR |
| SHL-047 | `finance` | Finance / Finanțe | — | `Finance` | `ModeEmpty` unless a watchlist or payment exists; **never** seeded balances | BLOCKER if seeded €-figures show outside demo |
| SHL-048 | `health` | Health / Sănătate | — | `Health` | `ModeEmpty` unless the `apple-health` plugin is configured; when live, rings/metrics are **emptied**, not seeded (`live.ts:412-415`) | BLOCKER if seeded 7 h 12 m sleep shows |
| SHL-049 | `knowledge` | Knowledge / Cunoaștere | — | `Knowledge` | `ModeEmpty` unless `/api/kg/entities` returns rows **and** `websearch` is configured (`live.ts:407-410`) | MAJOR |
| SHL-050 | `family` | Family / Familie | — | `Family · local` | `ModeEmpty` unless `whatsapp-bridge` is configured; when live, members/events/reminders are **emptied** (`live.ts:416-419`) | BLOCKER if seeded "Cosmina / Max / Mama" shows outside demo |
| SHL-051 | `comms` | Comms / Comunicări | `0` | `Comms · inbox` | `ModeEmpty` / live from `/api/rooms` + `/api/channels/inbox` | MAJOR |
| SHL-052 | `admin` | Admin / Admin | — | `Admin · settings` | Live from `/plugins` (open tier) — expect LIVE with the real registry | MAJOR |

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-053 | Active state | Click each rail button | Exactly one `.rail-btn.active`: accent text, faint accent fill, and a 2 px accent tick bar to its left (`styles.css:141-142`) | MINOR | ❌ |
| SHL-054 | Tooltips | Hover each button | `title` == the localized label (`shell.tsx:105`) | COSMETIC | ❌ |
| SHL-055 | Separators | Count the hairlines | 3 (`.rail-sep`, 22 × 1 px) grouping 6 / 4 / 4 / 2 buttons | COSMETIC | ❌ |
| SHL-056 | "Mode wiring in progress" must never appear | Visit all 16 modes | `ModeStub` (`app.tsx:23-36`) is **unreachable** — all 16 ids are handled | MAJOR if any mode shows `P0 · shell + cockpit live · build green` | ❌ |
| SHL-057 | Hotkeys ignored while typing | Focus the composer, type `1234567890 a m` | The text lands in the input; the mode does **not** change and no overlay opens (`app.tsx:179-180` guards `input`/`textarea`) | MAJOR | ❌ |
| SHL-058 | Hotkeys with a panel focused | Tab until a `.panel-body` (they carry `tabIndex=0`) has focus, press `3` | Mode switches to Trust — panel bodies are not text inputs, so this is expected | — | ❌ |
| SHL-059 | Pageview beacon per mode | DevTools → Network, filter `analytics/event`, switch 4 modes | 1 beacon on load + 1 per switch, body `{name:"pageview", path:"/<mode>", session_id}` to `POST /api/analytics/event` (open tier); the mount effect skips its first run to avoid a duplicate (`app.tsx:130-135`) | MINOR | ✅`frontend/src/analytics.test.ts` |
| SHL-060 | No mode is in the URL | Switch to `admin`, copy the URL, open it in a new tab | The URL never encodes the mode; the new tab lands on `cockpit`. Known limitation — record it, do not file twice | — | ❌ |

---

## 03.5 Command palette

Composition (`shell.tsx:250-288`): **31 entries** in 3 groups — *Go to* 17 (the 16 modes + `Ambient mode`),
*Theme* 5 (4 accents + language toggle), *Display* 9 (2 looks, 3 densities, 2 motions, scanline, dot grid).

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-061 | Open/close by keyboard | `Ctrl+K`, then `Ctrl+K` again | Opens, then **closes** (it is a toggle — `app.tsx:177`); Chrome's own Ctrl+K is suppressed by `preventDefault` | MAJOR | ❌ |
| SHL-062 | Autofocus | Open it and type immediately | Characters land in the input (focus is set 30 ms after open — `shell.tsx:246`) | MAJOR | ❌ |
| SHL-063 | Query resets on open | Type `fin`, Esc, reopen | The input is empty and selection is back on row 0 | MINOR | ❌ |
| SHL-064 | Match is substring, **not** fuzzy | Type `cock`, then `ckpt` | `cock` → `Cockpit`. `ckpt` → `no matches` (`shell.tsx:290` uses `String.includes`) | — (documentation: fuzzy is not implemented, gap G4) | ❌ |
| SHL-065 | Case-insensitive | Type `AMBER` | `Accent · Amber` matches | MINOR | ❌ |
| SHL-066 | Empty result state | Type `zzzz` | The list shows exactly `no matches`; footer still shows the 3 kbd hints | MINOR | ❌ |
| SHL-067 | Arrow navigation | Open, press ↓ ×5, ↑ ×2 | Selection moves one row per press, clamps at both ends (`shell.tsx:296-297`) | MAJOR | ❌ |
| SHL-068 | Enter runs the selection | Type `heal`, Enter | Palette closes **and** the mode becomes Health | MAJOR | ❌ |
| SHL-069 | Escape closes | Open, press Esc | Closes | MAJOR | ❌ |
| SHL-070 | Scrim click closes | Open, click the blurred backdrop | Closes; clicking inside the panel does **not** (`shell.tsx:303-304`) | MINOR | ❌ |
| SHL-071 | Mouse hover moves selection | Hover row 4 then press Enter | Row 4 runs (`onMouseEnter` sets `sel`) | MINOR | ❌ |
| SHL-072 | Hotkey hints | Read the *Go to* group | Hints `1,9,,2,3,4,5,6,7,8` then blanks for finance/health/knowledge/family/admin/ambient — matching the real hotkey map (`app.tsx:181`) | MINOR if a hint names a key that does nothing | ❌ |
| SHL-073 | All 4 accents apply | Run each `Accent ·` entry | `data-accent` on `.hud-root` becomes cyan/amber/green/violet; the accent colour changes across rail, clock, bubbles; survives reload (`hud.accent`) | MINOR | ⚠️`frontend/src/test/palette-tweaks.test.tsx` (display axes only) |
| SHL-074 | Language entry | Run `Toggle language EN / RO` | Same effect as the TopBar globe | MINOR | ❌ |
| SHL-075 | Look Obsidian/Graphite ✓ marks | Run `Look · Graphite`, reopen | The active option carries a trailing `✓`; corner brackets (`.bk`) disappear and bubbles lose their clipped corners in Graphite (`styles.css:59,64`) | MINOR | ✅`palette-tweaks.test.tsx` |
| SHL-076 | Density 3-way | Run Compact / Normal / Comfy | `--pad`/`--gap`/base font change (11/9/13 px · 16/14/14 · 22/20/14.5 — `styles.css:67-68`) | MINOR | ✅ same |
| SHL-077 | Motion 2-way | Run `Motion · Calm` | `.ambient-anim` animations stop and mesh packets (`.pkt`) disappear (`styles.css:71-72`) | MINOR | ✅ same |
| SHL-078 | Scanline toggle | Run `Scanline · Off` | The moving scan bar and scan texture go to opacity 0 (`styles.css:80-82`); the label flips to `Scanline · On` | COSMETIC | ✅ same |
| SHL-079 | Dot grid toggle | Run `Dot grid · On` | The dot-grid texture layer becomes visible (`styles.css:78`) | COSMETIC | ✅ same |
| SHL-080 | Ambient entry | Run `Ambient mode` | The palette closes **first**, then Ambient opens (`app.tsx:459`) — no stacked overlays | MINOR | ❌ |
| SHL-081 | Missing entries | Search `console`, `cinema`, `demo`, `reload` | All four return `no matches` — the Console, Cinema, and the demo toggle have **no** palette entry (gap G5) | MINOR | ❌ |
| SHL-082 | Keyboard-only end to end | From a fresh load, without touching the mouse: `Ctrl+K` → `fam` → Enter → `Ctrl+K` → `cock` → Enter | You reach Family then Cockpit with zero clicks | MAJOR | ❌ |

---

## 03.6 Overlays — Ambient, Cinema, Console, Provenance, Dossier

#### SHL-083 — Ambient overlay 👁
- **Surface:** `shell.tsx:326-354`, `.ambient` z-index 40 (`styles.css:408`) · **Auto:** ❌
- **Steps:** 1) press `a`. 2) read every element. 3) press Esc. 4) reopen, click anywhere, confirm exit.
- **Expected:** big `HH:MM`, the localized date line, an EKG path, then a stat strip:
  `<non-idle>/<total>` over `AGENTS`, `<n>%` over `% LOCAL` **only when `localPct != null`**,
  `<n>` over `pending decisions`. With pending decisions, up to 3 lines appear with the agent name in
  accent and the body **stripped of markup** (`stripTags`, `shell.tsx:355`). Footer:
  `press ESC or click to wake`.
- **Also acceptable (honest degradation):** `0/0 AGENTS`, no `% LOCAL` block, `0 pending decisions`.
- **FAIL if:** raw `**bold**` markers or `<b>` tags leak into an ambient line → **MINOR**; a `% LOCAL`
  figure appears while the TopBar badge is hidden → **MAJOR** (contradiction).
- **Evidence:** screenshot; if pending items are present, redact family/finance content per the local-only rule.

#### SHL-084 — the CONSOLE button floats over Ambient 👁
- **Surface:** `app.tsx:456-457` (inline `zIndex:50`) vs `.ambient` z-index 40
- **Steps:** 1) press `a`. 2) look at the bottom-right corner. 3) click `▦ CONSOLE`. 4) press Esc once.
- **Expected:** Ambient is a clean wall display — no HUD chrome on top of it.
- **Known-current behaviour:** the fixed `▦ CONSOLE` button paints **on top of** the ambient screen and
  is clickable; clicking it opens the Console (`.pal-scrim` z 80) over Ambient, and a single Esc closes
  **both** (each registered its own `keydown` listener).
- **FAIL if:** reproduced → **MINOR (cosmetic)**; if the double-close leaves the app in a state where
  the cockpit is unreachable → **MAJOR**.
- **Evidence:** screenshot of the ambient screen with the button visible.

#### SHL-085 — Cinema mode (full-bleed mesh) 👁
- **Surface:** `CinemaMesh`, `shell.tsx:362-405` · **Auto:** ✅`frontend/src/test/cinema.test.tsx`
- **Steps:** 1) press `m`. 2) read the top mark, the rotating tag (changes every 4.2 s), the bottom feed
  line and the stat row. 3) press Esc; reopen and click the `Esc` button top-right.
- **Expected (live):** mark `JARVIS` + reactor; tags cycle exactly `Governed operator view` →
  `Current evidence only` → one of `Trust evidence unavailable` / `Cloud lane reported by trust status`
  / `Trust status connected` (the third depends on `sources.trust` and the trust booleans);
  feed line `the Cabinet is working…` only when an agent is executing or a task is running, else
  `no live activity`; stats `<n> agents live` and `<n>% on-device` **omitted entirely** when `localPct`
  is null.
- **Expected (demo):** every tag starts with `DEMO ·`.
- **FAIL if:** any tag claims `87% on-device`, `0 cloud leaks`, `always-on`, or `Private. Provable` —
  the prototype's fabricated copy — → **BLOCKER**. `agents live` disagreeing with the TopBar
  `· N ▶` count → **MAJOR**.
- **Evidence:** three screenshots across one 12.6 s tag cycle.

#### SHL-086 — Console overlay open/close 👁
- **Surface:** `ConsoleOverlay`, `gap.tsx:2856-2881` · **Auto:** ⚠️`frontend/src/test/gap-panels.test.tsx` (individual panels)
- **Steps:** 1) press `` ` `` → opens. 2) press `` ` `` again → **closes** (toggle, `app.tsx:185`).
  3) reopen via the fixed `▦ CONSOLE` button. 4) press Esc → closes. 5) reopen, click the blurred scrim →
  closes. 6) reopen, click the `esc ✕` button → closes. 7) reopen and click *inside* a panel → stays open.
- **Expected:** header `CONSOLE` + `net-new capability surfaces (P4c) · live + mock-tolerant` + `esc ✕`;
  **9** section headings in this order: `START`, `HOME`, `MEMORY`, `TRUST`, `INTEROP`, `OBSERVE`,
  `BUILD`, `AUTONOMY & AGENTS`, `ADMIN` (`gap.tsx:2844-2854`), laid out in 3 columns of ~320 px,
  totalling **67** panel cards.
- **FAIL if:** any of the four close paths fails → **MAJOR**; a section renders zero cards → **MAJOR**
  (grade the panels themselves in §05, not here).
- **Evidence:** one screenshot per section heading (scrolled), plus the DevTools Console cleared before
  opening — **any uncaught exception while mounting 67 panels is a BLOCKER for this section**.

#### SHL-087 — Provenance modal 👁🤖
- **Surface:** `ProvModal`, `app.tsx:530-545`; chip in `cockpit.tsx:57-62`
- **Steps:** 1) send a real turn. 2) after the reply lands, read the chip under the bubble.
  3) click it. 4) close by clicking the scrim.
- **Expected:** chip reads `<n> agents · <n> plugins · local|cloud|locality — · conf <x>`. The modal shows
  `PROVENANCE`, `conf <x>` in green, `AGENTS CONSULTED` (glyph + id per agent), `PLUGIN READS`, and one of
  `100% on-device · no cloud egress` / `cloud-assisted` / **`locality not reported`**. Values come from
  `GET /api/cognition` (**user**), never from a client-side guess (`app.tsx:274-283`).
- **Also acceptable:** `0 plugins`, empty `PLUGIN READS`, `locality —`, `conf 0`.
- **FAIL if:** the chip claims `local` while `/api/cognition` `decision.local` is absent or false → **BLOCKER**;
  it lists a plugin that `curl -s /api/cognition` does not report → **BLOCKER** (that is the run-1
  fabrication shape one level down).
- **Evidence:** screenshot of the chip + the modal + `curl -s http://127.0.0.1:8080/api/cognition` output.

#### SHL-088 — low confidence is invisible (run-1 root-cause signal) 👁🤖
- **Why it matters:** run 1 found the fabricated calendar reply carried `conf 0.5` internally, against
  `conf 1` for a plain question and `conf 0` for an honest refusal — "nothing in the UI surfaces that
  low score as a caveat."
- **Steps:** with no calendar connected ask (RO) **„Ce am pe agenda azi?"** and (EN) **"What's on my
  plate today?"**. Read the prov chip's `conf` value on the reply, then compare the reply against the
  **TODAY** widget in the same screenshot.
- **Expected:** either the reply is honest ("no calendar connected") **or**, if it narrates a calendar,
  the shell visibly marks the answer as low-confidence/ungrounded.
- **FAIL if:** a narrated calendar appears with `conf ≤ 0.6` and **no** visual caveat, one widget away
  from `calendar not connected` → **BLOCKER** (this is §R R1; report it there, and note here that the
  shell offers no low-confidence affordance → gap G6).
- **Evidence:** one screenshot containing the reply, its conf chip, and the TODAY widget.

#### SHL-089 — Dossier drawer 👁
- **Surface:** `Dossier`, `modes.tsx:44-63`
- **Steps:** 1) in the cockpit roster click each agent row in turn. 2) for each, confirm a right-side
  drawer slides in. 3) close via the scrim.
- **Expected:** every agent in the roster opens a drawer with its glyph, name/role, SOUL text (live from
  `GET /api/agents/{agent_id}/soul`, **open** tier) and run history.
- **Known-current behaviour:** clicking **howard** or **argus** opens **nothing** — `Dossier` looks the id
  up in the seeded 15-agent table (`V2.AGENTS`, `data.ts:31-47`) and `return null` when absent, while the
  live roster has 17. `setActiveId` still fires, so the chat target silently changes with no feedback.
- **FAIL if:** reproduced → **MAJOR** (2 of 17 roster rows are dead, and a click silently retargets chat).
- **Evidence:** screen recording of the howard click + the DevTools React state or a follow-up chat turn
  showing the retarget.

---

## 03.7 RosterColumn (left) and ContextColumn (right)

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-090 | Roster header | Read it | `ROSTER` / `ECHIPĂ` + `<n> enabled` where n == `agents.length` == `/status.agents_total` | MAJOR | ❌ |
| SHL-091 | Tier grouping | Read the group headers | Only non-empty tiers render, in order `CNS` Central Nervous System, `BIZ` Business, `SEC` Systems & Eng, `FND` Foundation (`data.ts:24-29`) | MAJOR | ❌ |
| SHL-092 | Backend tiers match the UI's four | `curl -s /api/agents \| findstr tier` | Every row's `tier` is one of CNS/BIZ/SEC/FND (`agents/web.py:650-667`; unknown ids default to `FND`) | **MAJOR** if any agent is in the count but in no group (invisible row) | ❌ |
| SHL-093 | `howard` has no metadata | Find howard in the roster | It appears under `FND` with an **empty role line** and an **invisible glyph** (`_AGENT_META` in `agents/web.py:650-667` has 16 entries, no howard; `V2.GLYPHS` has 15, no howard/argus) | MINOR | ❌ |
| SHL-094 | Status dot semantics | Compare each dot to `curl -s /api/agents` | `active`→ green-ish `active`, `busy`→ `busy`, `err`→ `err`, everything else → `idle` (`primitives.tsx:53`). The backend emits only `ready`/`idle` (`agents/web.py:677`), so every heartbeat agent shows the **idle** dot | MINOR — record it, gap G7 | ❌ |
| SHL-095 | Row click | Click a row | Row gains `.active`; the dossier opens; the chat target (`activeId`) becomes that agent | MAJOR | ❌ |
| SHL-096 | SYSTEM meters | Compare to `curl -s /status \| python -m json.tool` | `RAM` == round(ram_used/ram_total·100), `VRAM` likewise, `GPU` == round(gpu_load). With no NVIDIA GPU, `/status` reports `gpu:"none"` and 0s → all three meters read `0%` | **BLOCKER if VRAM/GPU show plausible non-zero values with no GPU present** | ⚠️`tests/test_*` cover `_sys_info` honesty |
| SHL-097 | BACKEND row | Read it, then `curl -s /status` | The row is `<sys.backend> · <model>`. `_sys_info` never sets a real backend, so expect literally `unknown · <model>` while `/status.llm_backend` knows the truth (e.g. `lm-studio+ollama-howard`) | MINOR — record it, gap G8 | ❌ |
| SHL-098 | BACKEND must never say "LM Studio" by default | Read it with LM Studio **not** running | `shell.tsx:231` falls back to the literal string `'LM Studio'` when `sys.backend` is empty | **MAJOR if the row names LM Studio while it is not the backend** | ❌ |
| SHL-099 | Model label states | Cycle model loaded → ejected → backend down | `<model id>` (accent) / `no model loaded` (amber) / `backend offline` (amber) / `—` (grey) (`shell.tsx:225-226`) | MAJOR | ❌ |
| SHL-100 | LATENCY p50 | Read it after several turns | `sys.latency` is never populated → the row shows `—`. An honest dash is a PASS | **BLOCKER if a plausible latency number appears** (it cannot come from `/status`) | ❌ |
| SHL-101 | DECISION QUEUE empty state | Live, nothing pending | Header `DECISION QUEUE` + count `0`, body `queue clear ✓` | MINOR | ❌ |
| SHL-102 | DECISION QUEUE vs the real inbox | Open the Console → `DECISION INBOX` panel and compare | **The cockpit queue is demo-only**: `setDecisions` is only ever fed `V2.DECISIONS` under `demo` (`app.tsx:98,146`) — no loader writes it. So the cockpit says `queue clear ✓` even with N items pending in the real inbox | **MAJOR** — the cockpit asserts "clear" over a non-empty governed queue; gap G10 | ❌ |
| SHL-103 | Decision card buttons are inert | In demo, click **Reschedule** on the PEPPER card, then **Leave it** on the next | Both merely remove the card client-side; both buttons call the same `onDecision(d._id)` (`shell.tsx:141`, `app.tsx:372`) — no API call in the Network tab | MAJOR in demo (governance theatre); would be **BLOCKER** if these cards ever carried live items | ❌ |
| SHL-104 | Card body markup | Read a demo card | `**bold**` renders as accent-coloured bold via `renderRich`; no raw `**` visible | COSMETIC | ❌ |
| SHL-105 | WEATHER empty state | Live, no weather plugin | Header `WEATHER` with no city chip, body `weather not connected` | **BLOCKER if a temperature appears with nothing connected** | ⚠️`frontend/src/test/loaders.test.ts` |
| SHL-106 | WEATHER live shape 🔑 | With a weather source configured | Temp, description, `feels N°`, `WIND`, `HUMIDITY`, and a 4-cell forecast strip; city chip in the header. `loaders.ts:115` only accepts it when `temp` is non-empty and not `—` | MAJOR | ⚠️ same |
| SHL-107 | TODAY empty state | Live, no calendar OAuth | Header `TODAY` / `AZI`, count `0`, body `calendar not connected` — **this widget is the cross-check witness for §R R1** | **BLOCKER if events appear with no calendar connected** | ⚠️ same |
| SHL-108 | HEARTBEAT empty state | Fresh boot | Header `HEARTBEAT` / `PULS`, body `no activity yet` | MINOR | ⚠️ same |
| SHL-109 | HEARTBEAT severity dots | After the observer has run | Each row: a severity dot (`info`/`ok`/`warn`/`alert`), agent name, time, text — mapped from `/dashboard` `notifications` (`loaders.ts:230-236`) | MINOR | ⚠️ same |
| SHL-110 | Context column is scroll-independent | Scroll the right column | Only `.col.scrollcol` scrolls; the cockpit centre does not move (`styles.css:167`) | COSMETIC | ❌ |
| SHL-111 | Context column in Agents mode | Press `2` | The same 4-panel context column renders beside the agents grid (`app.tsx:434`) | MINOR | ❌ |

---

## 03.8 Chat pane — composer, streaming, rehydration, rendering

#### SHL-112 — the three centre tabs 👁
- **Surface:** `app.tsx:416-425` · **Auto:** ⚠️`frontend/src/test/artifacts.test.tsx`
- **Steps:** click `CONVERSATION`, `COGNITION`, then the artifacts tab.
- **Expected:** labels `CONVERSATION`/`CONVERSAȚIE`, `COGNITION`/`COGNIȚIE`, `Artifacts`/`Artefacte`
  (`artifacts.tsx:56`). A pip dot appears on CONVERSATION while a turn is in flight, and on COGNITION
  once a trace exists and no turn is in flight. Switching tabs never loses the transcript.
- **Expected (cognition empty):** brain icon + `Send a message to watch Jarvis think —` +
  `classify → route → gather → synthesize`.
- **FAIL if:** a tab switch clears messages → **MAJOR**.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-113 | Composer chrome | Read the input bar | `▸` prefix, channel chip `VOICE · LOCAL`/`VOCE · LOCAL`, placeholder `Speak or type a command…`, mic button, `⚙` button, `TRANSMIT`/`TRIMITE` | MINOR | ❌ |
| SHL-114 | Enter sends | Type text, press Enter | Sends and clears the box (`cockpit.tsx:223`) | MAJOR | ❌ |
| SHL-115 | TRANSMIT sends | Type text, click TRANSMIT | Same | MAJOR | ❌ |
| SHL-116 | Whitespace is rejected client-side | Type three spaces, press Enter | Nothing is sent, no network request (`cockpit.tsx:180` trims); the backend would 422 anyway (`agents/web.py:696-704`) | MINOR | ✅`tests/test_web_chat*.py` |
| SHL-117 | **Shift+Enter does not newline** | Type `a`, Shift+Enter, `b` | The message sends on the first Enter — the composer is a single-line `<input>`, not a textarea (`cockpit.tsx:222`). Multi-line composing is **not supported** | MINOR — record it, gap G9 | ❌ |
| SHL-118 | 4096-char cap 🤖 | Paste 5000 `x`, send | The backend rejects with 422 (`message` max_length 4096); the HUD's `postStream` throws and the shell appends the honest `⚠ No reply — the model backend is unreachable or no model is loaded…` notice | MAJOR if the browser hangs or the notice is absent | ✅`tests/test_web_chat*.py` |
| SHL-119 | Streaming renders token-by-token 🤖👁 | Ask for ~200 words | The agent bubble appears at the `start` event and grows continuously; `postStream` parses `data:` SSE frames (`api/client.ts:76-96`) | MAJOR if the reply appears only at the end | ✅`frontend/src/test/chatStreamAbort.test.ts` (transport) |
| SHL-120 | Agent attribution 🤖 | Send `Stark, KPI summary` | The bubble's `mtag` shows the agent name UPPERCASE from the stream's `evt.agent` (`app.tsx:265,271`), the timestamp, and the prov chip after the cognition snapshot lands | MAJOR if the tag names an agent that `/api/cognition` did not select | ⚠️ |
| SHL-121 | Stop generating 🤖👁 | Start a long reply, click `■ stop` | Streaming halts; the **partial text stays**; no `⚠` error notice; `aria-label="Stop generating"` (`cockpit.tsx:71-74`); the abort is a clean outcome (`app.tsx:289`) | MAJOR | ✅`frontend/src/test/chatStreamAbort.test.ts` |
| SHL-122 | Stop leaves nothing persisted 🤖 | After SHL-121, `curl -s /memory` | The aborted partial is **not** in `turns` (server disconnect/cancel path) | MAJOR | ✅`tests/test_*chat_stream*` |
| SHL-123 | Double-submit guard | Press Enter twice within ~200 ms | Exactly one turn runs; the second submit is dropped while `thinking` is non-null (`app.tsx:251`) | MAJOR if two streams interleave into one bubble | ❌ |
| SHL-124 | Honest failure, never a fabricated reply | Quit LM Studio, send a message | The bubble is attributed to `SYSTEM` and reads exactly `⚠ No reply — the model backend is unreachable or no model is loaded. Load a model in LM Studio, or enable ◐ DEMO to preview the interface.` (`app.tsx:294`) | **BLOCKER if a plausible reply appears with no backend** | ❌ |
| SHL-125 | The staged mock is demo-only | Repeat SHL-124 with `?demo=1` | You get the seeded staged mock (a 3.3 s scripted timeline, `app.tsx:219-239`) — acceptable **only** because the DEMO banner and `◐ DEMO` badge are on screen | **BLOCKER if the mock ever fires outside demo** | ✅`frontend/src/test/app-demo-exit.test.tsx` |
| SHL-126 | Per-message TTS button 🔑👁 | Click `🔊` on a reply | Becomes `◼` while speaking (`POST /tts`, **user** tier); on failure it turns amber with title `TTS unavailable` and does **not** claim to have played | MINOR | ⚠️`frontend/src/test/ttsStream.test.ts` |
| SHL-127 | Save-to-artifacts appears only when safe | Watch a streaming reply, then after it completes | `⬒ save` is absent while the last message is streaming and absent on `system` messages; present on completed agent replies in the cockpit only — ChatMode does not pass `onArtifactSaved` (`cockpit.tsx:34`, `app.tsx:422,438`) | MINOR | ✅`frontend/src/test/artifacts.test.tsx` |
| SHL-128 | Bold rendering | Send a prompt that yields `**bold**` | Renders as accent-coloured bold; no stray `**` (`cockpit.tsx:81-85`) | COSMETIC | ❌ |

#### SHL-129 — transcript survives a reload (regression R6) 👁🤖
- **Surface:** `app.tsx:155-172` → `GET /memory` (**user**) · **Auto:** ❌ (the fix is vitest-green for
  the loader path only; never browser-verified)
- **Why it matters:** run 1's clean, reproducible "conversation history does not survive a page reload".
- **Steps:** 1) send `Persistence check 4471: reply with the number only`. 2) confirm the reply.
  3) `curl -s http://127.0.0.1:8080/memory | python -m json.tool` and confirm both turns are in `turns`.
  4) hard-refresh (Ctrl+Shift+R). 5) read the conversation pane.
- **Expected:** both the user turn and the reply are rendered again after reload, oldest first, each with
  a `HH:MM` timestamp; agent bubbles attributed from `agent_id`. Rehydration runs once
  (`_rehydrated` ref) and **never clobbers** a conversation you started before it resolved.
- **Also acceptable (honest degradation):** a **brand-new** session shows an empty pane; `/memory`
  returning `{"error":"not initialized"}` (503) leaves the pane empty with no error banner.
- **FAIL if:** the pane is empty while `/memory` returned turns → **MAJOR** (R6 regressed).
- **Evidence:** `curl` output + post-reload screenshot.

#### SHL-130 — rehydration is capped at 20 turns
- **Steps:** send 12 short turns (24 messages), then hard-refresh.
- **Expected:** at most **20** entries return — `GET /memory` calls `get_history(..., last_n=20)`
  (`agents/core/routers/memory_hud.py:35`). Older turns are dropped from the *rendered* transcript
  while remaining in server memory.
- **FAIL if:** the tester reports this as data loss without knowing the cap — record the cap in the run
  notes. A silent truncation with **no** "earlier turns not shown" affordance → **MINOR**, gap G23.

#### SHL-131 — rehydration must not fight demo mode
- **Steps:** 1) load `/v2/?demo=1`. 2) confirm the two seeded messages (`Morning Jarvis — what does my
  day look like?` + the Jarvis reply, `data.ts:95-99`). 3) hard-refresh.
- **Expected:** the seeded corpus is shown; **no** `/memory` request appears in the Network tab
  (`app.tsx:157` returns early when `demo`).
- **FAIL if:** real server turns are mixed into the demo transcript → **BLOCKER** (provenance mixing).

#### SHL-132 — scroll behaviour during a long stream 👁🤖
- **Steps:** 1) ask for ~800 words. 2) while it streams, scroll **up** to re-read an earlier turn.
- **Expected:** you can read history while tokens arrive; the view sticks to the bottom only when you
  were already at the bottom.
- **Known-current behaviour:** `cockpit.tsx:29` sets `scrollTop = scrollHeight` on **every** `messages`
  change unconditionally, so each token yanks you back to the bottom.
- **FAIL if:** reproduced → **MAJOR** (a long reply is unreadable until it finishes).
- **Evidence:** screen recording.

#### SHL-133 — multi-line and code-block replies 👁🤖
- **Steps:** ask (EN) "Reply with a numbered list of 5 items, one per line." then "Reply with a fenced
  python code block that prints hello."
- **Expected:** the list renders on 5 visual lines; the code block renders monospaced and does not
  overflow the bubble.
- **Known-current behaviour:** `.msg .bubble` (`styles.css:230`) sets **no** `white-space` and no
  `overflow-wrap`, and `renderRich` only handles `**bold**` — so newlines **collapse into one paragraph**
  and fenced code renders as inline prose including the literal backticks.
- **FAIL if:** reproduced → **MAJOR** (readability); if a long unbroken token (paste a 200-char hash and
  ask the model to echo it) breaks the bubble out of the panel → **MAJOR** layout defect.
- **Evidence:** two screenshots.

#### SHL-134 — RO diacritics round-trip through chat 👁🤖
- **Steps:** send exactly `Rezumă în română: „Încărcarea bateriei a scăzut cu 5% după actualizare."`
  and then the EN twin `Summarize in English: "Battery charge dropped 5% after the update."`
- **Expected:** the user bubble shows the diacritics and the curly RO quotes `„…"` unmangled;
  `curl -s /memory` shows the same bytes; the RO reply's diacritics render (subject to SHL-029's font
  fallback).
- **FAIL if:** mojibake (`Ã®`, `Ã¢`) anywhere in bubble or `/memory` → **MAJOR** (encoding bug).

#### SHL-135 — focus chat mode parity 👁
- **Surface:** `ChatMode`, `modes3.tsx:11-26`
- **Steps:** press `9`, read the head, send a turn, click a prov chip.
- **Expected:** head `DIRECT LINE · NERVA` + `distraction-free · ⌘K for everything else` +
  a green dot with `local`; ticker hidden; same transcript as the cockpit (shared `messages` state);
  prov chip and `■ stop` work. **No** `⬒ save` button here (by design).
- **FAIL if:** the chat-mode head's `local` claim persists while the prov chip says `cloud` → **MAJOR**
  (hardcoded `local` label, gap G11); if the transcript differs from the cockpit's → **MAJOR**.

---

## 03.9 First-run gate & onboarding

#### SHL-136 — the FIRST RUN gate on genuinely clean storage 👁
- **Surface:** `FirstRunGate` + `CommandCenterPanel` (`gap.tsx:2670-2842`) → `GET /api/onboarding/command-center` (**user**) · **Auto:** ✅`frontend/src/test/first-run-gate.test.tsx`, ✅`frontend/src/test/command-center-panel.test.tsx`
- **Prereq:** a **fresh browser profile** (or DevTools → Application → Clear site data). Two separate
  keys must be gone: `hud.firstrun.dismissed` (the gate, `gap.tsx:2816`) **and** `hud.seen` (the WELCOME
  banner, `app.tsx:109`). No model loaded, so the install is genuinely not usable.
- **Steps:** 1) load `/v2`. 2) read every row of the gate. 3) `curl -s http://127.0.0.1:8080/api/onboarding/command-center | python -m json.tool` and reconcile each row.
- **Expected:** a modal titled `FIRST RUN` + `let's get you to a working assistant`, containing
  `COMMAND CENTER` with sub-line `<ready|starting> · <provider or "no route">`, then:
  - `install` → `✓ ready · v<version>` in green (the version matches `/status`),
  - `model` → amber, one of `<id> · configured, not loaded`, `<id> · residency unknown`,
    `model readiness unknown`, or `no runnable model`,
  - `⚠ <wizard hint>` — with no backend: `No conversational model is loaded — load one in LM Studio or
    Ollama, or add a cloud API key in Admin → settings.`,
  - `onboarding` → a dial of ●/○ and `0/5` — **5** wizard steps on this build
    (`onboarding.py:70-76`: intro, model, test_chat, autonomy, product_posture),
  - `WHAT NERVA CAN DO FOR YOU` → exactly 3 outcomes — `Plan my day`, `Use my private documents`,
    `Research the web` — each with a `READY NOW` (green) or `NEEDS SETUP` (amber) tag, two grey chips
    (privacy + `read-only`), and a setup sentence when not live,
  - 3 first actions — `Say hello`, `Get your morning brief`, `Chat with a folder of your docs` — each
    either with a reason string or (for `say_hello` only) a `run` button,
  - `continue to cockpit →`.
- **FAIL if:** any outcome shows `READY NOW` with nothing configured → **BLOCKER**; the version differs
  from `/status` → **MAJOR**; the dial denominator is not 5 → **MINOR** (record the drift; run 1 saw 6 on
  an older build).
- **Evidence:** full-page screenshot + the `command-center` JSON, side by side.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-137 | Gate is truly modal | Press Esc; click the scrim outside the card | **Neither dismisses it** — the scrim has no `onClick` and there is no Esc handler (`gap.tsx:2829-2830`). Only `continue to cockpit →` closes it | MAJOR if the button is also broken (user trapped) | ✅`first-run-gate.test.tsx` |
| SHL-138 | "Say hello" advances the dial 🤖 | Load a model, reload, click `run` on `Say hello` | `↳ <first 140 chars of the reply>` appears and the dial advances `0/5 → 1/5` after the panel reloads (`POST /api/onboarding/funnel {step:"test_chat",event:"complete"}`, **user**) | MAJOR | ✅`command-center-panel.test.tsx` |
| SHL-139 | A degraded hello does **not** tick the step | Force a model 400 (load a model then eject it mid-run) and click `run` | The `↳` line shows the `⚠…` reply **and the dial does not advance** (`gap.tsx:2725-2729`) | **BLOCKER if the wizard claims "Say hello ✓" on a hello that never reached a model** | ✅ same |
| SHL-140 | Chat failure text | Kill the server, click `run` | `↳ chat failed — is a model running?` | MINOR | ✅ same |
| SHL-141 | The other two first actions are inert | Look at `Get your morning brief` / `Chat with a folder of your docs` when `ready:true` | They render with **no** control — only `say_hello` gets a `run` button (`gap.tsx:2800`) | MINOR — gap G12 | ❌ |
| SHL-142 | Dismissal persists | Click `continue to cockpit →`, then hard-refresh | The gate does **not** return; `localStorage['hud.firstrun.dismissed'] === '1'` | MAJOR | ✅`first-run-gate.test.tsx` |
| SHL-143 | Dismissal never expires | With the install still broken (no model), reload 3× | The gate stays dismissed. Re-appearance requires clearing storage or a new profile — **there is no re-nag rule** | MINOR — document it, gap G13 | ✅ same |
| SHL-144 | Gate + banner both appear | Clean storage, no model, server up | Both the `FIRST RUN` modal **and**, underneath it, the `◇ WELCOME` banner (`app.tsx:389-392`) are present — two onboarding surfaces at once | COSMETIC | ❌ |
| SHL-145 | WELCOME banner copy | Dismiss the gate; read the banner | `◇ WELCOME` + `No language model is loaded yet — start LM Studio (or Ollama) and load a model, then this fills with your data.` + `◐ preview with demo` + `dismiss` | MINOR | ❌ |
| SHL-146 | Banner second message | Load a model, reload | The banner is gone entirely (its condition requires `!llm.model` — `app.tsx:389`); the alternate copy "Connect plugins in Admin…" is therefore **unreachable** | COSMETIC — gap G14 | ❌ |
| SHL-147 | `◐ preview with demo` | Click it | Demo turns on: URL gains `?demo=1`, the amber DEMO banner replaces the WELCOME banner | MINOR | ✅`demo-mode.test.tsx` |
| SHL-148 | Banner `dismiss` persists | Click `dismiss`, reload | Banner gone; `localStorage['hud.seen'] === '1'` | MINOR | ❌ |
| SHL-149 | Gate never blocks on an API error | Stop the server, load `/v2` | No gate, no crash — the fetch's `.catch()` is silent and `shouldShowFirstRun(null)` is `false` (`gap.tsx:2818-2821`) | MAJOR if the HUD white-screens | ✅`first-run-gate.test.tsx` |
| SHL-150 | Gate is suppressed in demo | Clean storage, load `/v2/?demo=1` | No gate (the effect returns early on `demo` — `app.tsx:92`) | MINOR | ❌ |

---

## 03.10 Demo mode & LiveSourceChip provenance

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-151 | Demo is URL-driven and exact | Load `/v2/?demo=10`, then `/v2/?demo=0&demo=1` | `demo=10` → **live**; `demo=0&demo=1` → **demo** (exact `1` among duplicates — `demo-mode.ts:3-5`) | MAJOR if `demo=10` enables demo | ✅`demo-mode.test.tsx` |
| SHL-152 | Stale localStorage cannot enable demo | Set `localStorage['hud.demo']='1'`, load `/v2` (no query) | Live mode; the flag is ignored | **BLOCKER if a stale key silently enables seeded data** | ✅ same |
| SHL-153 | Toggle uses replaceState | Toggle demo on then press browser **Back** | No extra history entry was created for the toggle; Back leaves the page (`demo-mode.ts:24`) | MINOR | ✅ same |
| SHL-154 | Popstate exit clears seeded state | From `/v2/?demo=1`, `history.pushState({}, '', '/v2/')` in the console, then Back/Forward | On leaving demo, every seeded surface clears **before paint** (`useLayoutEffect`, `app.tsx:341-344`): agents, messages, decisions, ticker, tasks, weather, calendar, heartbeat, sys, llm, trust, sources, locality | **BLOCKER if any seeded value survives into live mode** | ✅`app-demo-exit.test.tsx` |
| SHL-155 | `exit demo` button | Click it in the banner | Same clearing, URL loses `?demo=1`, banner disappears, in-flight stream aborted (`app.tsx:309-336`) | BLOCKER as above | ✅ same |
| SHL-156 | Late demo poll cannot repaint live | Throttle to Slow 4G, toggle demo off immediately after load | The late demo response is discarded by the generation guard (`loaders.ts:175-213`); no seeded text ever reappears | **BLOCKER** | ✅ same + `loaders.test.ts` |
| SHL-157 | Demo banner is unmistakable | Look at it | Amber diagonal-hatch bar reading `◐ DEMO DATA — seeded sample, not your live backend · /v2/?demo=1` + `exit demo` (`app.tsx:497-506`) | MAJOR if the demo state is ever visually subtle | ✅`demo-mode.test.tsx` |
| SHL-158 | LIVE chip | Visit a mode whose source answered (e.g. `memory`) | A green outlined chip `● LIVE`, title `Live data from the backend` (`LiveSourceChip.tsx`) | MAJOR | ✅`live-source-chip.test.tsx` |
| SHL-159 | SEED chip | In demo, visit a mode whose source is **not** live | An amber `● SEED` chip, title `Seeded demo data — not live` | **BLOCKER if seeded content shows with no chip** | ✅ same |
| SHL-160 | No chip when nothing is showing | Live, no source, visit `trust` | **No** chip — `ModeEmpty` is on screen instead (`liveSourceState` → null) | MINOR | ✅ same |
| SHL-161 | Chip is absent on cockpit/chat/agents/projects | Visit those four | No chip is rendered (they are not routed through the `LiveSourceChip` branch — `app.tsx:442`) | MINOR — gap G15: the cockpit has no per-view provenance chip | ✅ same (`build: undefined` case) |
| SHL-162 | The chip cannot say LIVE on seed | In demo, visit a mode that **is** also live | `live` wins over `seed`; verify the underlying data really is the backend's by cross-checking one value against its `curl` | **BLOCKER on a false LIVE** | ✅ same |
| SHL-163 | ModeEmpty distinguishes wired vs unwired | Compare `trust` (wired) with any unmapped mode | Wired → `Not connected` + "…populates automatically once the source responds"; unmapped → `Design preview` + "This view has no backend wired yet." (`app.tsx:559-577`). On this build **all 12 gated modes are wired**, so `Design preview` should never appear | MINOR if `Design preview` shows | ✅`preview-modes-live.test.ts` |

---

## 03.11 Persistence, responsive layout, keyboard & accessibility

#### SHL-164 — the complete client-state inventory
- **Steps:** DevTools → Application → Local Storage → the HUD origin. Change every pref, reload, confirm each sticks.
- **Expected keys** (all written by `app.tsx:136-143` / `gap.tsx:2816` / `api/client.ts:6-7`):
  `hud.look`, `hud.density`, `hud.motion`, `hud.scanline`, `hud.dotgrid`, `hud.accent`, `hud.lang`,
  `hud.voice` (JSON: mode/tts/lang/barge), `hud.seen`, `hud.firstrun.dismissed`, `hud.user_token`,
  `hud.admin_token`. Plus **sessionStorage** `hud.analytics.sid` (ephemeral, per tab — `analytics.ts:18`).
- **FAIL if:** any pref does not survive reload → **MINOR** each; a **token** is written anywhere other
  than `hud.user_token`/`hud.admin_token`, or a token value appears in a URL or in the analytics body →
  **BLOCKER**.
- **Evidence:** screenshot of the storage table with token values **redacted**.

#### SHL-165 — reduced motion ♿
- **Steps:** 1) Windows → Settings → Accessibility → Visual effects → **Animation effects off**.
  2) load `/v2` in a fresh profile.
- **Expected:** motion defaults to `calm` (`app.tsx:43-47` reads `prefers-reduced-motion`), so
  `data-motion="calm"` is on `.hud-root`: reactor rings still, mesh packets hidden, ticker at half speed.
  Independently, `@media (prefers-reduced-motion: reduce)` kills `.ambient-anim`/`.pkt` regardless of the
  pref (`styles.css:73`).
- **Also:** the palette can override back to `Lively`, and that override wins for the `data-motion` rules
  but **not** for the media query — so packets stay hidden. Record this asymmetry.
- **FAIL if:** with the OS pref on, anything still animates continuously → **MAJOR ♿**.

| ID | Check | Do | Expect | Fail | Auto |
|----|-------|----|--------|------|------|
| SHL-166 | 1100 px breakpoint | Device toolbar → 1024 × 768 | Cockpit collapses to one column, the right context column **disappears** (`display:none`), the rail becomes icon-only, the clock shrinks to 30 px (`styles.css:581-586`) | MAJOR | ❌ |
| SHL-167 | Context column loss is silent | At 1024 px, note that DECISION QUEUE / TODAY / HEARTBEAT / WEATHER are unreachable | There is no alternate route to them at that width | **MAJOR** — the TODAY widget is the anti-fabrication witness and vanishes on a laptop-narrow window; gap G16 | ❌ |
| SHL-168 | 760 px breakpoint | 768 × 1024 | Topbar becomes 2 columns, the clock hides entirely | MINOR | ❌ |
| SHL-169 | Phone width | 390 × 844 (iPhone-class) | `body{overflow:hidden}` + `.badges{display:flex}` with **no wrap** → the six brand badges are clipped and unreachable; there is no horizontal scroll to recover them | **MAJOR** at phone width (the LLM/DATA/EGRESS/MIC honesty badges become invisible); gap G17 | ❌ |
| SHL-170 | Cinema at phone width | 390 px + press `m` | `.cin-word` drops to 22 px, stats to 10 px (`styles.css:625`) — the overlay stays usable | COSMETIC | ✅`cinema.test.tsx` (logic only) |
| SHL-171 | Focus ring is visible ♿ | Tab from the address bar into the page, 25 presses | Every focus stop shows a 2 px accent outline with 2 px offset (`styles.css:592-596`, covering `button, input, a, [tabindex], .rail-btn, .agent-row, .pal-item`) | MAJOR ♿ if any stop has no visible ring | ⚠️`frontend/e2e/a11y.spec.ts` |
| SHL-172 | Focus order is sane ♿ | Record the tab order from load | Order follows DOM: TopBar tool buttons → rail (16) → roster rows → centre tabs → composer → context column panels → the fixed CONSOLE button | MINOR ♿ if focus jumps unpredictably or leaves the viewport without scrolling | ⚠️ same |
| SHL-173 | Overlays do not trap or leak focus ♿ | Open the palette, press Tab repeatedly | Focus should stay within the palette. **Expect a finding:** there is no focus trap — Tab walks out into the cockpit behind the scrim | MAJOR ♿; gap G18 | ❌ |
| SHL-174 | axe audit on real Chromium ♿ | `cd frontend && npm run e2e` (or `npx playwright test e2e/a11y.spec.ts`) | Both specs pass (0 critical/serious); read `frontend/e2e/artifacts/a11y-cockpit.json` and `a11y-cinema.json` and record the moderate/minor tallies as the backlog | MAJOR ♿ per critical/serious violation | ✅`frontend/e2e/a11y.spec.ts` |
| SHL-175 | Mono meta-text contrast ♿👁 | Sample `--ink-3` text (badge keys, timestamps, all empty-state lines) and `--ink-4` text with a contrast checker against `--void` | Measure and record the actual ratio for both tokens (`styles.css:41`: `--ink-3` = 34 % and `--ink-4` = 18 % white over `#04070e`). Judge against WCAG AA 4.5:1 (3:1 for ≥18.66 px) | MAJOR ♿ if the *honesty* strings (`calendar not connected`, `weather not connected`, `○ EMPTY`) are below AA — an unreadable honest state is functionally a hidden one | ⚠️ SHL-174 |
| SHL-176 | 200 % browser zoom ♿ | Ctrl+`+` to 200 % at 1920 px | No content is clipped out of reach; the cockpit reflows or scrolls | MAJOR ♿ | ❌ |
| SHL-177 | Screen-reader smoke ♿ | Narrator on, walk the TopBar | Each badge announces its key + value; the `■ stop` control announces "Stop generating". **Expect a finding:** badges are `div`s with `title` only — no `role`/`aria-label` — so the reading is `AGENTS 17 en` at best and possibly nothing | MAJOR ♿; gap G19 | ⚠️ SHL-174 |

---

## 03.X Degraded & honest-state matrix

Every cell is what the shell **must** show. "—" means the surface is not affected.

| Surface | No model loaded | Model backend absent | Server down mid-session | `user` routes 401 (token set, none entered) | Empty DB / fresh install | Demo on | Cloud key present |
|---|---|---|---|---|---|---|---|
| TopBar LLM badge | `○ NO MODEL` amber, tooltip "LM Studio reachable but no model is loaded" | `○ OFFLINE` grey, "no local LLM backend reachable" | last known value freezes, then `○ OFFLINE` after ≤30 s | `○ —` or last value (`/status` is open, so it keeps working) | `○ OFFLINE` | unchanged (badge reflects the real backend) | unchanged |
| TopBar DATA badge | `● LIVE` or `○ EMPTY` | same | `○ OFFLINE` "server unreachable" | `○ EMPTY` (only open-tier tiles can fill) | `○ EMPTY` | `◐ DEMO` (wins over all) | unchanged |
| TopBar `% LOCAL` | hidden unless strict-local | hidden unless strict-local | last value | hidden (`/api/analytics/locality` is open — so it may still fill) | **hidden** | `87%` | **hidden** until a routed run |
| TopBar EGRESS | `⊘ SEALED` | `⊘ SEALED` | last value | `⊘ SEALED` (open tier) | `⊘ SEALED` | unchanged | `↗ HYBRID` |
| Ticker | header must not claim ALL NOMINAL | same | same | empty track | empty track | 8 seeded items + `◐ DEMO` | — |
| Rail | all 16 clickable | all 16 clickable | all 16 clickable | all 16 clickable | all 16 clickable | — | — |
| Roster | populated | populated | frozen, then empty + honest text | **empty** — must not claim "server unreachable" (SHL-004) | populated (agents exist without a model) | 15 seeded agents | — |
| SYSTEM panel | `no model loaded` | `backend offline` | frozen | still fills (`/status` open) | meters 0 %, `LATENCY —` | — | — |
| DECISION QUEUE | `queue clear ✓` | `queue clear ✓` | `queue clear ✓` | `queue clear ✓` | `queue clear ✓` | 4 seeded cards | — |
| WEATHER | `weather not connected` | same | same | same | same | Bucharest 19° seeded | — |
| TODAY | `calendar not connected` | same | same | same | same | 5 seeded events | — |
| HEARTBEAT | `no activity yet` | same | same | same | same | 5 seeded rows | — |
| Chat send | `⚠ No reply — the model backend is unreachable or no model is loaded…` | same | same | 401 → token prompt, then the same `⚠` notice | same | staged mock (banner visible) | real cloud reply |
| Cognition tab | `Send a message to watch Jarvis think —` | same | same | same | same | mock trace | — |
| Capability modes | `Not connected` + `◐ enable DEMO` | same | same | same | same | full seeded views + `● SEED` chip | — |
| First-run gate | **opens** (model not ready) | opens | does not open (fetch fails silently) | does not open (401 → catch) | opens | suppressed | opens if the wizard is incomplete |
| Prov chip | n/a | n/a | n/a | `locality —` | `0 agents · 0 plugins · locality — · conf 0` | seeded `conf 0.84` | `cloud` |
| Cinema tags | `Trust evidence unavailable` when `sources.trust` is false | same | same | `Trust status connected`/`unavailable` per the open-tier trust call | `Trust status connected` | all tags `DEMO ·` | `Cloud lane reported by trust status` |

**The single rule this table enforces:** in every column, *no cell may contain a plausible number the
backend did not supply*. A dash, an "empty", a "not connected" or a `⚠` is a PASS.

---

## 03.Y Negative, adversarial & abuse cases

#### SHL-178 — 401 token prompt path 🌐
- **Prereq:** restart with `JARVIS_USER_TOKEN=devuser`. **Auto:** ✅`tests/test_web_auth*.py` (server side), ❌ (client side)
- **Steps:** 1) fresh profile, load `/v2`. 2) at the browser prompt reading
  `This Nerva instance is network-exposed. Enter your X-User-Token:` press **Cancel**. 3) note the
  degraded HUD. 4) reload and type `wrong`. 5) reload and type `devuser`.
- **Expected:** Cancel → open-tier tiles only, roster empty, no crash, and **the prompt appears at most
  once per page load** (`_prompted` module flag, `api/client.ts:27,43`). `wrong` → still 401, no retry
  loop, the bad token is nevertheless **persisted** to `hud.user_token`. `devuser` → full HUD after reload.
- **FAIL if:** the prompt fires repeatedly (one per guarded route × per poll = a modal storm) → **MAJOR**;
  a wrong token is retried in an infinite loop → **MAJOR**; the token appears in any URL → **BLOCKER**.
- **Cleanup:** delete `hud.user_token` before continuing the run.

| ID | Adversarial check | Do | Expect | Fail |
|----|-------------------|----|--------|------|
| SHL-179 | Forged token | Set `localStorage['hud.user_token']='../../etc/passwd'`, reload | Guarded routes 401; no traceback, no stack in the response body | MAJOR |
| SHL-180 | Admin-tier route from the HUD | With no admin token, visit `autonomy` | Mode shows `Not connected` (its `/autonomy/brief` + `/autonomy/observer` calls are **admin** tier and 401/403) — it must **degrade**, never show seeded brief items | **BLOCKER** if the 6 seeded brief rows render outside demo |
| SHL-181 | Rate-limit under a wrong token 🌐 | From a second LAN device, hammer `GET /api/agents` with a wrong `X-User-Token` >120×/min | 429s appear (`JARVIS_RATE_LIMIT`, default 120/min); localhost and valid tokens are exempt (`agents/web.py:211-232`) | MAJOR |
| SHL-182 | Oversized composer input | Paste 10,000 chars, send | Rejected (422 → the honest `⚠` notice); the tab does not freeze; the input does not break the layout | MAJOR |
| SHL-183 | Empty + whitespace + newline-only | Send `""`, `"   "`, `"\n"` (paste a newline) | Every one is a client-side no-op; zero network requests | MINOR |
| SHL-184 | Unicode / emoji / RTL | Send `🜁🜂 ماذا يوجد اليوم؟ ✅`, and a 300-char single word | Renders without breaking the bubble; round-trips through `/memory` byte-identical | MAJOR on layout break |
| SHL-185 | HTML/script injection into chat | Send `<img src=x onerror=alert(1)>` and `<b>bold</b>` | Rendered as **literal text** (React escapes; `renderRich` only splits on `**`), no dialog, no bold | **BLOCKER on any script execution** |
| SHL-186 | Markup injection via a decision body | In demo, inspect a card body with `**` | `renderRich` handles it; ambient strips tags via regex (`shell.tsx:355`). Note the regex is not a sanitizer — if a live source ever feeds this path, re-test | MAJOR (latent) |
| SHL-187 | Rapid mode clicking | Click 12 rail buttons in ~2 s | No duplicate mounts, no console errors, exactly one analytics beacon per switch | MAJOR |
| SHL-188 | Rapid demo toggling | Toggle demo 10× in ~5 s | State stays coherent; no seeded value survives an off-transition; URL ends consistent with the badge | **BLOCKER on any leak** |
| SHL-189 | Double-submit via voice + text | Start a voice turn and press Enter in the composer simultaneously | Only one turn runs (the `thinking` guard, `app.tsx:251`) | MAJOR |
| SHL-190 | Refresh mid-stream | Ctrl+R while a reply streams | No partial is persisted (`/memory` has no half turn); after reload the rehydrated transcript shows only completed turns | MAJOR |
| SHL-191 | Back button mid-stream | Press Back while streaming in demo | The demo-exit path aborts the in-flight controller before paint (`app.tsx:341-344,311-313`); no orphaned bubble | MAJOR |
| SHL-192 | Overlay stacking | Open Console, then press `a`, then `m` | Console blocks nothing (its hotkey guard is only for ambient/cinema — `app.tsx:178`), so overlays stack. Record the resulting z-order and whether Esc unwinds them one at a time | MAJOR if the app becomes unreachable without a reload |
| SHL-193 | Palette + hotkeys | Open the palette, click once on the **list area** (not the input), then press Esc, then `3` | Expect a finding: with focus off the input, Esc does nothing (the handler is on the input only — `shell.tsx:306`) and `3` switches the mode **behind** the open palette | MAJOR |
| SHL-194 | Server restart mid-session ⏱ | Kill and restart `serve.py` while the HUD is open | Within ≤30 s the badges go OFFLINE then recover; the transcript in the pane is not wiped; `/memory` may be a new session — the pane must not silently mix two sessions | MAJOR |
| SHL-195 | Clock skew ⏱ | Set the Windows clock forward 3 h, watch the clock and one new reply's timestamp | Both use the browser clock, so both move; a rehydrated turn's timestamp comes from the server's UTC ISO value converted to local (`app.tsx:164`) — after a skew, old and new timestamps will disagree by the skew. Record it; do not file as a data bug | COSMETIC |
| SHL-196 | Day boundary ⏱ | Leave the HUD open across local midnight | The date line rolls over (the clock hook ticks every second); the ticker/heartbeat do not re-label yesterday's items as today | MAJOR if a stale "today" claim persists |
| SHL-197 | 8 h soak ⏱👁 | Leave the cockpit open 8 h with DevTools → Performance monitor | No unbounded growth in JS heap or DOM nodes across ~960 poll cycles (two 30 s intervals: `app.tsx:369`, `live.ts:425`); no accumulating console errors | MAJOR on a leak |
| SHL-198 | Two tabs, one server | Open `/v2` twice; send a turn in tab A; refresh tab B | Tab B rehydrates from `/memory` and shows tab A's turn (same server session) — confirm it does **not** duplicate it | MAJOR |
| SHL-199 | Two tabs, opposite demo state | Tab A `/v2/?demo=1`, tab B `/v2` | Prefs (`hud.*`) are shared via localStorage, so a palette change in A affects B on reload; demo state is **per-URL** and must not bleed | **BLOCKER if tab B ever shows seeded data** |
| SHL-200 | Private/incognito window | Load `/v2` in incognito | Prefs default; storage writes are wrapped in try/catch so a blocked storage never breaks the HUD (`app.tsx:42`); analytics mints a non-persistent session id (`analytics.ts:42-46`) | MAJOR on a white screen |
| SHL-201 | Analytics endpoint down | Block `POST /api/analytics/event` in DevTools → Network → Block request URL, then switch modes | The HUD is unaffected — every analytics path swallows its errors (`analytics.ts:51-73`) | MAJOR if a mode switch fails |
| SHL-202 | SSE stream unavailable | Block `GET /api/cognition/stream`, send a turn | No console noise storm; the post-turn `/api/cognition` snapshot still populates the trace (`app.tsx:197-212` closes the EventSource on error) | MINOR |
| SHL-203 | Malformed SSE frame | With DevTools, is not directly injectable — instead confirm the guard by reading `app.tsx:201-209` and `api/client.ts:79`: both `JSON.parse` calls are wrapped | Malformed frames are ignored, not rendered | MAJOR (code-read only, mark as such) |
| SHL-204 | Server-side turn error leaks into the bubble 🤖 | Force a mid-turn backend exception (e.g. eject the model in LM Studio *while* a long reply streams), then read the agent bubble verbatim | The stream's runner error path emits an `end` frame whose text is `Eroare internă: <exception string>` (`agents/web.py:826`) — so the reply bubble shows a **Romanian** internal-error string plus a raw exception message, in **either** UI language | MAJOR — a raw exception in a user-facing bubble, and an untranslated one; gap G27 |

---

## 03.Z Coverage ledger

| Group | Cases | Needs | Auto-covered | Notes |
|---|---|---|---|---|
| 03.1 Boot & build identity | SHL-001…004 (4) | 👁 ⏱ | 1 partial (`e2e/hud.spec.ts`) | SHL-003/004 are the two run-1 cold-nav findings |
| 03.2 TopBar | SHL-005…029 (25) | 🤖 🔑 👁 ♿ | 7 (`i18n-completeness`, `demo-mode`, `loaders`, `cinema`, `self-hosted-fonts`, `tests/test_trust_api.py`) | badge *rendering* has no offline test at all |
| 03.3 Ticker | SHL-030…036 (7) | 👁 | 2 partial | SHL-030 is a golden-rule case |
| 03.4 Rail & modes | SHL-037…060 (24) | 👁 | 3 partial (`analytics`, `preview-modes-live`, `mesh`) | 16 modes × 3 entry paths |
| 03.5 Palette | SHL-061…082 (22) | 👁 ♿ | 5 (`palette-tweaks`) | display axes covered offline; navigation not |
| 03.6 Overlays | SHL-083…089 (7) | 👁 🤖 | 2 (`cinema`, `gap-panels`) | SHL-084 and SHL-089 are new findings |
| 03.7 Columns | SHL-090…111 (22) | 👁 🖥 | 4 partial (`loaders`) | SHL-102/103 expose a demo-only governance surface |
| 03.8 Chat pane | SHL-112…135 (24) | 🤖 👁 🔑 | 6 (`chatStreamAbort`, `artifacts`, `ttsStream`, `app-demo-exit`, backend chat tests) | R6 lives here (SHL-129) |
| 03.9 First run | SHL-136…150 (15) | 🤖 👁 | 8 (`first-run-gate`, `command-center-panel`) | needs two clean browser profiles |
| 03.10 Demo & provenance | SHL-151…163 (13) | 👁 | 11 (`demo-mode`, `app-demo-exit`, `live-source-chip`, `loaders`, `preview-modes-live`) | best-covered group offline |
| 03.11 Persistence/responsive/a11y | SHL-164…177 (14) | 👁 ♿ ⏱ | 2 (`e2e/a11y.spec.ts` partial) | SHL-174 runs the real axe gate |
| 03.Y Adversarial | SHL-178…204 (27) | 🌐 ⏱ 🔑 🤖 | ~4 (server-side auth/rate-limit tests) | SHL-181 needs a second LAN device |
| **Total** | **204 cases** | — | **~55 with any offline coverage (~27 %)** | The shell chrome itself (TopBar, Ticker, Rail, RosterColumn, ContextColumn) has **no** dedicated vitest file — `app-demo-exit.test.tsx` *mocks all five away*. This section is the only coverage those five have. |

Frontend suite context: 373 vitest tests via `cd frontend && npm test`; the root `npm test` runs a
*different* suite (`tests/frontend/**/*.test.js`, the legacy static HUD — `vitest.config.js`). Do not
conflate the two counts.

---

## Open gaps found while writing


Observations only — no code was changed. Line numbers are from this revision and **will drift**;
re-locate by the quoted string rather than the number. G-numbers are referenced inline above.

- **G1 — brand drift in the shell wordmark** (SHL-005). `shell.tsx:49` renders `JARVIS` as the top-left
  wordmark and `shell.tsx:391` renders `JARVIS` in Cinema, while the page title is `NERVA · HUD`
  (`agents/web/v2/index.html`), the focus-chat head says `DIRECT LINE · NERVA` (`modes3.tsx:18`), and the
  first wizard step is titled `Welcome to Jarvis` (`agents/core/routers/onboarding.py:71`). CLAUDE.md
  records the product rename as executed 2026-07-19.
- **G2 — the `locked` mode flag is dead code.** `MODES` declares `locked?: boolean` and both `Rail` and
  `Tabs` implement locked styling and click-suppression (`shell.tsx:104-105,117-119`; `.rail-btn.locked`
  at `styles.css:143`), but **no entry sets it**. A "locked mode behaves correctly" test is therefore
  **not runnable** on this build — I deliberately did not write one.
- **G3 — `Tabs` is unreachable.** `app.tsx:58` pins `const ia = 'rail'`, so the `tabs` information
  architecture and its CSS (`.main[data-ia="tabs"]`, `styles.css:129`) never render in the shipped app.
- **G4 — the palette has no fuzzy matching** (SHL-064). `shell.tsx:290` filters with
  `name.toLowerCase().includes(q.toLowerCase())` — a plain substring test.
- **G5 — palette coverage gaps** (SHL-081). No entry opens the Console, enters Cinema mode, or toggles
  demo; all three exist only as hotkeys/buttons, so a keyboard-only user who does not already know
  `` ` `` / `m` cannot reach them.
- **G6 — routing confidence is computed and then discarded** (SHL-088). The prov chip prints `conf`
  (`cockpit.tsx:60`) but nothing in the shell escalates a low value into a visible caveat — exactly the
  missing signal named as the run-1 systemic root cause.
- **G7 — status vocabulary mismatch** (SHL-094). `_enrich_agents` emits only `ready`/`idle`
  (`agents/web.py:677`) while `statusClass` (`primitives.tsx:53`) and `isExecutingAgent`
  (`mesh.tsx:62-65`) key off `active`/`busy`/`err`. Consequence: every heartbeat agent shows the *idle*
  dot, and the TopBar's `· N ▶` "actually running" counter can never fire from `/api/agents`.
- **G8 — `_sys_info` never populates `backend` or `latency`** (SHL-097/098/100). `agents/web.py:575-586`
  leaves both at `"unknown"`/`0`, so the SYSTEM panel reads `unknown · <model>` and `LATENCY p50 —`
  even though `/status.llm_backend` knows the real string. Worse, `shell.tsx:231` falls back to the
  literal `'LM Studio'` when the field is absent — a hardcoded backend name inside an
  anti-fabrication product.
- **G9 — the composer is single-line** (SHL-117). `cockpit.tsx:222` is an `<input>`, so multi-line
  prompts cannot be composed; Enter always submits and Shift+Enter does not insert a newline.
- **G10 — the cockpit DECISION QUEUE is demo-only** (SHL-102/103). `setDecisions` is only ever fed
  `V2.DECISIONS` under `demo` (`app.tsx:98,146`); no loader writes it. The cockpit therefore prints
  `queue clear ✓` while the real governed queue (Console → DECISION INBOX) has pending items.
  Additionally both buttons on a card call the same `onDecision(d._id)` (`shell.tsx:141`) and merely
  filter the item out client-side (`app.tsx:372`) — approve and reject are indistinguishable and
  neither reaches an API.
- **G11 — the focus-chat head hardcodes a locality claim** (SHL-135). `modes3.tsx:19` renders a green dot
  plus the literal `local` regardless of the route actually used, so it can contradict the same turn's
  prov chip reading `cloud`.
- **G12 — two of the three first actions are inert** (SHL-141). Only `say_hello` gets a `run` button
  (`gap.tsx:2800`); `morning_brief` and `index_docs` render as rows with no control even when the backend
  reports `ready:true`.
- **G13 — the first-run gate never re-nags** (SHL-143). Dismissal is permanent per browser profile
  (`FIRST_RUN_DISMISS_KEY`, `gap.tsx:2816`) with no revisit rule even if the install is still unusable.
  Two separate dismissal keys exist (`hud.firstrun.dismissed` for the gate, `hud.seen` for the WELCOME
  banner), so a valid "clean first-run" test must clear both.
- **G14 — unreachable onboarding copy + step-count drift** (SHL-146). The WELCOME banner's second message
  ("Connect plugins in Admin to populate weather, calendar, email and the rest.", `app.tsx:522`) can
  never render because the banner's own condition requires `!llm.model` (`app.tsx:389`). Separately, the
  wizard has **5** steps on this build (`onboarding.py:70-76`) while run 1 observed a `0/6 → 1/6` dial —
  build drift a reader of that report will trip over.
- **G15 — the cockpit and chat have no provenance chip** (SHL-161). `LiveSourceChip` is rendered only on
  the gated-capability branch (`app.tsx:442`), so the two surfaces where fabrication actually appeared in
  run 1 carry no LIVE/SEED label of their own.
- **G16 — the right context column disappears below 1100 px** (SHL-167). `styles.css:583` sets
  `.col.scrollcol { display:none }` with no alternate route. That column holds **TODAY** — the widget
  this manual relies on as the anti-fabrication witness — so a laptop-narrow window silently removes the
  cross-check.
- **G17 — TopBar badges are clipped at phone width** (SHL-169). `.badges` has no `flex-wrap`
  (`styles.css:99`) and `body` has `overflow:hidden` (`styles.css:25`), so below ~700 px the LLM / DATA /
  EGRESS / MIC honesty badges are cut off with no scroll to recover them.
- **G18 — no overlay focus trap** (SHL-173). The palette, provenance modal, first-run gate and Console
  all render as plain `div`s inside `.pal-scrim` with no `role="dialog"`, no `aria-modal`, and no focus
  containment, so Tab walks out into the cockpit behind the scrim.
- **G19 — no ARIA on the TopBar badges** (SHL-177). They are `div`s carrying only a `title`
  (`shell.tsx:51-56`), so their state is not exposed to assistive technology; `title` is the only
  channel for the honesty tooltips.
- **G20 — the ticker header is an unconditional claim** (SHL-030). `shell.tsx:78-81` always renders a
  pulsing red dot, the label `SITUATION`, and `ALL NOMINAL`, independent of `items` — including with zero
  items and with a `hi`-severity item scrolling past. Run 1 recorded exactly this shape (a real GECKO
  finance alert live on screen while other surfaces reported all-clear).
- **G21 — `Dossier` is keyed to the seeded 15-agent table** (SHL-089/093). `modes.tsx:50,60` looks the id
  up in `V2.AGENTS` and returns `null` when absent, so clicking **howard** or **argus** in the live
  17-agent roster opens nothing while `setActiveId` still retargets chat. `V2.GLYPHS` (`data.ts:6-22`)
  also has no glyph for either, so their roster and mesh glyphs render as an empty SVG path; and
  `_AGENT_META` (`agents/web.py:650-667`) has no `howard`, so its role line is blank and its tier
  defaults to `FND`.
- **G22 — the chat bubble has no `white-space` or `overflow-wrap`** (SHL-133). `styles.css:230` — so
  newlines collapse into one paragraph and long unbroken tokens can overflow. Compare
  `.art-plain { white-space:pre-wrap }` and `.art-body { overflow-wrap:anywhere }`
  (`styles.css:641,643`), which the artifacts panel *does* set. `renderRich` (`cockpit.tsx:81-85`)
  handles only `**bold**`, so fenced code blocks render as inline prose including the backticks.
- **G23 — the rehydrated transcript is silently capped at 20 turns** (SHL-130). `GET /memory` calls
  `get_history(..., last_n=20)` (`agents/core/routers/memory_hud.py:35`) and the HUD renders whatever it
  gets with no "earlier turns not shown" affordance.
- **G24 — the conversation force-scrolls unconditionally** (SHL-132). `cockpit.tsx:29` assigns
  `scrollTop = scrollHeight` on every `messages`/`thinking` change, so you cannot read history while a
  reply streams.
- **G25 — z-index collision: the fixed `▦ CONSOLE` button paints over Ambient** (SHL-084). Inline
  `zIndex:50` (`app.tsx:456-457`) beats `.ambient` z-index 40 (`styles.css:408`) and ties with the
  Dossier scrim (z 50). It is correctly hidden under Cinema (z 90) and the palette scrim (z 80).
- **G26 — partial localization plus dead i18n keys** (SHL-028). Eleven EN keys are defined but never
  rendered (`context`, `focusHint`, `kgTitle`, `killTitle`, `online`, and others), while a large set of
  *visible* shell strings is hardcoded English and absent from the table entirely (every badge value and
  tooltip, all four empty-state lines, every palette entry, the first-run and demo banners, `ModeEmpty`,
  the `⚠ No reply …` notice, the whole Console overlay). The offline gate
  (`frontend/src/test/i18n-completeness.test.ts`) can therefore pass while RO mode is only partly
  localized.
- **G27 — a server-side turn error reaches the user bubble raw and in Romanian** (SHL-204).
  `agents/web.py:826` emits `end` with `text = f'Eroare internă: {data}'`, where `data` is
  `str(exception)` — an untranslated internal-error string plus a raw exception message rendered as if it
  were the agent's reply.

**Could not verify / a reviewer must re-check.** (i) The exact contrast ratios in SHL-175 — I computed
them from the token definitions rather than measuring composited pixels, and axe may or may not flag
them; treat the numbers as a hypothesis until the run records real measurements. (ii) Whether the
committed bundle at `agents/web/v2/assets/index-BQpwz2br.js` is byte-equivalent to a fresh build of the
current `frontend/src` — I confirmed only that six representative strings are present in it, which is
why SHL-002 exists. (iii) Whether run 1's false Kill-Switch "ENGAGED" still reproduces — that card lives
in the Console TRUST section and belongs to §05's scope, so SHL-086 only grades that the section mounts.
(iv) Whether `Narrator`/NVDA actually announces the badges (SHL-177) — predicted from the DOM, not
observed. (v) `sys.latency` semantics: `_sys_info` initializes it to `0` and I found no writer, but I did
not exhaustively grep every mutation path, so SHL-100's "can never be non-zero" claim needs one live
confirmation.
