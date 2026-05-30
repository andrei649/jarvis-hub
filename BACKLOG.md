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
| 2.2 | `app.js` | Poll 30s (data) suprascria `sys` peste poll 10s (status). **Fix: 30s nu mai atinge `sys`.** | ✅ |
| IMP-5 | `admin.js` Toast | `key:Date.now()` forța remount la fiecare render. **Fix: eliminat.** | ✅ |
| W-6 | `web/templates/index.html` | `data-density`/`data-scanline`/`data-dotgrid` nesetate. **Fix: bootstrap pre-paint din localStorage.** | ✅ |
| IMP-10 | `network.js` | SVG SMIL (`<animate>`/`<animateMotion>`, L194-202/369-371) rula și în tab ascuns. **Fix: `pauseAnimations()` pe `visibilitychange` + skip spawn packets.** | ✅ |
| B-8 | `admin.js:226` | `kind:"button"` → `onAction`; niciun setting nu e `button` (no-op până se adaugă unul). | ⬜ |
| 5.4 | `orchestrator.py` ~382 | `intent.target_agents[0]` în `_gather_plugin_data` — gardat, dar fragil. | ⬜ |
| IMP-2 | `web.py` | Polling fără `Cache-Control`/`ETag`. | ⬜ |
| W-7 | multiple | Stringuri RO hardcodate, fără i18n. | ⬜ |

## ❌ Invalidate la verificare (NU sunt buguri)

| ID | Motiv |
|----|-------|
| C-1 (data.js dublat) | FALS — data.js are 129 linii, `JARVIS_GLYPHS` declarat o singură dată. |
| W-1 (`VoiceVisualizer` mort) | FALS — randat/exportat la `components.js:424`. |

> Notă: IMP-10 fusese marcat eronat „fals" la o verificare grăbită (grep `<animate ` cu spațiu). La re-verificare s-au găsit `animateMotion`/`animate` reale → reparat.

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

## ✅ Rezolvate (continuare)

**Sesiunea 3c (commit 9c0bb35 + următorul):**
- 2.2: poll 30s nu mai suprascrie `sys`
- IMP-5: Toast fără `key:Date.now()`
- W-6: bootstrap pre-paint pentru data-attrs UI
- IMP-10: pauză animații SVG în tab ascuns

## Ordinea de execuție (PM) — următorii pași
1. ~~B-9, W-9, W-8, W-2, W-3~~ ✅ (sesiunea 3b)
2. ~~2.2, IMP-5, W-6, IMP-10~~ ✅ (sesiunea 3c)
3. **5.4** — guard `target_agents[0]` în `_gather_plugin_data` (robustețe)
4. **IMP-2** — `Cache-Control`/`ETag` pe endpointuri de polling (perf rețea)
5. **B-8** — wire `kind:"button"` când apare primul buton
6. **W-7** — i18n (efort mare, ultimul)
