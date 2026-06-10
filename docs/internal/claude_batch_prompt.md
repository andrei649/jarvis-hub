# Batch Prompt — Jarvis Hub Full Implementation (~700K token budget)

## Rol

Ești un **Project Manager AI** care coordonează o echipă de agenți subordonați pentru a implementa toate taskurile rămase din Jarvis Hub. Lucrezi într-o singură sesiune cu un buget de ~700K tokeni.

## Strategie de execuție

1. **Faza 0 — Plan** (5K tokeni): Citește BACKLOG.md, apoi publică planul de execuție cu ordinea și alocarea.
2. **Faza 1-5 — Execuție paralelă** (650K tokeni): Pentru fiecare fază, lansezi sub-agenți (Task tool) pentru taskuri independente, apoi unifici.
3. **Faza 6 — Integrare + Testare** (45K tokeni): Rulezi toate testele, repari ce e stricat, verifici smoke test.

## Ordinea de execuție (dependențe)

```
Faza 1: H3.5 Heartbeat (deja gata), H3.1 Qdrant, H2.9 Vision Web Research, H2.10 Veronica Drafting, H2.8 Frigga Local Store
        → toate independente, se pot face paralel

Faza 2: H2.1 Pepper Calendar, H2.2 Pepper Email Triage, H2.5 Jerome Spotify
        → toate depind de H1.4 (OAuth deja gata), independente între ele

Faza 3: H2.3 Friday Morning Brief, H2.4 Hercules Apple Health, H2.7 Hephaestus PM, H2.11 Stark GA4
        → independente între ele

Faza 4: H2.6 Gecko Balance (blocat de API bănci, fă spreadsheet fallback)
        H3.2 Neo4j Knowledge Graph, H3.3 Session Persistence
        → H3.3 depinde de H3.1

Faza 5: H3.4 Learning Loop (depinde H3.1+H3.3), H3.6 Bench Activation (depinde H3.4)
        H4.1-H4.11 (toate independente), Cross-cutting, Securitate
```

## Context pre-incărcat (nu mai citi din repo, economisești tokeni)

### Structură skill standard
Toate skill-urile urmează acest pattern:

```python
# agents/core/skills/<name>.py
from core.skill_base import Skill

class <Name>Skill(Skill):
    def __init__(self):
        super().__init__("name", "description")

    async def execute(self, intent, orch):
        # logic here
        return response_text
```

### Integrare agent
Skills se înregistrează automat dacă sunt în `agents/core/skills/`.
Routing-ul e în `agents/_system/agents.yaml` pe `capabilities` și `keywords`.

### Teste
Testele sunt în `tests/test_<name>.py` și folosesc pytest + pytest-asyncio.

```python
import pytest
@pytest.mark.asyncio
async def test_<name>():
    ...
```

### API keys existente în .env
- GEMINI_API_KEY, TAVILY_API_KEY, OPENWEATHER_API_KEY
- TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN, SLACK_BOT_TOKEN
- SMTP_HOST, IMAP_HOST, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

### Pattern OAuth
`plugins/oauth.py` are deja: `get_google_auth_url()`, `exchange_google_code()`, `refresh_google_token()`
Tokenii se salvează în `memory_logs/tokens/<service>.json`.

## Format output

Pentru fiecare task, scrii:

```
## [DONE] H2.X — Nume
- Fișiere create: path/la/fisier.py, tests/test_fisier.py
- Teste: pytest tests/test_fisier.py -v ✅
- Tokeni consumați: ~XXK
```

## Reguli

- Nu rescrie cod existent care funcționează
- Testează doar critical path (1-2 asserturi per test)
- Dacă un API key lipsește, implementează fallback + log warning
- La final: `python -m pytest tests/ -v` trebuie să treacă
- Commit și push la final pe main

---

**Buget estimat per task:**
| Categorie | Tokeni | Efort |
|-----------|--------|-------|
| Skill simplu (H2.5, H2.10) | ~12K | 1 sub-agent |
| Skill mediu (H2.1, H2.2, H2.9) | ~20K | 1 sub-agent |
| Skill complex (H2.3, H2.6, H2.7) | ~25K | 1-2 sub-agenți |
| Infrastructură (H3.x, H4.x) | ~18-28K | 1 sub-agent |
| Cross-cutting | ~10-15K | 1 sub-agent |

**Total estimat: ~600-650K tokeni** (încăpe în 700K cu marjă)
