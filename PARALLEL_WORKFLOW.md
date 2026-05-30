# Parallel Development Protocol

> Reguli pentru lucrul simultan: **Big Pickle / Opus 4.8** (opencode) ↔ **Claude Code**

## 1. File Ownership

| Cale | Stăpân | Regulă |
|------|--------|--------|
| `agents/core/plugins/oracle_bridge.py` | opencode | Only opencode edits. Claude reads-only. |
| `agents/core/llm/` | opencode | Hybrid router, Gemini backend, tokenizer. Claude reads-only. |
| `agents/web/static/admin.js` | opencode | Admin panel UI. Merge manual dacă ambii editează. |
| `agents/web/static/i18n.js` | opencode | String dictionary. Doar opencode adaugă stringuri noi. |
| `agents/web.py` | opencode | API endpoints pentru Oracle. Claude poate adăuga endpointuri NOI la sfârșitul fișierului. |
| `agents/core/orchestrator.py` | opencode | Wiring Oracle. Claude poate adăuga pluginuri NOI, NU atinge cod Oracle existent. |
| `BACKLOG.md` | opencode | Status și estimări. |
| `PARALLEL_WORKFLOW.md` | opencode | Acest fișier. |
| `agents/core/skills/` | Claude | Toate skill-urile H2.x. opencode nu atinge. |
| `tests/test_*.py` | Claude | Teste noi pentru skill-uri H2.x. opencode nu atinge. |
| `agents/core/plugins/<new_plugin>.py` | Claude | Pluginuri H2.x (calendar, spotify, etc.). |
| `agents/core/security/` | Claude | S4, S-PKCE hardening. |
| `agents/web/static/*.js` (except admin.js/i18n.js) | Claude | Componente vizuale HUD. |
| `agents/web/static/*.css` | Claude | CSS. |
| `agents/web/templates/` | Claude | Template-uri. |
| `agents/_system/agents.yaml` | **AMBII** | Merge manual. Adăugați secțiuni, NU ștergeți. |
| `.env.example` | **AMBII** | Merge manual. Adăugați variabile, NU ștergeți. |

## 2. Lock Protocol

Înainte de a edita ORICE fișier, verificați lock-ul:

### Lock files

Lock-urile sunt în `memory_logs/oracle/locks/`:
```
memory_logs/oracle/locks/
  claude.active     → Claude Code e activ
  opencode.active   → OpenCode e activ
  <file>.lock       → Fișier individual blocat
```

### Reguli

1. **Verifică înainte de editare**: dacă `claude.active` există, NU edita fișiere din ownership Claude. Dacă `opencode.active` există, Claude NU editează fișiere opencode.
2. **Shared files** (`agents.yaml`, `.env.example`, `orchestrator.py`, `web.py`): verificați dacă fișierul e deja modificat local (`git status`) înainte de a-l edita. Dacă da, NU editați — lăsați celălalt agent să termine și faceți merge manual.
3. **La pornire**: scrieți lock-ul vostru (`claude.active` sau `opencode.active`) cu conținut = ce intenționați să faceți.
4. **La terminare**: ștergeți lock-ul.

### Comenzi

```bash
# Lock (opencode)
echo "working on oracle bridge, admin panel" > memory_logs/oracle/locks/opencode.active

# Lock (claude)
echo "implementing H2 skills, tests" > memory_logs/oracle/locks/claude.active

# Check
ls memory_logs/oracle/locks/

# Unlock
rm memory_logs/oracle/locks/opencode.active
```

## 3. Commit Protocol

### Commit-uri separate

- **OpenCode**: prefix `feat(oracle):`, `feat(admin):`, `docs(backlog):`
- **Claude**: prefix `feat(H2.x):`, `feat(H3.x):`, `feat(H4.x):`, `fix:`
- **Ambii**: prefix `merge:`

### Ordine

1. OpenCode face commit + push PRIMUL (dacă e cazul)
2. Claude face `git pull --rebase` înainte de a începe
3. Claude face commit + push la final
4. OpenCode face `git pull --rebase` după ce Claude termină

### Evitare conflicte

- **NU editați fișiere care au fost modificate în ultimele 24h de celălalt agent** (verificați `git log --oneline <file>`)
- Dacă un fișier e în `ownership` celuilalt agent și trebuie modificat, creați un ticket în `BACKLOG.md` secțiunea `# Atenționări conflicte`
- Pentru `agents.yaml` și `.env.example`: adăugați la sfârșit, NU în mijloc

## 4. Detecție automată

Oracle Bridge (panoul Admin → Oracle) detectează automat conflicte prin:

- **Hash comparison** — compară MD5 local vs hash-ul din ultimul sync
- **Git log** — verifică cine a modificat ultimul un fișier
- **Lock files** — ce agent e activ

> Rulează `python -c "from agents.core.plugins.oracle_bridge import check_conflicts; print(check_conflicts())"` pentru verificare manuală.

## 5. Recovery

Dacă apar conflicte:

1. **Nu panică** — conflictele sunt așteptate în paralel development
2. **Verifică** `git status` și `git diff`
3. **Rezolvă** manual în editor (păstrează ambele contribuții)
4. **Commit** cu `git commit -m "merge: resolve <file> conflict between opencode and claude"`
5. **Mark resolved** în Oracle → butonul "✅ Rezolvă conflictele" din Admin
