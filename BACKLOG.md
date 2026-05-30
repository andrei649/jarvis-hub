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
| B-9 | `web/static/app.js` ~127-150 | SSE: handler-ul de `end` din bucla principală **nu face `break`**, iar fragmentul rămas în `buf` e reprocesat după buclă → **mesaj agent dublat** dacă `end` ajunge într-un chunk parțial. VERIFICAT 30 mai. | 🔄 |
| W-9 | `web/static/app.js` ~27-37 | Fără indicator de loading; fallback mock persistă tăcut dacă API e down. VERIFICAT (0 `loading` în app.js; doar admin.js are). | ⬜ |
| W-8 | `web/static/admin.js:262` | `Channel` select are doar `['voice','web','telegram']` — lipsesc `discord`, `email`, `slack` (deși există adaptere în backend). VERIFICAT. | ⬜ |

## P2 — Curățenie / minore (verificate)

| ID | Fișier | Problemă | Status |
|----|--------|----------|--------|
| W-3 | `admin.js:94` | `AGENT_GLYPHS` duplică `JARVIS_GLYPHS` din `data.js:5`. VERIFICAT. | ⬜ |
| W-2 | `admin.js:217` | `SettingsPage` definit dar **niciodată randat** (cod mort). VERIFICAT (0 `h(SettingsPage`). | ⬜ |
| B-8 | `admin.js:238` | `kind:"button"` → `onAction`; niciun setting nu e `button` (no-op până se adaugă unul). | ⬜ |
| IMP-5 | `admin.js:272` | `key:Date.now()` în Toast (anti-pattern React key). VERIFICAT. | ⬜ |
| 2.2 | `app.js:39,58` | Race: poll 30s (data) vs 10s (status) suprascriu reciproc `sys`. | ⬜ |
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

**Sesiunea 3a (commit e00d9dc):**
- CI: `pytest.ini` (asyncio auto)
- `settings_db`: thread-safe init, WAL o dată/proces, log chei necunoscute
- `network.js`: RING_ORDER dinamic
- `orchestrator`: atribuire memorie pe agentul real
- README sincronizat + `tests/test_settings_db.py`

---

## Ordinea de execuție (PM)
1. **B-9** — corectitudine chat (mesaje duble) ← *în lucru*
2. **W-9** — UX loading/stale
3. **W-8** — canale complete în admin
4. **W-2 + W-3** — curățenie cod mort + glyph duplicat (quick wins)
5. Restul P2
