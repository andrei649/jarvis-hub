# P26: real Ollama raw-stream evidence

The Ollama serving-layer limb of P26 passed on 2026-09-09. The unmodified
`OllamaBackend.generate_stream` consumed a real local response, returned the
existing `THINKING_EXHAUSTED_REPLY`, and invoked the user-token callback zero
times. No production source changed for this proof.

| Measurement | Observed |
|---|---|
| Serving layer / installed model | Ollama 0.33.3 / `qwen3.5:0.8b` |
| Local endpoint | `http://127.0.0.1:11434/api/generate` |
| Synthetic prompt | `Calculate 17 multiplied by 23.` |
| Controls | `stream=true`, `think=true`, `num_predict=8`, `num_ctx=2048`, temperature 0, `keep_alive=0` |
| Raw response | 1,123 bytes, seven NDJSON records |
| Finish | `done=true`, `done_reason=length`, `eval_count=8` |
| Reasoning / visible response | 25 / 0 characters |
| User-token callback / returned reply | 0 calls / the named degraded reply |
| Wall time | 7.031 seconds, including model load |
| Resident models before / after | None / none; explicit cleanup returned `done_reason=unload` |

The raw response body is retained byte-for-byte in
[`ollama-generate.ndjson`](ollama-generate.ndjson). Its SHA-256 is
`c5a3026db1b528df81e57a016f53143d643bbcbd727d24e8f1df251fa90b869e`.
[`evidence.json`](evidence.json) records the request, installed model digest,
timestamps, measurements, final user reply and unload confirmation. The raw
capture contains only model output for the synthetic arithmetic prompt.
The reader-source SHA-256 in this original evidence was subsequently calculated
from the exact `agents/core/llm/base.py` blob at the recorded `d0a729f8` commit;
the capture, timestamp and measurements were not regenerated. Future live runs
record the current checkout HEAD, the actual reader-file hash, and whether that
file differs from HEAD; a dirty reader is not represented as commit-only proof.
The source must remain unchanged between import and completion. This identifies
the reader file, not every dependency in the running environment.

The capture transport changes only three request controls that the backend method
does not expose: `keep_alive=0`, `think=true`, and `num_ctx=2048`. It forwards the
request to the real loopback server and tees response bytes without changing them.
There is no response shim, fabricated `thinking` field, or serving-layer mock in
the live run. The backend's production HTTP-client wrapper is replaced by this
capture transport, so this proves the real wire and reader, not HTTP-egress policy
or a complete running-hub turn.

To replay the exact saved bytes offline through the current backend reader:

```powershell
python docs/qa-runs/2026-09-09-p26-ollama-stream/capture.py
```

An explicit `--live` captures one new bounded generation using the already
installed model; it refuses if any model is resident and does not install or
download anything. The default command never contacts Ollama.

P26 remains **open**. This small-budget arithmetic probe does not prove LM Studio
SSE behavior, other Ollama/model versions, long real reasoning latency, exclusion
of the warning from later memory recall, or the cloud context-window limb. The
known inline-`<think>` serving-layer gap is unchanged.

Freshness: goal was the Ollama raw-stream limb; base and tested head
`d0a729f846e08c7fb3d35180a31050316c8439c1`; branch
`codex/hermes-p26-ollama-stream`; captured 2026-09-09 12:02:37 UTC. Changed paths
are this evidence directory, `docs/OWNER_TASKS.md`, and the HA-5c BACKLOG row.
Next action at capture time: independent evidence review, then integrate this documentation-only
proof unit. Rollback is a revert of that unit; no runtime or data migration.
