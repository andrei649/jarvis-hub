# LivingMemory Duplicate Gate Design

**Goal:** Stop exact duplicate completed chat turns from creating another LivingMemory tier record and decay entry.

**Non-goals:** No semantic similarity model, no reflection-hand-off change, no endpoint or HUD change, and no deletion of existing records.

## Context

The H21.3/O26 memory seam now records completed LLM turns into LivingMemory with metadata only: session, agent, channel, turn reference, digest, character counts, and timestamp. That preserves privacy, but the hot seam still passes `surprise=1.0` for every completed turn. Repeating the exact same user/assistant turn therefore creates another memory and decay entry even though the predictive-coding gate already has a concept of low-surprise inputs.

## Approach

Add a small `LivingMemory.has_text_digest(text_sha256, prefix="turn:", limit=1000)` helper that scans recent metadata records for the existing digest. The orchestrator turn seam will compute the digest as it does today, ask LivingMemory whether it has already seen it, and map exact duplicates to `surprise=0.0` / `novelty=0.0`.

When `LivingMemory.encode()` rejects that duplicate through the existing surprise threshold, the orchestrator records `last_living_memory_record` with `reason="duplicate_turn_digest"` and does not add a decay entry. First sightings keep the current `surprise=1.0` behavior.

## Risks

The scan is bounded to recent turn records, so very old duplicates outside the limit can still encode. That is acceptable for this slice because it prevents repeated-turn echo without making memory lookup an expensive global operation.

## Tests

- Pure LivingMemory test for digest lookup over metadata-only tier records.
- Golden-loop regression proving two identical completed turns create one tier record and one decay record, with the second turn reported as `duplicate_turn_digest`.

## Rollback

Remove the helper, restore constant `surprise=1.0` in `_record_living_memory_after_turn`, and remove the two regression tests.
