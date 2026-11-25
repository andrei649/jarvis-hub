# HUD v2 Fonts

Vendored Latin-variable WOFF2 slices used by `frontend/src/styles.css`:

- `space-grotesk-latin-var.woff2` from Google Fonts, family `Space Grotesk`, weight range 300-700.
- `jetbrains-mono-latin-var.woff2` from Google Fonts, family `JetBrains Mono`, weight range 100-800.

Both families are distributed under the SIL Open Font License. The HUD ships these local assets so
`/v2` keeps its branded type stack without runtime font-network dependency.

## Latin Extended slices (Nerva Workspace)

The Latin slices above do not cover Romanian: ă (U+0103), ș (U+0219) and ț (U+021B) live in
Latin Extended-A/B (â and î are plain Latin-1 and are covered). Nerva Workspace
(`frontend/src/workspace/workspace.css`) therefore also vendors the matching **latin-ext**
slices, from the same Google Fonts families and under the same SIL Open Font License:

- `space-grotesk-latin-ext-var.woff2` — `Space Grotesk`, latin-ext subset, weight range 300-700.
- `jetbrains-mono-latin-ext-var.woff2` — `JetBrains Mono`, latin-ext subset, weight range 100-800.

Each slice is declared in its own `@font-face` with the subset's `unicode-range`, so a browser
downloads the latin-ext file only when a page actually contains such a character. Vite copies all
four files into `agents/web/workspace/assets/` with a content hash in the name; the hub serves them
from `/workspace/assets/` as `font/woff2`, which the shell's `font-src 'self'` allows.

The HUD declares the same latin-ext slices in `frontend/src/theme/fonts.css` (2026-11-23), so
Romanian text in the HUD never falls back either.

## Ledger faces (HUD themes, 2026-11-23)

The Ledger design (`docs/BRAND_BOOK.md` §7.4) sets what Nerva writes in **Literata** and the
instrument in **Barlow**. Both are vendored here, latin and latin-ext slices only, and declared in
`frontend/src/theme/fonts.css`. Source: the Fontsource npm packages, which repackage the Google
Fonts builds unchanged; both families are under the SIL Open Font License 1.1, whose text ships
beside the files (`OFL-Literata.txt`, `OFL-Barlow.txt`).

- `literata-{latin,latin-ext}-opsz-{normal,italic}.woff2` — from `@fontsource-variable/literata`
  5.3.0 (Google Fonts v40). Variable: weight 200–900 and optical size 7–72, so titles and verdicts
  get their display cut automatically (`font-optical-sizing: auto`). Copyright 2017 The Literata
  Project Authors.
- `barlow-{latin,latin-ext}-{300,400,500,600,700}-normal.woff2` — from `@fontsource/barlow`
  5.3.0. Static weights 300–700, upright only (italics are not used by the instrument; a browser
  would synthesise one). Copyright 2017 The Barlow Project Authors.

Together they add about 575 KB, and a browser fetches a slice only when a page uses that face,
weight, style and character range. Barlow Semi Condensed, which the Threshold theme uses for
labels, titles and figures and the Console theme for its interface face, is not vendored: those
roles render in the next face of their stacks, Bahnschrift SemiCondensed on Windows and the
system sans elsewhere. Briefing's interface face, Source Sans 3, is not vendored either (stand-in
Segoe UI Variable).
