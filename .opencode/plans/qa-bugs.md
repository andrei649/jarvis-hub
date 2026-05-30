# Jarvis HUB — QA Bug & Improvement List

> Ultimul update: 2026-05-30 (sesiunea 3 — config teste + 5 bug-uri fixate)
> Server: `uvicorn agents.web:app --host 127.0.0.1 --port 8080`
> Teste: `python -m pytest` (config în `pytest.ini`, asyncio auto)
> 26 tests passing, 10/10 admin categories, 52 settings seeded

## Fixate în sesiunea 3 (30 mai)

| ID | Fișier | Ce s-a reparat |
|---|---|---|
| CI | `pytest.ini` (nou) | `asyncio_mode=auto` — cele 4 teste async nu mai pică fără flag manual; `python -m pytest` merge din prima |
| new-6.1 | `settings_db.py` | `_ensure_init()` thread-safe — `threading.Lock` cu double-checked locking |
| new-6.2 | `settings_db.py` | `put_category` loghează cheile necunoscute ignorate (nu mai e silențios) |
| new-6.3 | `settings_db.py` | `PRAGMA journal_mode=WAL` o singură dată per proces (flag `_wal_set`), nu la fiecare conexiune |
| WARN-5 | `network.js` | `RING_ORDER` dinamic — agenții noi din API apar automat în graf (nu mai e hardcodat la 14) |
| new-5.1 | `orchestrator.py` | Non-stream path atribuie memoria agentului real (`responder_id`) când nu e sinteză Jarvis, nu hardcodat `"jarvis"` |
| test | `tests/test_settings_db.py` (nou) | 5 teste pentru seeding/get/put/unknown-key |

## Fixate în sesiunea 1 (29 mai)

| ID | Fișier | Ce s-a reparat |
|---|---|---|
| B10 | `agents/core/settings_db.py` | `init_db()` mutat din import-time în lazy (`_ensure_init()`) |
| B1 | `agents/web.py:211` | `/chat/stream` pasă `agent_override` la `handle_input_stream` |
| — | `agents/core/settings_db.py` | Adăugate 3 categorii lipsă: `agents` (4 settings), `skills` (4), `system` (4). Total 52 defaults |
| B2 | `components.js:156` | `(sys.latency \|\| 0).toFixed(1)` |
| B3 | `components.js:140` | `(a.model \|\| '').split('-')` |
| B6 | `web.py:283` | `orch.plugins.get("weather")` în loc de `plugins["weather"]` |
| B7 | `components.js:270` | `agentMap[thinking] \|\| { name: thinking }` |
| B5 | `app.js:272` | `filter_project` logat (nu ignorat) |

## Fixate în sesiunea 2 (29 mai)

| ID | Fișier | Ce s-a reparat |
|---|---|---|
| new-4.4 | `web.py:194` | `/chat` endpoint — adăugat try/except cu logger.exception |
| new-4.5 | `web.py:608` | `ORDER BY id` → `ORDER BY rowid` (sigur pe SQLite) |
| new-5.2 | `orchestrator.py:363,374` | `plugins["weather"]`/`["news"]` → `.get()` cu guard, nu mai crapă dacă pluginul lipsește |
| new-5.3 | `orchestrator.py:272` | **Confirmat că nu e bug** — `GuardrailsEngine` are `generate_stream` |
| new-5.1 | `orchestrator.py:311` | Memory logging stream path folosește `agent_id` real în loc de hardcoded `"jarvis"` |
| new-1.2 | `components.js:221` | `.toUpperCase()` nu mai crapă — fallback `'unknown'` |
| new-2.1 | `app.js:28,41` | Adăugat `.catch()` pe ambele efecte `loadJarvisData` |
| new-1.1 | `components.js:138-139` | `a.name`/`a.role` cu fallback (`a.id`, `''`) |
| new-1.3 | `components.js:368` | `via ${it.owner || '—'}` |
| new-1.4 | `components.js:345-352` | `f.hr`/`f.t` cu fallback -> `''`/`''` |
| new-3.3 | `admin.js:253-256` | `agent.name`/`role`/`tier` cu fallback (`agent.id`, `''`, `'FND'`) |
| new-3.4 | `admin.js:152` | `min\|\|0` → `min ?? 0` (nullish coalescing) |
| new-5.5 | `orchestrator.py:483` | `self.session_id[:20]` → `(self.session_id or 'none')[:20]` |
| new-4.3 | `web.py:285` | `_dashboard_cache["cached_at"]` → `_dashboard_cache.get("cached_at", 0)` |
| BUG-4 | `web.py` + `admin.js` | Adăugat `PUT /api/admin/agents/{id}` endpoint; `onAgentUpdate` face fetch real |
| new-2.3 | `app.js:170` | Deja fixat — `location.hostname !== 'localhost'` există în cod |
| new-2.4 | `app.js:185` | **Confirmat că nu e bug** — `recRef.current` e corect gestionat (onerror/onend/stop nullify) |

## Bug-uri rămase (nefixate)

### 🟡 Medii
| ID | Fișier | Linie | Problemă |
|---|---|---|---|
| BUG-9 | `app.js` | 110-150 | SSE stream produce mesaje duplicate dacă `\n\n` e divizat în 2 chunk-uri TCP |
| WARN-9 | `app.js` | 27-37 | Fără indicator de loading; mock data persistă fără avertisment dacă API e down |

### 🟢 Minore
| ID | Fișier | Linie | Problemă |
|---|---|---|---|
| BUG-8 | `admin.js` | 454 | `kind: "button"` settings nu funcționează — `onAction` = no-op (niciun setting nu e `button`) |
| new-2.2 | `app.js` | 40-52 vs 58-75 | Race condition: 30s data poll suprascrie 10s status poll |
| new-4.6 | `web.py` | 608 | Table name interpolat în SQL (validat dar anti-pattern) |
| new-5.4 | `orchestrator.py` | 358 | `intent.target_agents[0]` — IndexError dacă listă goală (deși gardat) |
| WARN-1 | `components.js` | 165-204 | `VoiceVisualizer` mort (~120 linii + CSS) |
| WARN-2 | `admin.js` | 217-227 | `SettingsPage` mort (gruparea neterminată) |
| WARN-3 | `admin.js` / `data.js` | 94-110 | `AGENT_GLYPHS` duplicat |
| WARN-6 | `index.html` | — | `data-density`/`data-scanline` etc. nu sunt setate, deși CSS le suportă |
| WARN-7 | Multiple | — | Strings hardcodate în română fără i18n |
| WARN-8 | `admin.js` | 262 | Canale omit `discord`, `email`, `slack` |

### Îmbunătățiri rămase
| ID | Fișier | Linie | Problemă |
|---|---|---|---|
| IMP-2 | `web.py` | Multiple | Polling fără `Cache-Control`/`ETag`. Frontend face polling la 10s fix |
| IMP-4 | `settings_db.py` | 91-92 | `force=True` nedeclarat în UI/API |
| IMP-5 | `admin.js` | 272 | `Date.now()` ca React key în Toast |
| IMP-10 | `network.js` | 356-361 | SVG `<animate>` rulează și în tab ascuns |

## Cum se pornește / testează

```bash
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080
python -m pytest tests/ -v
```

Admin: http://localhost:8080/admin
HUD: http://localhost:8080/
După modificări JS: Ctrl+F5 în browser.
