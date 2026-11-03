# Family Store

> Frigga's 100% local family data store (Max sleep & more) — zero external network

**Version:** 0.1.0
**Author:** claude
**Agents:** frigga
**Requires:**

## Usage
Stores simple per-person logs in a local SQLite DB (`memory_logs/family.db`).
No cloud, no external calls — Frigga is local-only by design.

## Commands
- `log_sleep <input>` — record a sleep entry: `<person> <hours>`
- `get_sleep <input>` — recent sleep for `<person>` plus a short average

## Example Output
```
Am notat: Max a dormit 9h.
Max: ultima noapte 9h, media ultimelor 3 = 8.7h.
```
