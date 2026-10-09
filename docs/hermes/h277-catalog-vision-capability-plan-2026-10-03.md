# H277 selected-main cloud vision catalog

Goal: use source-backed, exact per-model cloud vision metadata to avoid sending
images to a selected main model that is known text-only. Base/head at planning:
`5a848774` on `codex/h277-provider-discovery-20261002`, 2026-10-03.
Pinned Hermes: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`,
`agent/image_routing.py:_probe_models_dev` and
`agent/models_dev.py:_entry_supports_vision`. Current upstream schema verified
at https://models.dev/ and its public `api.json` on 2026-10-03: providers own
`models` maps, models may declare `modalities.input` and `attachment`.

Nerva's selected image route already probes LM Studio/Ollama and accepts exact
owner declarations. The remaining gap is cloud model metadata: unknown stays
eligible, so a known text-only model can still be offered image input. Add a
bounded public catalog fetch at selected image preflight only. It carries no
prompt, image or provider key. Map only Nerva's native selected adapters at
their exact canonical endpoint: Anthropic, Gemini, OpenAI Responses, xAI and
OpenRouter. An OpenRouter-compatible proxy or custom endpoint cannot borrow
OpenRouter's model verdict. Local models keep their own runtime probe.

The owner declaration wins, then local runtime metadata, then the catalog.
An explicit `modalities.input` list gives true only when it contains `image`;
otherwise use a strict `attachment` boolean if present. Missing or malformed
metadata is unknown. A known false skips the main image route before review,
letting the existing reviewed fallback resolve. No model-name heuristic or
provider-wide `vision` flag is evidence.

Fetch a fixed HTTPS URL with no redirects, proxy, cookies or credentials. Bind
method, URL and direct transport at the physical request; cap time and bytes.
Cache the parsed verdict map in process for four hours, deduplicate concurrent
loads, and back off failures. Synchronous review/physical guards read only the
cache; no hidden network call occurs there. A changed selected destination or
capability verdict invalidates the old review before image egress.

Red-first tests: canonical/provider/model isolation; modalities vs attachment;
malformed/unknown; bounded/no-redirect/direct no-key transport; cache and
failure backoff; owner precedence; selected composer false fallback and review
drift. Then focused H277/H513/settings regressions, Graft, status check and
secret scan. Non-goals: general model-picker catalog, arbitrary custom provider
catalog aliases, SDK credential recovery and live paid-provider acceptance.
Rollback is this catalog module plus its two selected-composer call sites and
tests; prior owner/local verdict paths remain intact. H277 stays partial.

Verification checkpoint (2026-10-03, local branch
`codex/h277-provider-discovery-20261002`): the focused catalog and selected
Claude tests passed (26 cases). The full backend suite completed with exit 0:
21,341 passed, 34 skipped and 1 expected failure, counted from pytest's quiet
progress output. Ruff, `git diff --check`, `scripts/hermes_status.py check`,
`graft check .` and the staged gitleaks scan passed. No frontend source changed
in this slice, and no live cloud-provider acceptance was attempted. The
catalog only covers canonical native selected routes; custom/proxy endpoints
remain unknown, and the wider H277 requirements remain open.
