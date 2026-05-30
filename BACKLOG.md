# Jarvis Hub — Backlog (PM-tracked)

> Owner: Andrei · Menținut de Claude
> Start: 2026-05-30 (sesiunea 3)
> Test: `python -m pytest` · HUD: http://127.0.0.1:8000/ · Admin: /admin
> **Regulă: verifică în cod că bugul încă există înainte de a-l rezolva.**

Legenda: ⬜ todo · 🔄 în lucru · ✅ done · ❌ invalid (verificat, nu e bug)

---

## P1 — Impact vizibil pentru user

| ID | Fișier | Problemă | Status |
|----|--------|----------|--------|
| B-9 | `web/static/app.js` | SSE: `end` nu făcea `break`, buf reprocesat → mesaj dublat. **Fix: guard `finished` + break.** | ✅ |
| W-9 | `web/static/app.js` | Fără loading; mock persistă tăcut dacă API e down. **Fix: overlay `loading` + banner `apiDown`, reset pe poll.** | ✅ |
| W-8 | `web/static/admin.js` | `Channel` select fără discord/email/slack. **Fix: adăugate.** | ✅ |

## P2 — Curățenie / minore (verificate)

| ID | Fișier | Problemă | Status |
|----|--------|----------|--------|
| W-3 | `admin.js` | `AGENT_GLYPHS` duplica `JARVIS_GLYPHS`. **Fix: ref la `window.JARVIS_GLYPHS`.** | ✅ |
| W-2 | `admin.js` | `SettingsPage` cod mort. **Fix: eliminat, `renderRow` păstrat.** | ✅ |
| B-8 | `admin.js:226` | `kind:"button"` → `onAction`; niciun setting nu e `button` (no-op până se adaugă unul). | ⬜ |
| IMP-5 | `admin.js` Toast | `key:Date.now()` (anti-pattern React key). | ⬜ |
| 2.2 | `app.js` | Race: poll 30s (data) vs 10s (status) suprascriu reciproc `sys`. | ⬜ |
| 5.4 | `orchestrator.py` ~382 | `intent.target_agents[0]` în `_gather_plugin_data` — gardat, dar fragil. | ⬜ |
| W-6 | `web/templates/index.html` | `data-density`/`data-scanline` nesetate deși CSS le suportă. | ⬜ |
| IMP-2 | `web.py` | Polling fără `Cache-Control`/`ETag`. | ⬜ |
| IMP-10 | `network.js` | SVG `<animate>` rulează și în tab ascuns. | ⬜ |
| W-7 | multiple | Stringuri RO hardcodate, fără i18n. | ⬜ |

## ❌ Invalidate la verificare (NU sunt buguri)

| ID | Motiv |
|----|-------|
| C-1 (data.js dublat) | FALS — data.js are 129 linii, `JARVIS_GLYPHS` declarat o singură dată. |
| W-1 (`VoiceVisualizer` mort) | FALS — randat/exportat la `components.js:424`. |

## ✅ Rezolvate

**Sesiunea 3b (commit d38d822) — frontend QA:**
- B-9: SSE dedup (guard `finished` + break)
- W-9: loading overlay + banner „backend indisponibil" + CSS
- W-8: canale complete în admin (discord/email/slack)
- W-3: glyph map unic (referință la `window.JARVIS_GLYPHS`)
- W-2: eliminat `SettingsPage` mort
- Smoke test: `/`, `/admin`, `/status`, `/api/agents`, toate `/static/*` → 200

**Sesiunea 3a (commit e00d9dc) — backend QA:**
- CI: `pytest.ini` (asyncio auto)
- `settings_db`: thread-safe init, WAL o dată/proces, log chei necunoscute
- `network.js`: RING_ORDER dinamic
- `orchestrator`: atribuire memorie pe agentul real
- README sincronizat + `tests/test_settings_db.py`

---

## Ordinea de execuție (PM) — următorii pași
1. ~~B-9, W-9, W-8, W-2, W-3~~ ✅ (sesiunea 3)
2. **2.2** — race condition la polling (corectitudine date sys)
3. **IMP-10** — pauză `<animate>` în tab ascuns (perf/baterie)
4. **IMP-5** — React key stabil în Toast
5. **W-6** — aplică `data-density`/`data-scanline` din settings
6. **B-8** — wire `kind:"button"` când apare primul buton
7. **W-7** — i18n (efort mare, ultimul)
