# H277 local auxiliary evidence impact audit

Read-only audit against base `614602123902391ccb5b30ba21c4ce900147b9c6`. I validated **all evidence pins on each candidate row** against the base tree, then required the `orchestrator.py` / `FLAGS.md` pin itself to match the base blob. This leaves 21 previously-current reviewed rows; rows with any old citation mismatch were excluded. The validated base blob hashes are in `evidence-audit.json`. The live working tree was not used as the historical source.

The four changed orchestrator call sites are `_session_titler` (orchestrator.py:2941-2955), `_query_rewriter` (:2957-2976), `_review_llm` (:3511-3527), and `_compression_summarizer` (:3745-3774). The new `generate_local_auxiliary` reads a task-specific local model, rejects job pins, preserves Qwen3 title/rewrite prompting, and holds `auxiliary_request_scope` across generation or compression streaming (auxiliary_text.py:19-62). FLAGS adds the four variables and their limits (docs/FLAGS.md:695-717).

Six of the 21 rows need a targeted evidence/content update; fifteen retain their existing claim text because their cited behavior is outside those four call sites. “Preserve” means preserve the existing reviewed claim, not silently refresh its whole-file hash.

| Row | Impact and recommendation |
|---|---|
| H277 | Rewrite only the residual that says shared task-aware auxiliary routing remains unfinished. Four consumers now have that routing; broader adapters, discovery and recovery remain open. Preserve the video/role claims and their historical mutation receipts. |
| H413 | `_session_titler` now permits a task-specific model override. Preserve title lifecycle, local-only dispatch, output/token/Qwen/job-pin behavior; rewrite the model-selection detail to describe override plus old fallback. |
| H433 | `_query_rewriter` now permits its task-specific model override. Preserve prompt/filter/96-token/temperature behavior; rewrite only the model-selection detail. |
| H465 | `_review_llm` now permits its task-specific model override. Preserve bounded review settings and strict-local policy; rewrite the model-selection sentence to name the override while retaining the JSON/temperature/token contract. |
| H513 | The auxiliary integration path now routes through the common helper, which still wraps the selected local backend/model in `auxiliary_request_scope`. Preserve H513 consent and policy semantics; add the helper/new test as evidence for this integration and avoid implying active-model-only selection. |
| H674 | `_compression_summarizer` now calls the common helper, which calls `stream_summary` inside the same auxiliary policy scope and passes the same inactivity value. Preserve hold, streaming, cancellation and digest claims; update only model-selection detail. |

The other current rows’ claims point to separate symbols and tests: H182 turn power holds; H227 inspector core-block rendering; H328 skill prompt catalog; H329 skill switches; H398 taint propagation; H428 recall gates/timeouts/warm context; H441 recap trail storage/rendering; H487 approval/chat outcome state; H579 attached context references; H659 idempotency; H667 sandbox cache path; H670 identity prompt versioning; H671 session birth/clock publication; H677 startup/shutdown budgets; H679 reasoning vocabulary. The changed methods do not implement those claims. Preserve their prose and defer any whole-file citation refresh until claim-specific verification; do not restamp them merely because the orchestrator blob changed.

The focused test union for the directly affected runtime claims is `tests/test_h277_local_auxiliary.py`, `tests/test_h413_session_titles.py`, `tests/test_recall_gate.py`, `tests/test_query_rewrite.py`, `tests/test_h465_refine.py`, `tests/test_h465c_refine_review.py`, `tests/test_h465d_refine_review.py`, `tests/test_h465e_refine_review.py`, `tests/test_h465f_refine_review.py`, `tests/test_h465g_refine_review.py`, `tests/test_h674_compaction_hold.py`, `tests/test_h513_auxiliary_policy.py`, and `tests/test_h513_auxiliary_integration.py`. This is a recommended verification union, not a claim that it was run.

No tests were run. No assessment row was edited or restamped. This is evidence-drift triage, not runtime acceptance.

## Integration verification protocol

The coordinator independently checked all pins against the previously verified
base and compared orchestrator methods structurally: only the four named producer
methods changed. Six initially proposed rows were excluded because other evidence
was already stale: H262,H298,H315,H594,H681 and H490. The original207 stale rows
remain untouched. Moved citations are accepted only when anchored text matches;
the edited H433/H674 call sites are mapped to the new helper explicitly.

The final integration receipt records the full-suite outcome and per-cited-module
counts before any restamp. Legacy console tools have a separate40-case result;
frontend acceptance remains tied to its unchanged source snapshot. No capability
status is promoted by this review.
