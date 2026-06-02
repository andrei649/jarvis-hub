# Profiling căii per-turn — unde se pierde timpul (2026-06-02)

> Context: „se mișcă cam încet". Profiling pe calea de request din orchestrator
> (`handle_input` / `handle_input_stream` / `_call_agents_parallel`), nu pe
> generarea LLM (care e separat, ~4–5s/query și ține de strategia de model).

## Ce face calea la fiecare turn (în afară de apelul LLM)

| Pas | Cost | Observație |
|---|---|---|
| `router.classify` | mic | keyword-based; LLM fallback doar sub prag de încredere |
| `_gather_plugin_data` | 0 sau network | rulează un plugin **doar** dacă apar keyword-uri (weather/news/…) |
| `checkpoints.save(self)` | **sqlite commit** | `json.dumps(state)` + INSERT + `commit()` **sincron**, fiecare turn |
| `audit.log(...)` | **sqlite commit** | INSERT + `commit()` + sha256 (lanț Merkle) **sincron**, fiecare turn |
| `_record_interactions` / `_log_session` | append JSONL | open/write per turn |
| `memory.*` | serializat | toate trec printr-un singur `asyncio.Lock` |
| recall (nou, opt-in) | network/turn | embedding `/v1/embeddings` per query, fără cache |

## Măsurători (micro-benchmark, 500 ops, acest mediu — SSD/tmpfs)

| Operație | Default | WAL + `synchronous=NORMAL` |
|---|---|---|
| sqlite insert+commit | **3317 µs/op** | **92 µs/op** (~**36× mai rapid**) |
| jsonl append (open/write) | 12 µs/op | — |
| sha256 merkle | 1.5 µs/op | — |

**Cheia:** scrierile sqlite sunt **sincrone în event-loop-ul async**. Calea face ~2
commit-uri/turn (checkpoint + audit) ≈ 6.6 ms aici — dar pe disc real cu `fsync`
adevărat (System76) poate fi 10–50 ms/commit. Cât durează commit-ul, **niciun
request concurent nu avansează**. JSONL și sha256 sunt neglijabile.

## Aplicat acum (sigur, măsurat)

- **WAL + `synchronous=NORMAL`** pe DB-urile scrise des:
  `checkpoint.py`, `security/audit.py`, `autonomy/queue.py`.
  Durabilitatea se păstrează (WAL e crash-safe; NORMAL e sigur cu WAL).
  ~36× mai ieftin per commit, deci event-loop-ul e blocat mult mai puțin.

## Recomandări rămase (în ordinea raportului calitate/efort)

1. **Mută scrierile blocante de pe event-loop** — `await asyncio.to_thread(...)`
   pentru `checkpoints.save` / `audit.log` / JSONL, sau fire-and-forget +
   debounce pe checkpoint (nu e nevoie de save complet la fiecare turn).
2. **Debounce/scădere frecvență checkpoint** — `json.dumps(state)` al întregului
   orchestrator la fiecare turn e și CPU; salvează la N turns sau pe shutdown.
3. **Cache pentru query-embedding (recall)** — `Embedder.from_env(cache_dir=...)`
   + fast-fail când LM Studio embeddings nu rulează (deja `max_retries=1`).
4. **Strategie fast/heavy model** — pentru cele ~4–5s/query: model 14–32B 100%
   în VRAM pentru task-uri ușoare, 70B cu spillover doar pentru raționament greu.
