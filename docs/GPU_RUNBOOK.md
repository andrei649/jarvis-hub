# GPU Runbook — the last two scope-1.0 items (H12.14 & H13.3)

These are the only two `scope-1.0` items not buildable/verifiable in-sandbox
(194/196 done). Both are **GPU/host-deployment** steps — no application code to
write. The software they plug into already exists; this runbook makes them
turnkey when you're on real hardware.

| Item | What | Needs | Software already in place |
|------|------|-------|---------------------------|
| **H12.14** | Small fine-tuned agentic model (task router / tool-caller), $0 COGS | 1× GPU (≥16 GB for a 4B SFT/LoRA), the SFT/GRPO pipeline | `training/sft_grpo.py`, `training/prepare_data.py` (H11.3); `HybridRouter` local tier |
| **H13.3** | Speculative decoding (draft → target), 1.5–2.5× interactive throughput, **output-identical** | 1× GPU with VRAM for target+draft, vLLM or llama.cpp | `HybridRouter` deep tier (`JARVIS_DEEP_MODEL`); VLM/OpenAI-compatible backends |

---

## H12.14 — Fine-tune the agentic model

### 1. Export an SFT dataset from the learning logs
The H7.11 learning loop writes one trace per interaction to
`memory_logs/learning/<agent>.jsonl` (`task` / `response` / `success`).
`prepare_data.py` turns successful traces into ShareGPT-style SFT examples:

```bash
# only successful traces (success → score 1.0); writes ShareGPT messages JSONL
python training/prepare_data.py memory_logs/learning/*.jsonl --min-score 1.0 -o sft.jsonl
# -> "Wrote N SFT examples to sft.jsonl"
```

Curate `sft.jsonl` before training (dedupe, spot-check, drop anything sensitive —
the file is plaintext conversations). A few thousand high-quality examples beats
a noisy dump. For tool-routing specifically, bias toward traces where the agent
picked the right tool/route (`route_name` in the records).

### 2. Train (GPU host)
```bash
pip install 'trl' 'transformers' 'datasets' 'peft' 'accelerate' torch
python training/sft_grpo.py --data sft.jsonl --model Qwen/Qwen3-4B --out ./ft-jarvis --epochs 1
```
`sft_grpo.py` runs supervised fine-tuning (TRL `SFTTrainer`) and saves to
`./ft-jarvis`. Imports are guarded, so it fails with a clear message if the GPU
deps are missing. For a LoRA adapter (smaller, mergeable) add `peft` config; for
the GRPO/preference stage, feed back scored rollouts (same `prepare_data` score
field) — left as the next iteration once SFT lands.

### 3. Serve it locally and point the router at it
Convert to GGUF and register with Ollama (the router's local tier speaks the
`name:tag` convention, e.g. `qwen3:7b`):

```bash
# (after llama.cpp convert+quantize to ./ft-jarvis.gguf)
printf 'FROM ./ft-jarvis.gguf\n' > Modelfile
ollama create jarvis-agentic -f Modelfile     # serves on http://localhost:11434
```

Then make the router use it as the **default local model** — either:
- admin setting `default_model = "jarvis-agentic"` (HUD admin → model settings, read by `HybridRouter._admin_setting("default_model", …)`), **or**
- replace the Howard tier: set `HOWARD_OLLAMA_MODEL` to your model (served at `HOWARD_OLLAMA_URL`, default `http://localhost:11434`).

### 4. Verify
```bash
ollama run jarvis-agentic "Route: 'remind me to call mom at 6pm' — which tool?"
```
Confirm it returns the right tool/route, then exercise it through the HUD and
watch new `memory_logs/learning/*.jsonl` traces flip to `success: true`. Mark
**H12.14 ✅** in `BACKLOG.md`.

---

## H13.3 — Speculative decoding

Output is **identical** to the target model — this is a throughput/latency win,
not a behavior change, so there is **no application code to touch**. You enable
it in the local inference server and point the router's deep tier at that
endpoint.

### Option A — vLLM
```bash
pip install vllm
vllm serve Qwen/Qwen3-32B \
  --speculative-config '{"model": "Qwen/Qwen3-4B", "num_speculative_tokens": 5}' \
  --port 8001
```
(Older vLLM: `--speculative-model Qwen/Qwen3-4B --num-speculative-tokens 5`.)
Pick a draft model from the **same tokenizer family** as the target (Qwen draft
for a Qwen target; for `gpt-oss` use a small gpt-oss/compatible draft).

### Option B — llama.cpp
```bash
llama-server -m qwen3-32b.gguf -md qwen3-4b-draft.gguf \
  --draft-max 16 --draft-min 4 --port 8001
```

### Point the router / VLM backend at it
Both servers expose an **OpenAI-compatible** API, which the existing backends
already speak:
```bash
export JARVIS_DEEP_MODEL="Qwen/Qwen3-32B"   # deep tier model name
# point the deep/VLM backend base_url at http://localhost:8001/v1
# (e.g. JARVIS_VLM_URL=http://localhost:8001/v1 for the vision path, or the
#  deep-tier base_url in the hybrid router config)
```

### Verify (the key acceptance check)
1. **Output identity** — same prompt, greedy decode (`temperature 0`), with and
   without the draft model → **identical** tokens.
2. **Speedup** — measure tokens/sec both ways; expect **1.5–2.5×** on
   interactive (low-batch) loads. If throughput *drops*, the draft acceptance
   rate is too low → try a smaller/closer draft or fewer speculative tokens.

Mark **H13.3 ✅** once output-identity holds and you see the speedup.

---

## H22.4 — Ollama concurrency & keep-warm (server-side tuning)

> These are **Ollama server** environment variables, set where `ollama serve`
> runs (the host), not in jarvis code — jarvis connects to Ollama, it doesn't
> launch it. Pair with the startup warm-up jarvis already does (`JARVIS_LLM_WARMUP`,
> BACKLOG H22.2). **Validate on the GPU box** — effects can't be measured in CI.

Set in the Ollama service env (e.g. `~/.ollama` / systemd drop-in / shell that
starts `ollama serve`):

```bash
export OLLAMA_NUM_PARALLEL=2        # 2–4: interleave concurrent requests on one
                                    # loaded model (default 1 = serial/head-of-line).
                                    # RAM scales ~ NUM_PARALLEL × context.
export OLLAMA_KEEP_ALIVE=-1         # keep the model resident (no 5m unload).
export OLLAMA_FLASH_ATTENTION=1     # enables KV-cache quant; gate per-model.
export OLLAMA_KV_CACHE_TYPE=q8_0    # ~½ KV memory vs f16 (needs flash-attn on).
```

### Verify
1. **Concurrency** — fire two chat requests at the same loaded model; with
   `NUM_PARALLEL=1` they serialize, with `2` they overlap (watch tokens/sec and
   wall-clock of the pair).
2. **Warm start** — first turn after boot should skip the cold-load (the jarvis
   warm-up + `KEEP_ALIVE=-1` keep it resident).
3. **Flash-attn / KV quant** — confirm no quality regression or crashes on your
   specific model (known crash reports on some architectures — keep an allowlist).

Mark **H22.4 ✅** once concurrent requests overlap and the model stays warm.

---

## Notes
- Both items are **$0 incremental COGS** — they run on local hardware you already
  provision for the strict-local tier (H13.1/H13.4).
- Neither runs in CI (no GPU runner); that's expected and why they sit at the
  `194/196` line. Everything upstream of them (the SFT pipeline, the router
  tiers, the OpenAI/VLM backends) is built and offline-tested.
- After either lands, bump the `BACKLOG.md` "Status General" tables and the
  scope-1.0 total accordingly.
