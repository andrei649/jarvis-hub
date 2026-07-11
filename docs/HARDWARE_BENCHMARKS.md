# Hardware benchmarks — what runs decently, honestly (FB4)

> **Purpose.** Calibrate tester expectations with *measured* local-model throughput per VRAM
> tier, instead of vibes. A recurring alpha question is *"local-only on 8GB — is it actually
> usable?"* This page answers it with numbers, not adjectives.
>
> **Status: skeleton — awaiting measured runs on real hardware (owner-gated).** The rows below
> are the plan; the `— to measure —` cells get filled from a real run on each tier. Until a cell
> has a number it stays blank rather than guessing. The qualitative picker lives in the README
> Hardware table; this is the quantitative companion.

## How to measure (reproducible)

Load the model in LM Studio/Ollama, then run one deterministic chat turn and read the reported
tokens/sec (or use `scripts/install_smoke.py` for a boot+turn baseline). Record: model + quant,
context length, first-token latency, steady tokens/sec, and whether the deep-think slot was on.
Keep the prompt fixed across tiers so the numbers compare.

## Local model throughput by VRAM

| VRAM tier | Model (quant) | First-token | Tokens/sec | Deep slot | Verdict |
|-----------|---------------|:-----------:|:----------:|:---------:|---------|
| **8 GB** (3060 / laptop) | `qwen2.5:7b` Q4 | — to measure — | — | off | — |
| **8 GB** | `llama3.1:8b` Q4 | — to measure — | — | off | — |
| **12 GB** (3080) | `qwen2.5:14b` Q4 | — to measure — | — | off | — |
| **16 GB** (4080 / 4070 Ti S) | `gemma2:27b` Q4 | — to measure — | — | one slot | — |
| **24 GB** (3090 / 4090 / 5090) | `gemma-4-31b-a4b` MoE + deep slot | — to measure — | — | on | reference |
| **CPU-only** | `qwen2.5:3b` | — to measure — | — | off | works, slow |

## Local vs hybrid, per tier

| Tier | Local-only realistic use | When to enable hybrid (cloud opt-in, per-agent) |
|------|--------------------------|--------------------------------------------------|
| 8 GB | daily chat, brief, notes, single agent | heavy synthesis / long-context research → cloud-escalate the auto-policy agents |
| 12–16 GB | most cabinet agents, one model slot | deep-think + parallel agents on the biggest tasks |
| 24 GB+ | the full reference experience | rarely needed; cloud only for the very largest jobs |

> Hybrid keeps the **local-first, key-stays-local** contract (see [`SECURITY.md`](../SECURITY.md)):
> cloud is opt-in per agent, and the `%-local` metric on the HUD reports the real split.

## Related

- README **Hardware** — the qualitative "what model should I run?" picker.
- [`docs/COMPATIBILITY.md`](COMPATIBILITY.md) — platform / provider / usage-profile matrix.
- `docs/METRICS.md` — the `%-local` north-star metric this feeds.
