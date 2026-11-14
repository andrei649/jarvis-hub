# Nerva — Offline Subsystem Invariant Measurements (2026-11-14)

> **Scope & Honesty Disclosure (`hermetic_in_process` · `live_network_llm_calls = 0`)**
>
> Every measurement in this report was produced by executing Nerva's real production Python
> subsystems in-process via [`scripts/bench_nerva_differentiators.py`](../../scripts/bench_nerva_differentiators.py)
> against deterministic synthetic LLM/transport backends (`JARVIS_TESTING=1`, temporary sandbox).
> These fixtures check bounded subsystem invariants and record local timing; they are not product comparisons.
> Baselines are illustrative synthetic patterns, including declared constants. Hermes/OpenClaw are not executed.
> They do **not** claim live cloud provider throughput or owner-gated live desktop/browser head-to-head
> task win-rates, which remain governed separately by [`docs/HARDWARE_BENCHMARKS.md`](../HARDWARE_BENCHMARKS.md)
> and [`docs/HERMES_HEAD_TO_HEAD.md`](../HERMES_HEAD_TO_HEAD.md).

- **Schema:** `nerva.differentiator_bench.v2`
- **Suite Spec Digest (`sha256`):** `89354b6d8452a6bd16cfa6ce478cbde2938a365ca033a110c269f7bd768b0171`
- **Synthetic token units:** `len(text.encode('utf-8')) // 4 + 1`; fixed fixture accounting, not provider vocabulary or billed/live tokens.
- **Machine-Readable Artifact:** [`nerva-vs-hermes-openclaw-2026-11-14.json`](nerva-vs-hermes-openclaw-2026-11-14.json)
- **Verification Suite:** [`tests/test_bench_nerva_differentiators.py`](../../tests/test_bench_nerva_differentiators.py)
- **Result:** `5/5` subsystem benchmarks passed

---

## Fixture Outcomes

| # | Fixture Workload | Nerva Subsystem | Recorded Outcome | Illustrative Baseline (not competitor measurement) | Status |
|---|---|---|---|---|---|
| 1 | **Resilient Hybrid Committee** (4 proposers, 1 fault/timeout, `min_quorum=3`) | [`agents/core/llm/moa.py`](../../agents/core/llm/moa.py) (`H032`) | `100%` quorum completion; `3.99x` steady parallel speedup (`2.14x` overall wall speedup); `2.0s` timeout cap & `256`-tok budget enforced | `0%` completion on faulted sequential chain (waits full timeout then aborts) | PASS |
| 2 | **Controllable Cloud Privacy** (mixed local + unconsented cloud committee on 4 sensitive prompts) | [`agents/core/llm/moa.py`](../../agents/core/llm/moa.py) + [`data_handling.py`](../../agents/core/llm/data_handling.py) (`H513`) | `0` cloud calls / `0` synthetic token units leaked (`100%` block accuracy); `100%` grounded local synthesis | `4` cloud calls (`71` synthetic token units) sent without per-member configuration-bound consent (`0%` block) | PASS |
| 3 | **Surviving-Host Room Failover & Split-Brain Fencing** (primary outage + `epoch+1` promote + stale writes) | [`agents/core/rooms.py`](../../agents/core/rooms.py) (`H657`) | `100%` stale-epoch write rejection (`409 room_fenced`); `0`/`12` lost entries; `0.321 ms` promote latency | `0%` stale write rejection in unfenced room stores (split-brain log divergence) | PASS |
| 4 | **Identity-Scoped Browser Broker** (8 SSRF targets, 6 cross-principal probes, 6 ticket replays) | [`agents/core/browser_broker.py`](../../agents/core/browser_broker.py) (`H086`) | `100%` SSRF block; `100%` cross-principal isolation; `100%` one-shot HTTPS ticket replay rejection (`410`) | `0%` private-CIDR block, `0%` principal isolation, and `0%` replay rejection on unguarded shared CDP/static file bridges | PASS |
| 5 | **Encrypted Candidate Staging & Local Preservation** (`4` seeded secrets, `8` bit-flips, `6` arrival orders) | [`agents/core/e2e_sync.py`](../../agents/core/e2e_sync.py) + [`settings_db.py`](../../agents/core/settings_db.py) (`H040`; `stage_only`) | `0` leaked secrets; `100%` tamper rejection; identical sets of `6` encrypted candidates; `100%` local preservation and restart/replay idempotence; no automatic apply/install | Raw config copying would expose `4` fixture credentials; illustrative only | PASS |

