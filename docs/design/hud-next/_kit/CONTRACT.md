# Mockup contract — every direction follows this

All directions draw **the same moment of the same product** so they can be compared side by side.
The brief is `BRIEF.md` (same folder); the shared content is `content.json`.

## Files (one folder per direction: `docs/design/hud-next/<slug>/`)

| File | What it is |
|---|---|
| `cockpit.html` | The home screen. Designed for 1920×1080; must reflow at 1440×900 and 1280×800 with **no horizontal page scroll**. At 1920×1080 the page itself does not scroll — inner regions may. It is also rendered at **2560×1353 at 1.5× pixel ratio — the owner's actual screen** (a maximized browser on a 31-inch 4K monitor at 150%): there the extra room must be used well. No line of text wider than a comfortable measure, no panel stretched to fill, no dead quarter of the screen. |
| `secondary.html` | The Trust Center, in the same design language (proves the system generalises to a dense, safety-critical screen). |
| `tokens.css` | The direction's tokens — colour, type, space, radius, elevation, motion — as CSS custom properties. Both pages link it. |
| `README.md` | The concept note (see the brief for its sections). |
| `shots/` | Written by the render tool. Do not hand-edit. |

## Rules

- **Self-contained.** No network requests of any kind: no CDN, no web fonts, no remote images. The
  render tool aborts every non-local request and lists it as a failure.
- **Plain HTML + CSS.** JavaScript only for small behaviours (theme switch, a tab, a disclosure).
  No frameworks, no build step, no generated bundles.
- **Themes — both are required.** Honour `?theme=dark|light` by setting `data-theme` on `<html>` in
  an inline script in `<head>`, before first paint. With no parameter the page shows the theme
  your direction declares as its default. Every page carries
  `<meta name="nerva-themes" content="dark light">`; the render tool then shoots both. Both themes
  come from the same token names in `tokens.css` — a light theme that is an inversion or an
  afterthought counts against the direction.
- **Content is inlined.** Write the content into the HTML (or a local `<script>` data file in your
  folder). Do not `fetch()` `content.json` at runtime: file pages cannot fetch files.
- **Fonts — only what renders here without downloading anything:**
  - the brand faces the product already vendors, via `<link rel="stylesheet" href="../_kit/fonts.css">`:
    **Space Grotesk** (300–700) and **JetBrains Mono** (100–800), with Romanian coverage;
  - fonts installed on this Windows machine: **Segoe UI Variable** (optical sizes: `Segoe UI
    Variable Display` / `Text` / `Small`), **Bahnschrift** (variable weight and width, DIN-like),
    **Sitka** (variable serif with optical sizes: `Sitka Small` / `Text` / `Subheading` / `Heading`
    / `Display` / `Banner`), Georgia, Cambria, Constantia, **Cascadia Code** / **Cascadia Mono**,
    Consolas, Source Code Pro.
  - If the concept would ship a different open-licence typeface in production, render with the
    closest installed stand-in and name both in the README. The product is local-first: any
    production typeface must be self-hostable under an open licence.
- **Content.** Use `content.json` verbatim for names, labels and numbers. Do not invent product
  concepts that are not in it or in the brief.
- **Legibility floor.** No text below 11px anywhere. Body text ≥ 14px. Secondary text ≥ 12px.
- **Contrast.** Zero axe colour-contrast failures (WCAG 2.x AA) in every theme you ship.
- **Motion.** None is required. If you animate: respect `prefers-reduced-motion`, and do not use
  large blurred areas or continuously running animation — the same GPU is running a local LLM.
- **Icons.** Inline SVG you draw yourself (simple strokes). No icon fonts, no emoji as icons.
- **Logo.** `../_kit/nerva-mark.svg` is the real mark (the "neural N"). Use it or restyle it; do not
  invent a different logo.

## Rendering and the gates

```
node "<kit>/tools/shootset.mjs" "<your folder>"            # full matrix
node "<kit>/tools/shootset.mjs" "<your folder>" --quick    # 1920 dark only, for the inner loop
```

The tool writes `shots/<page>-<width>-<theme>.png` and `shots/report.json` and prints one line per
shot. A direction is **not finished** until every line shows:

- `OK`, no JS errors, no blocked external requests, no `FONTS NOT INSTALLED`;
- a `light` line for every page;
- `smallest` ≥ 11px and `<11px 0`;
- `hOverflow no` at 2560, 1920, 1440 and 1280;
- `vOverflow 0px` for `cockpit@1920` and `cockpit@2560`;
- `contrast fails 0` in each theme.

Then open every PNG and look at it. Passing the gates is the floor, not the goal.
