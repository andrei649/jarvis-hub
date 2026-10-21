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
