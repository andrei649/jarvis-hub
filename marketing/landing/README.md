# Jarvis Hub landing page

Static, self-contained dev half for O26-P3.6 / M3.3.

Open `index.html` directly in a browser, or serve the `marketing/landing/` folder from any static
host. No external scripts, stylesheets, fonts, images, or API calls are required; the page is safe
to preview offline and stays outside the HUD build pipeline.

## Source material

- Copy spine: `docs/marketing/TEASER_PACK.md`
- Launch language: `docs/marketing/ANNOUNCEMENT.md`
- Visual tokens and voice: `docs/BRAND_BOOK.md`
- Capture checklist: `demo-shot-list.md`, distilled from `docs/marketing/TEASER_PACK.md` section 6

## Scope

This branch supplies the landing surface and demo capture support. The owner records the actual
video in M4 using real HUD data or clearly badged demo mode.

## Contract

The test `tests/test_o26_p3_6_landing_page.py` pins the important promises:

- self-contained HTML only;
- canonical Brand Book tokens;
- no stale proof-point numbers copied from older marketing docs;
- demo shot-list support present beside the page.
