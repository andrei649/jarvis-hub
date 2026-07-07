# LivingMemory Recall Eval Design

## Goal

Make the existing LivingMemory algorithm layer influence live recall without storing raw transcript text, and add a deterministic eval mode that exercises the real `MemoryManager.remember()` and `MemoryManager.recall()` path.

## Non-Goals

- Do not add new automatic memory capture beyond the O26-P2.2 turn seam.
- Do not store raw user/assistant transcript text in LivingMemory records.
- Do not generate answers from LivingMemory hashes or metadata alone.
- Do not change RRF fusion internals; temporal-context memory is a post-fusion ranking hint.

## Design

Add a focused helper under `agents/core/memory/living_recall.py`. It accepts already-fused recall hits plus the cognition `LivingMemory` module, indexes LivingMemory records by `turn_ref`, and reorders only hits whose ids match known LivingMemory turn references. It uses the existing `tcm_rerank()` function, annotates matched hit payloads with non-private `living_memory` metadata, and leaves unmatched/no-module results in their original order.

Wire `Orchestrator._recall_block()` to call the helper after `MemoryManager.recall()` and before `rag_guard.wrap_memory()`. This preserves the existing prompt-safety boundary: LivingMemory can influence which already-retrieved facts appear first, but all retrieved text still flows through the RAG guard as data, not instructions.

Extend `agents/core/memory/eval.py` with an async `run_recall_eval()` mode. Each case ingests its facts into a real `MemoryManager` configured with deterministic hash embeddings, recalls against the case question, then runs the existing keyword answerer only over retrieved fact text. The endpoint `/api/memory/eval/run` gains a `mode=keyword|recall` query parameter, defaulting to the current keyword baseline.

## Risks

- Hash embeddings are deterministic but not semantic; the eval mode is a real-path smoke/evidence gate, not a claim of model-quality recall.
- LivingMemory records currently carry metadata only. That is intentional; the helper must never synthesize recall snippets from those records.

## Tests

- Pure helper tests prove LivingMemory temporal context reorders matching hits and preserves unmatched results.
- Orchestrator test proves `_recall_block()` renders the re-ranked order while keeping `rag_guard` fencing.
- Eval tests prove `run_recall_eval()` uses the real recall path and the API mode returns the new report.
