# Nerva vs Hermes / OpenClaw — Subsystem Differentiator Benchmarks (2026-11-14)

> **Scope & Honesty Disclosure (`hermetic_in_process` · `live_network_llm_calls = 0`)**
>
> Every measurement in this report was produced by executing Nerva's real production Python
> subsystems in-process via [`scripts/bench_nerva_differentiators.py`](../../scripts/bench_nerva_differentiators.py)
> against deterministic synthetic LLM/transport backends (`JARVIS_TESTING=1`, temporary sandbox).
> These numbers prove **architectural & security invariants, USD cost governance, failover latency, and asyncio fan-out speedup**.
> They do **not** claim live cloud provider throughput or owner-gated live desktop/browser head-to-head
> task win-rates, which remain governed separately by [`docs/HARDWARE_BENCHMARKS.md`](../HARDWARE_BENCHMARKS.md)
> and [`docs/HERMES_HEAD_TO_HEAD.md`](../HERMES_HEAD_TO_HEAD.md).

- **Schema:** `nerva.differentiator_bench.v1`
- **Suite Spec Digest (`sha256`):** `41749416ec5f0ac25d1db6ed78ff9ddb631e357746d4081cacec81009f1a0167`
- **Machine-Readable Artifact:** [`nerva-vs-hermes-openclaw-2026-11-14.json`](nerva-vs-hermes-openclaw-2026-11-14.json)
- **Verification Suite:** [`tests/test_bench_nerva_differentiators.py`](../../tests/test_bench_nerva_differentiators.py)
- **Result:** `6/6` subsystem benchmarks passed

---

## Executive Comparison Matrix

| # | Differentiator Workload | Nerva Subsystem | Nerva Measured Outcome | Baseline Pattern (Hermes / OpenClaw Default) | Status |
|---|---|---|---|---|---|
| 1 | **Resilient Hybrid Committee** (4 proposers, 1 fault/timeout, `min_quorum=3`) | [`agents/core/llm/moa.py`](../../agents/core/llm/moa.py) (`H032`) | `100%` quorum completion; `3.98x` steady parallel speedup (`2.14x` overall wall speedup); `2.0s` timeout cap & `256`-tok budget enforced | `0%` completion on faulted sequential chain (waits full timeout then aborts) | PASS |
| 2 | **Controllable Cloud Privacy** (mixed local + unconsented cloud committee on 4 sensitive prompts) | [`agents/core/llm/moa.py`](../../agents/core/llm/moa.py) + [`data_handling.py`](../../agents/core/llm/data_handling.py) (`H513`) | `0` cloud calls / `0` tokens leaked (`100%` block accuracy); `100%` grounded local synthesis | `4` cloud calls (`78` tokens) sent without per-member configuration-bound consent (`0%` block) | PASS |
| 3 | **Surviving-Host Room Failover & Split-Brain Fencing** (primary outage + `epoch+1` promote + stale writes) | [`agents/core/rooms.py`](../../agents/core/rooms.py) (`H657`) | `100%` stale-epoch write rejection (`409 room_fenced`); `0`/`12` lost entries; `0.478 ms` promote latency | `0%` stale write rejection in unfenced room stores (split-brain log divergence) | PASS |
| 4 | **Identity-Scoped Browser Broker** (8 SSRF targets, 6 cross-principal probes, 6 ticket replays) | [`agents/core/browser_broker.py`](../../agents/core/browser_broker.py) (`H086`) | `100%` SSRF block; `100%` cross-principal isolation; `100%` one-shot HTTPS ticket replay rejection (`410`) | `0%` private-CIDR block, `0%` principal isolation, and `0%` replay rejection on unguarded shared CDP/static file bridges | PASS |
| 5 | **Secret-Stripped E2E Cross-Device Sync** (`4` seeded secrets, `8` ciphertext bit-flips, `3!` LWW arrival orders) | [`agents/core/e2e_sync.py`](../../agents/core/e2e_sync.py) + [`settings_db.py`](../../agents/core/settings_db.py) (`H040`) | `0` leaked secrets; `100%` authenticated ciphertext tamper rejection (`fernet-aes128-cbc-hmac-sha256`); `100%` deterministic LWW convergence directly in `E2ESync.pull_state()` + hostile skill quarantined | Raw config sync leaks `4` secrets; unsorted FIFO arrival-order ingestion converges on `33.3%` of permutations | PASS |
| 6 | **Governed Cost- & SLA-Aware Adaptive Model Cascade** (`20` mixed turns: local, consented cloud, USD-capped, H513/strict-local/pinned, SLA stall) | [`agents/core/llm/cost_cascade.py`](../../agents/core/llm/cost_cascade.py) + [`cost_estimator.py`](../../agents/core/llm/cost_estimator.py) | `84.8%` USD cost reduction (`$0.006975` vs `$0.045925`); `0` budget overruns (`100%` cap enforcement); `0` unconsented cloud escalations; `100%` completion via graceful local fallback | Cloud-always static routing spends `$0.045925`, leaks `4` unconsented/restricted escalations, and aborts on cloud SLA stall (`95%` completion) | PASS |

---

## Subsystem Workload Details & Cryptographic Notes

