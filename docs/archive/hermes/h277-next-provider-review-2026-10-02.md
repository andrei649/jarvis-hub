# Next H277 adapter investigation — read-only

Generated 2026-10-02 Europe/Bucharest. Nerva source freeze a38d7546aa7955a74746b32f1f13409944084aa1; pinned Hermes59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e. No implementation or live provider call.

Hermes tools/vision_tools.py video_analyze_tool constructs a video_url data-URL message and calls async_call_llm with task=vision. Its native Gemini adapter's _inline_data_part, however, accepts only image_url. A local AST extraction of the five pure conversion functions (_text_of, _coerce_content_to_text, _inline_data_part, _multimodal_part, _extract_multimodal_parts) reproduced omission: synthetic video_url produced only the text part, whereas image_url produced text plus inlineData. No provider/API outcome is inferred from this isolated conversion check.

Reference agent/gemini_native_adapter.py SHA256 e91ad1db89d6e1c19c7eaeab6c73892aaee232d4b07dd7b00aaf45e826263a16. This blocks using that native adapter as evidence of working video payload conversion, not the broader requirement to implement video-capable provider routes.

Next design should require direct inspection of the serialized native video body, correct MIME and payload limits, provider-specific credential header and endpoint identity, and current consent/cost/privacy policy at dispatch. Preserve existing single-route HMAC bytes and configured-chain behavior. Check official provider protocol documentation before implementing a new wire format. Do not infer video support or subscription entitlement from a configured provider name. Existing Nerva Gemini text/tool backend alone is not a video-consumer implementation.

Alternatives: extend an existing compatible endpoint (already supported, model acceptance still unverified), add a native Gemini adapter with offline body proof (new bounded implementation), or broaden shared auxiliary selection first (larger interface migration). No next implementation selected until the current frozen full suite finishes.

Official protocol read 2026-10-02:
- https://ai.google.dev/gemini-api/docs/generate-content/video-understanding documents REST `models/{model}:generateContent`, `x-goog-api-key`, inline_data containing mime_type/data, and candidate text parts. This matches the existing Nerva Gemini protocol family without an unrelated migration.
- The same page's overview permits inline inputs under100MB, while its inline section and upload guidance still say20MB. Do not claim an authoritative resolved limit from that inconsistent page. A proposed first adapter may conservatively cap the complete serialized request below20MB, naming this a local implementation bound; Files API/larger videos remain future work.
- https://ai.google.dev/gemini-api/docs/video-understanding now leads with Interactions examples. Adopting that newer API would be separate work, not necessary to copy the pinned consumer behavior.

Also review existing video MIME policy when adding native protocols: Nerva currently labels .mov/.avi/.mkv as video/mp4 in VIDEO_MIME. That accepted-extension table is not proof the container has the MP4 MIME type or that a target accepts it. The next adapter should preserve the real container MIME where supported and explicitly refuse unsupported containers, with format-specific serialized-body tests; do not claim live support from file-extension acceptance.