---

## Subsystem Workload Details & Cryptographic Notes

### 1. Resilient Hybrid Committee (`H032`)
- **Workload:** 4-proposer committee (`local`, `local-deep`, `ollama:qwen2.5-coder`, `ollama:faulty-node`) with `min_quorum=3`, `timeout_s=2.0`, and `max_tokens=256` across 4 rounds (`timeout_fault`, `transport_exception`, `degraded_reply`, and `all_healthy`), plus a below-quorum negative control (`2/4 < 3` failing closed with `RuntimeError`).
- **Observed contract:** `MoACommitteeBackend` dispatches all proposers concurrently via `asyncio.gather` with per-proposer `asyncio.wait_for` bounds and `is_degraded_reply` filtering, waiting for all proposer attempts before applying the quorum threshold. Model residency is outside the generation timeout; early-quorum latency is not demonstrated.

### 2. Controllable Cloud Privacy (`H513`)
- **Workload:** 4 sensitive prompts (medical, IBAN/tax, home security PIN log, M&A clause) executed against a hybrid preset containing an unacknowledged `openai-compatible` cloud member (`data_policy="unknown"`) behind a local aggregator, alongside `LOCAL_ONLY_AGENTS` (`ultron`) and a pure-local `local-moa` preset.
- **Observed contract:** `MoACommitteeBackend._authorize_all_members()` enforces `data_handling.authorize()` across **every** proposer and the aggregator prior to any network/backend call. Unconsented cloud members cannot hide behind a local synthesizer (`0` calls, `0` tokens leaked).

### 3. Surviving-Host Room Failover & Split-Brain Fencing (`H657`)
- **Workload:** Primary `host-alpha` writes 12 room turns, exports hash-chained verbatim log pages (`SHA-256` over `(room_id, seq, epoch, host, kind, role, agent, text, prev_digest)`), and replicates to `host-beta` (verifying duplicate idempotency, `409 sequence_gap`, and `409 log_divergence`). `host-beta` promotes with `confirm=True` to `epoch=2`, signs an HMAC-SHA256 fencing proof, and fences returning `host-alpha` (`403` on forged signature, `409 room_fenced` on all 8 post-fence stale writes).

### 4. Identity-Scoped Browser Broker (`H086`)
- **Workload:** `BrowserControlBroker(allow_loopback_http=False)` tested against 8 SSRF/scheme vectors (`169.254.169.254`, `127.0.0.1`, `[::1]`, `localhost`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `file://`), 6 cross-principal session/command/ticket probes between `owner-alice` and `peer-bob`, plain-HTTP transport refusal (`403 https_required`), and 6 one-shot upload/download ticket replay attempts (`410 ticket_already_used`).

### 5. Encrypted Candidate Staging & Local Preservation (`H040`)
- **Crypto workload:** Fernet (`AES-128-CBC + HMAC-SHA256`), secret-free export, hostile skill rejection and eight ciphertext bit-flips. Valid config/skill candidates remain encrypted in a private SQLite inbox; no target skill installation or settings mutation occurs.
- **Preservation workload:** Three devices contribute six candidates across all six arrival permutations, with deliberately misleading outer timestamps/device labels/digests. Local settings and skill bytes remain unchanged. After further owner edits and node recreation, replay returns the same candidate set without reopening application.
- **Limits:** No LWW winner, automatic conflict reconciliation, owner candidate retrieval/import/install UI, key migration or skill-loader admission is implemented by this fixture. Room failover above likewise demonstrates explicit promotion/demotion, not automatic partition fencing.

## Reproducing & Verifying

```bash
python scripts/bench_nerva_differentiators.py \
  --json-out docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.json \
  --md-out docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.md

python scripts/bench_nerva_differentiators.py --check
```