### 1. Resilient Hybrid Committee (`H032`)
- **Workload:** 4-proposer committee (`local`, `local-deep`, `ollama:qwen2.5-coder`, `ollama:faulty-node`) with `min_quorum=3`, `timeout_s=2.0`, and `max_tokens=256` across 4 rounds (`timeout_fault`, `transport_exception`, `degraded_reply`, and `all_healthy`), plus a below-quorum negative control (`2/4 < 3` failing closed with `RuntimeError`).
- **Why Nerva wins:** `MoACommitteeBackend` dispatches all proposers concurrently via `asyncio.gather` with per-proposer `asyncio.wait_for` bounds and `is_degraded_reply` filtering, synthesizing verified drafts as soon as quorum holds instead of blocking sequentially and failing on the first broken endpoint.

### 2. Controllable Cloud Privacy (`H513`)
- **Workload:** 4 sensitive prompts (medical, IBAN/tax, home security PIN log, M&A clause) executed against a hybrid preset containing an unacknowledged `openai-compatible` cloud member (`data_policy="unknown"`) behind a local aggregator, alongside `LOCAL_ONLY_AGENTS` (`ultron`) and a pure-local `local-moa` preset.
- **Why Nerva wins:** `MoACommitteeBackend._authorize_all_members()` enforces `data_handling.authorize()` across **every** proposer and the aggregator prior to any network/backend call. Unconsented cloud members cannot hide behind a local synthesizer (`0` calls, `0` tokens leaked).

### 3. Surviving-Host Room Failover & Split-Brain Fencing (`H657`)
- **Workload:** Primary `host-alpha` writes 12 room turns, exports hash-chained verbatim log pages (`SHA-256` over `(room_id, seq, epoch, host, kind, role, agent, text, prev_digest)`), and replicates to `host-beta` (verifying duplicate idempotency, `409 sequence_gap`, and `409 log_divergence`). `host-beta` promotes with `confirm=True` to `epoch=2`, signs an HMAC-SHA256 fencing proof, and fences returning `host-alpha` (`403` on forged signature, `409 room_fenced` on all 8 post-fence stale writes).

### 4. Identity-Scoped Browser Broker (`H086`)
- **Workload:** `BrowserControlBroker(allow_loopback_http=False)` tested against 8 SSRF/scheme vectors (`169.254.169.254`, `127.0.0.1`, `[::1]`, `localhost`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `file://`), 6 cross-principal session/command/ticket probes between `owner-alice` and `peer-bob`, plain-HTTP transport refusal (`403 https_required`), and 6 one-shot upload/download ticket replay attempts (`410 ticket_already_used`).

### 5. Secret-Stripped E2E Cross-Device Sync (`H040`)
- **Workload & Cipher Note:** `E2ESync` (`agents/core/e2e_sync.py`) encrypts artefacts using authenticated **Fernet (`AES-128-CBC + HMAC-SHA256`)** with keys derived via `PBKDF2-HMAC-SHA256` (`390,000` iterations) — not AES-GCM — providing identical `100%` authenticated-ciphertext bit-flip tamper rejection across IV, ciphertext blocks, and MAC tag (`8/8` tampered envelopes rejected). `settings_db.export_settings()` strips all `SECRET_KEYS`, `ROUTE_ONLY` consent rows, and credential-shaped strings (`0` secrets in envelope), and `detect_injection_normalized` quarantines hostile synced `SKILL.md` payloads before disk write.
- **Production LWW Convergence:** `E2ESync.pull_state()` authenticates/decrypts inbound peer manifests first (so forged unauthenticated entries cannot skew timestamps) and sorts verified manifests canonically by `(max_ts, device_id, digest)` before applying artefacts, achieving `6/6` (`100%`) deterministic convergence directly in production across all `3!` multi-device arrival permutations vs `33.3%` on unsorted FIFO ingestion.

### 6. Governed Cost- & SLA-Aware Adaptive Model Cascade
- **Workload:** 20-turn mixed session (`10` confident local fast/deep turns on `google/gemma-4-12b` / `deepseek-r1-distill-qwen-32b`, `3` consented low-confidence escalations to `claude-opus-4-7` priced via `cost_estimator.estimate_cost`, `2` turns exceeding `max_turn_usd=$0.010` and `max_session_usd=$0.012`, `4` governance-restricted escalations across unacknowledged H513 `data_policy="unknown"`, `LOCAL_ONLY_AGENTS` `ultron`, `JARVIS_STRICT_LOCAL=1`, and `approved_models` pinning, plus `1` cloud SLA stall).
- **Why Nerva wins:** `AdaptiveCostCascade` (`agents/core/llm/cost_cascade.py`) reserves worst-case `(input_tokens + max_tokens)` USD atomically **before** any cloud call and settles actual token spend afterward, guaranteeing `0` USD cap overruns (`$0.006975 <= $0.012`), `0` unconsented cloud escalations, `84.8%` USD savings vs static cloud routing, and `100%` (`20/20`) turn completion via `$0.00` local fallback synthesis.

## Reproducing & Verifying

```bash
python scripts/bench_nerva_differentiators.py \
  --json-out docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.json \
  --md-out docs/benchmarks/nerva-vs-hermes-openclaw-2026-11-14.md

python scripts/bench_nerva_differentiators.py --check
```
