# Footage runbook — capturing the TEASER_PACK shot list

**Purpose.** Turn `docs/marketing/TEASER_PACK.md` §6 (the six-shot asset list) into actual
video, off the real product, repeatably, without anyone having to remember which panel
lives behind which keystroke.

**The rule this whole runbook exists to keep.** From the shot list itself:

> Reuse rule: never stage fake data for a shot. Demo mode is clearly badged; use it, or use
> real data. The honesty *is* the marketing.

That rule is enforced, not just written down. `frontend/e2e/footage.spec.ts` accepts exactly
two sources — `live` and `demo` — and asserts the difference in both directions: a demo clip
must have the amber `DEMO DATA — seeded sample, not your live backend` banner visible on
screen, and a live clip must not. A third source fails at collection with a message naming
both. The specs never write app state; they navigate and wait. There is no seam for feeding
the HUD a prettier corpus, and that is deliberate.

---

## Run it

```bash
# once: the bundle is the thing being filmed
cd frontend && npm ci && npm run build && cd ..

node scripts/hud_footage.mjs                      # real data, 6s per shot
node scripts/hud_footage.mjs --source demo        # seeded corpus, banner in frame
node scripts/hud_footage.mjs --seconds 12         # longer takes
node scripts/hud_footage.mjs --shot trust-center  # re-shoot one
```

Playwright boots the real backend itself (`serve.py` on `E2E_PORT`, default 8123), so no hub
needs to be running. Clips land in `frontend/e2e/artifacts/footage/` — gitignored, 1920×1080
`.webm`, one per shot, plus `manifest.json` recording what was filmed, from which source,
and the exit code of the run.

`FOOTAGE=1` is what makes the `footage` Playwright project exist at all; the runner sets it.
Every other project carries `testIgnore: /footage\.spec\.ts$/`, so `npm run e2e`, the PR lane
and the nightly soak never record video even if the flag leaks into their environment.

## The shots

| id | surface | §6 | reached by |
| --- | --- | --- | --- |
| `hero` | cockpit at rest, Neural Mesh alive | 1 | boot surface |
| `trust-center` | audit chain + %-local meter | 2 | palette → *Trust Center* |
| `governed-autonomy` | the approval queue beside its task | 3 | palette → *Autonomy* |
| `morning-brief` | research queue + daily digest | 4 | palette → *Knowledge* |
| `strict-local` | local-only family space, Frigga badge | 5 | palette → *Family · local* |

Navigation goes through the command palette rather than the number keys, because palette
command names are hardcoded English in `shell.tsx` and therefore survive a language toggle;
and the spec proves navigation happened by watching the active rail button change, rather
than by pinning the order of `MODES` — so re-ordering the rail does not silently mis-shoot.

### §6.6, the WorldView globe — not in this lane

The shot list marks it optional; this script cannot produce it honestly. WorldView is a
separate surface with its own server (`worldview/`), not something the hub backend serves, so
a clip captured here would be named `worldview.webm` and contain something that is not
WorldView. Capture it from WorldView's own dev server, or cut the "and more" beat without it.

### §6.3, the Telegram half — a device capture

The approve/reject card lives on a phone. `governed-autonomy` films the HUD half: the queue
and the task it gates. The card itself is a screen recording from a real device, taken beside
the same task. Do not composite a mock card onto the HUD clip — that is staging under a
different name.

## Choosing a source

**`live` is the default and the better shot when the machine has real work on it.** A live
clip is proof: it shows this build, this data, this moment. Its cost is that a surface with
nothing in it films as an empty state — the modes gate their content honestly (`ModeEmpty`
until that mode's source is live), so a fresh install produces five clips of empty panels.
That is the product telling the truth, not a bug in the capture.

**`demo` is the honest alternative when you need a full-looking surface.** It seeds the same
corpus the HUD ships for evaluation, and it puts the amber banner across the top. Keep the
banner in frame when you cut. A demo clip with the badge cropped out is exactly the staged
screenshot the reuse rule forbids, and no automated check can catch it after the fact — that
one is on the editor.

If you want live footage that is also full, the answer is to give the machine real work
before filming, not to reach for a third source.

## Post

- Clips are silent and uncut, six seconds by default; the motion in them (mesh, ticker,
  clock) is the product's own.
- Crop and trim freely. Do not composite data that was not on screen.
- Re-shoot rather than retouch: `--shot <id>` is cheap.
- `manifest.json` carries the source for every clip. If you hand clips to someone else,
  hand them the manifest too — it is the only record of which of the two sources they are.

## When a shot fails

The spec fails loudly rather than saving a bad clip:

- **`the mode never changed`** — the palette entry name in `SHOTS` no longer matches
  `shell.tsx`. Fix the name in the spec; the shot list is the source of truth for *what* is
  filmed, `shell.tsx` for *how* to reach it.
- **`live footage must not secretly be demo footage`** — a `?demo=1` leaked into the URL, or
  demo mode became sticky. Do not work around it; a live clip that is really demo is the
  failure this assertion exists for.
- **`demo footage must carry the demo badge in frame`** — the banner was made dismissable,
  conditional or subtler. That is a product decision with a marketing consequence; make it
  deliberately, then update this runbook.
- **`is empty — the recorder produced no frames`** — the page closed before the encoder
  flushed, usually a crashed browser. Re-run the single shot.
