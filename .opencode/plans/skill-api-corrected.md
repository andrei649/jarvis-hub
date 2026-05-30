# Plan de execuție corectat — API real de skill

> Autor: Claude · 2026-05-30 (sesiunea 4)
> Scop: corectează pattern-ul de implementare folosit în batch-prompt-ul de
> „full implementation". Pattern-ul din acel prompt era FABRICAT și ar fi
> produs cod care nu se importă. Acesta e API-ul VERIFICAT din cod.

---

## ⚠️ Ce era greșit în batch-prompt (verificat în cod)

| Afirmație în prompt | Realitate (fișier:linie) |
|---|---|
| `from core.skill_base import Skill` | **NU există** `skill_base.py`. Clasa `Skill` e în `agents/core/skills/loader.py:19` |
| Skill = clasă cu `execute(self, intent, orch)` | Skill = **director** `skills/<name>/` cu `SKILL.md` + `main.py`. Semnătura reală: `execute(command, args, context)` |
| Routing pe `capabilities`/`keywords` în `agents.yaml` | `agents.yaml` **nu** are aceste chei. Routing-ul e în `router.py:41` → dict `INTENT_KEYWORDS` |
| `.env`: `TAVILY_API_KEY`, `OPENWEATHER_API_KEY` | **Absente** din `.env.example`. Web search există deja (`websearch.py`), vremea via wttr.in (fără cheie) |
| Skill se înregistrează automat „dacă e în `agents/core/skills/`" | Fals — skill packs se descoperă din `skills/` (root), via `SkillLoader.discover()` |

---

## ✅ Pattern REAL de skill (din `skills/user_greeting_055711/`)

Un skill = un **director** `skills/<name>/` cu două fișiere:

### 1. `skills/<name>/SKILL.md` (manifest — parsat de `loader._parse_manifest`)
```markdown
# Nume Skill
> descriere scurtă

**Version:** 0.1.0
**Author:** cabinet-agent:<agent_id>
**Agents:** jerome
**Requires:** httpx

## Commands
- `play_focus <query>` — pornește muzică de focus
```
Reguli parser (verificate `loader.py:133-159`):
- `# titlu` → name · `> ...` → description · `**Agents:** a, b` → listă agenți
- Comenzile se citesc DOAR sub `## Commands`, format exact:
  `` - `command_name <arg>` — descriere `` (regex: `loader.py:153`)

### 2. `skills/<name>/main.py` (modul Python)
```python
async def handle(cmd: str, args: str, context: dict) -> str:
    ...
    return "text răspuns"

def get_commands() -> list[str]:
    return ["play_focus"]

def register(skill):
    skill.register_command("play_focus", handle)
```
Loader-ul (`loader.py:102-117`): importă `main.py`, cheamă `register(skill)` dacă
există, altfel mapează fiecare nume din `get_commands()` la atributul cu acel nume.

### 3. Invocare (orchestrator)
`orchestrator.py:255` → `self.skills.parse_command(text)` returnează
`(skill_name, command, args)`; apoi `skill.execute(command, args, context)`.

---

## 🚦 Stare reală a backlog-ului (verificat 30 mai, sincron cu opencode 6e4d502)

Opencode menține deja procentajele în `BACKLOG.md`. Pe scurt:
- **H1 Foundation: 100%** ✅ (voice, telegram, web, OAuth, admin→runtime)
- **H2 Core Agent: 17%** — doar H2.12 (hybrid router) gata; 11 skill-uri agent rămase
- **H3 Intelligence: 0%** · **H4 Platform: 0%**
- **Bugfixes: 100%** · **Securitate: 60%** (S1-S3 gata, S4+PKCE rămase)

## 🔒 Taskuri BLOCATE de infrastructură externă (nu pot fi „terminate" în repo)

Acestea cer servicii/credențiale care nu există în mediul de dev — orice agent
care le „implementează" produce doar schelet + fallback, NU funcționalitate:

| Task | Blocat de |
|---|---|
| H2.6 Gecko Balance | API bănci ING/Libră (nu există) → doar fallback spreadsheet |
| H2.11 Stark GA4 | acces GA4/Firebase API |
| H3.1 Qdrant | server Qdrant pornit |
| H3.2 Neo4j | server Neo4j pornit |
| H4.4 Ultron Security | Pi-hole + firewall |
| H4.6 Oracle n8n | n8n pornit |
| H4.8 Sandbox Docker | Docker daemon |

## ✅ Taskuri REALIZABILE complet în repo (skill + test, fără infra externă)

Ordine recomandată (skill-uri pure, fiecare = 1 director + 1 test):
1. **H2.10 Veronica** — content drafting (pur LLM, fără API extern)
2. **H2.5 Jerome Spotify** — plugin Spotify există deja (`spotify_plugin.py`)
3. **H2.9 Vision** — websearch există deja (`websearch.py`)
4. **H2.1 Pepper Calendar** — OAuth + `google_calendar.py` există
5. **H2.2 Pepper Email** — `gmail_plugin.py` există
6. **H2.3 Friday Brief** — weather (wttr.in) + news (RSS) + websearch, toate există
7. **H2.4 Hercules Health** — `apple_health.py` există (bridge local)
8. **H2.7 Hephaestus / H2.8 Frigga** — SQLite local (fără rețea)

## ⚙️ Recomandare de proces (evită coliziunea cu opencode)
- Opencode editează activ `master` (ultima dată chiar `BACKLOG.md`). **Doi agenți
  autonomi pe același branch = conflicte.**
- Orice implementare reală să se facă pe **branch separat** + PR, NU push direct
  pe master în paralel cu opencode.
- Fiecare skill nou trebuie să aibă `tests/test_<name>.py` care **trece** înainte
  de merge (regula proiectului: `python -m pytest` verde).
