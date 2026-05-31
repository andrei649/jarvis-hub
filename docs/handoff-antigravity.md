# Salut, Antigravity 👋 — de la Claude Code

> Coordonare între agenți pentru `jarvis-hub`. Lucrăm pe același cod, în paralel.
> Autor: **Claude Code** (Opus 4.8) · Cui: **Antigravity** · Actualizat: 2026-05-31

## Cum circulă codul între noi (important — tu nu ai GitHub)
```
Claude (eu, în cloud, doar GitHub)  ⇄  GitHub: branch `main`  ⇄  [GitHub Desktop, Andrei sincronizează]  ⇄  copia locală  ⇄  Antigravity (tu, doar local)
```
- **Tu (Antigravity):** vezi DOAR copia locală. Nu ai branch-uri, PR-uri, push/pull. Lucrezi pe `main` local și **commiți local**.
- **Eu (Claude):** comit mic și des direct pe `main` și dau push. După ce Andrei apasă **Sync** în GitHub Desktop, schimbările mele apar la tine local.
- **Andrei = puntea:** trage commit-urile mele jos și împinge commit-urile tale sus, prin GitHub Desktop.
- Deci: **PR-urile sunt inutile pentru noi** (tu nu le vezi). Coordonarea se face prin fișiere **urmărite în git** (vezi tabla de mai jos), nu prin lock-uri (`lock.py` scrie în `memory_logs/`, care e **gitignored** → nu se sincronizează).

## Regula de aur: stăm în lane-uri separate
Cea mai ușoară cale de a evita conflicte în GitHub Desktop e să **nu atingem aceleași fișiere**. Împărțire propusă (negociabilă):

| Lane | Fișiere | Cine |
|---|---|---|
| Autonomy / routing / observer | `core/router.py`, `core/autonomy/*` | **Claude** (eu) |
| Memory fusion (HybridRetriever, consolidare) | `core/memory/*` | **liber → ia-l tu** |
| HUD / PWA | `agents/web/static/*`, `agents/web/templates/*` | **liber → ia-l tu** |
| Voice / TTFB | `core/voice/*` | liber |
| Fișiere partajate (`orchestrator.py`, `web.py`, `agents.yaml`, `.env.example`, `BACKLOG.md`) | **doar adăugiri** la sfârșit, niciodată rescrieri în mijloc | ambii |

Dacă trebuie să atingi un fișier din lane-ul meu, scrie un rând în tabla de mai jos **și commite-l** înainte — îl văd la următorul sync.

## 🟢 Tablă de coordonare (urmărită în git → se sincronizează)
> Editați acest tabel în commit-urile voastre. E „cine lucrează la ce, acum".

| Agent | Lucrez la | Fișiere atinse | De la |
|---|---|---|---|
| Claude | autonomy/observer + routing (livrat) | `core/router.py`, `core/autonomy/observer.py` | 2026-05-31 |
| Antigravity | _(scrie aici ce începi)_ | | |

## Cum lucrezi tu (Antigravity, doar local)
1. **Sync întâi** (cere-i lui Andrei un Sync în GitHub Desktop) ca să pornești de pe ultimul `main`.
2. Lucrează în lane-ul tău; **commit local** cu mesaj clar (prefix `feat(...)`, `fix:`, `docs:`).
3. Actualizează **tabla de coordonare** în commit dacă începi ceva nou sau atingi un fișier partajat.
4. Spune-i lui Andrei „gata de push" → el împinge prin GitHub Desktop → eu te văd.
5. **Mențin verde:** `python -m pytest tests/ -q` trebuie să rămână ≥ ce era (acum **715 passed, 8 skipped**).

## Starea repo-ului acum
- Un singur branch: **`main`** (== `67e83f0`). `master` și branch-urile vechi au fost șterse — single-branch, curat.
- Setup: Python 3.11/3.12 + `pip install -r requirements-beta.txt`. Test: `python -m pytest tests/`.
- Recent integrat: **H5.9 + H5.10** (resilience tab + live data wiring) și **MCU audit** (router rescris bilingv RO/EN + `core/autonomy/observer.py`). Detalii: `docs/gap-analysis-mcu-jarvis.md`.

## Ce am atins eu recent (evită coliziunile)
- `core/router.py` — **rescris** (intent router determinist, bilingv, scored). Contractul `classify()/Intent/ROUTING_TABLE` e stabil; dacă-l schimbi, anunță în tablă.
- `core/autonomy/observer.py` — **nou** (Proactive OS Observer). Extinde cu probe noi, nu rescrie debounce-ul.
- `core/autonomy/{queue,worker,policy,inbox,digest,preferences}.py` — rail-uri stabile; integrează-te prin `worker.submit(...)`.
- `web.py` / `orchestrator.py` — am adăugat doar lucruri **noi** (endpointuri observer, wiring). Adaugă-le pe ale tale tot la sfârșit.

Spor la treabă — hai să-l ducem pe Jarvis cât mai aproape de J.A.R.V.I.S. 🚀

— Claude
