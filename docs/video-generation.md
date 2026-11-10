# Video generation

Nerva can make short videos from a text prompt, animate a still image, follow reference
images (xAI), and edit or extend a video it made with xAI. The provider code is Hermes
Agent's own, adopted as it is (`docs/hermes/ADOPT_LANE.md`, "Video generation"); every
request still goes through Nerva's approvals, egress rules and media store.

## Turning it on

Video generation is off until you do two things:

1. **Set a key.** HUD → Console → Start → **Integrations** → filter **video** → open the
   provider → paste the key. Or set it in `.env`:
   - FAL: `FAL_KEY` (21 model families: Pixverse, Veo 3.1, Kling, Seedance, Wan, MiniMax, …)
   - xAI Grok Imagine: `XAI_API_KEY` (text, image and reference-guided video; edit; extend)
   - DeepInfra: `DEEPINFRA_API_KEY` (name the model, e.g. `Wan-AI/Wan2.1-T2V-1.3B`)
2. **Choose the provider.** Press **use for videos**. A consent card says what the
   provider receives (your video prompts and the images you animate), that its data
   handling is not verified, and that it bills per second. "I understand, use it" writes
   your consent to the audit log and turns the provider on (`JARVIS_VIDEO_PROVIDER`).
   **turn video off** turns it off again. You can also set `NERVA_VIDEO_PROVIDER=fal` in
   `.env` (your own edit; not audited).

It also needs what paid cloud images need: the Action Kernel on (`NERVA_ACTION_KERNEL=1`),
enforced task mediation, and a system profile with heavy features on.

**Test** on a video provider sends nothing: any video request is billed, so the first
video's approval card is the test.

## Making a video

Ask in chat ("make a 5 second video of a red fox running in snow"). The model calls the
`video_generate` tool, which is gated: nothing is sent, and you get an approval card:

- the title names the provider, the model, the seconds and **an upper-bound cost**
  ("up to $0.45");
- the card's payload shows the exact prompt and settings, and `amount` (the same cost,
  counted by the approval policy's money accounting);
- the cost is a list price where Nerva has one (xAI `grok-imagine-video`, FAL Pixverse v6,
  checked 2026-11-10) and otherwise a stated ceiling ($0.10/s for FAL's cheap tier, $0.50/s
  for premium families and DeepInfra). After the run, a price the provider reports (xAI) is
  recorded next to the estimate.

Approve it in the Decision Inbox (or with `nerva approvals`). The video runs once on the
autonomy worker. While a conversation is in plan mode the tool is refused; while the
e-stop is engaged no card is created and a running video stops at its next request.

Options the tool takes: `duration` (the provider clamps it), `aspect_ratio`, `resolution`,
`model`, `image` (animate a still: an image Nerva generated, by its id, or the provider's
own media URL), `reference_images` (xAI), `negative_prompt`, `seed` and `audio` (FAL
families that take them), and for xAI `operation: "edit" | "extend"` with
`source_task_id`, the task of an xAI video Nerva made.

## Where the video goes

The file is kept only if it is an MP4 or WebM of at most 16 MiB. It lands in the media
store and the media gallery (kind `video`); open it from the gallery or
`/api/artifacts/<id>/blob`. The task result names its catalog id and size.

## What can go wrong

- `video_provider_not_chosen` / `credential_not_configured` — step 1 or 2 above.
- `video_too_large` — the file was over 16 MiB; ask for fewer seconds or a lower
  resolution.
- `video_host_not_admitted` — the provider tried to hand the file out from a host Nerva
  does not allow for it; nothing was fetched.
- `video_timeout` — the job did not finish in 15 minutes.
- `unknown` — the request reached the provider and then something broke. Nerva never sends
  it again (it may have been billed); ask again for a new video.

## Limits

- Tested against a fake provider only; no live video was generated.
- No OpenRouter video provider (its Hermes plugin needs Hermes's own credential resolver).
- DeepInfra has no live model list in Nerva: name the model.
- FAL's 2× upscale pass and Hermes's managed (Nous subscription) FAL gateway are not used.
- A local file the model names is never read or sent; only images Nerva generated are.
