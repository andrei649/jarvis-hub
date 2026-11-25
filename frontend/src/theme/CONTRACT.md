# Nerva theme contract v1

Owner decision, 2026-11-23: the HUD moves to the **Ledger** design (docs/design/hud-next/ledger/)
as its default, every screen is restyled in that language, and the seven designed directions
ship as **themes** the owner can switch in Settings → Personalisation, each with a dark and a
light scheme. The HUD v2 looks stay available as **Classic** (Obsidian, Graphite).

A theme changes the visual language — colour, typefaces, type scale, shape, density and how a
panel is drawn. It never changes structure, copy, routes or behaviour. Structure is one
(Ledger's information architecture, built in a later phase); themes are skins on it.

This file is the shared interface for everyone working on the theme system. Read it fully
before editing anything under `frontend/src/theme/`, `frontend/src/styles.css`,
`frontend/src/appearance.ts` or a theme-aware component.

## 1. Files and layering

| File | Holds | Load order |
|---|---|---|
| `src/styles.css` | HUD v2 stylesheet: legacy tokens (`--void`, `--ink`, `--accent`, …) and every legacy component rule | 1 |
| `src/theme/fonts.css` | The latin-ext slices of the vendored faces (Space Grotesk, JetBrains Mono), so Romanian ă ș ț â î never fall back; `styles.css` keeps its two pinned latin `@font-face` blocks | 2 (first in `index.css`) |
| `src/theme/tokens.css` | Canonical `--n-*` tokens: theme-independent scales + Ledger · Carbon fallbacks for every colour role | 2 |
| `src/theme/themes/<id>.css` | One file per Nerva theme: its `--n-*` values for dark and light | 3 |
| `src/theme/bridge.css` | Maps legacy ⇄ canonical tokens, base element styles, decoration switches | 4 |
| `src/theme/overrides.css` | Owner axes: density, motion, font override | 5 |
| `src/theme/kit.css` | Canonical component classes (`.n-*`) used by the panel kit and new components | 6 |
| `src/theme/index.css` | `@import`s 2–6 in order; imported once from `main.tsx` after `styles.css` | — |
| `src/theme/registry.ts` | Theme ids, names (en/ro), taglines, schemes, `resolveScheme()` | — |
| `src/theme/apply.ts` | Mirrors appearance onto `<html>` before first paint and on change | — |
| `src/theme/appearance-context.tsx` | `AppearanceProvider` / `useAppearanceContext()` (§7) | — |
| `src/theme/type.ts` | Inline-style helpers: `fs()`, `stepFromPx()`, `LABEL`, `MONO`, `PROSE` (§4–5) | — |

Never define a `--n-*` colour role outside `tokens.css` and `themes/*.css` (and the Classic
block in `bridge.css`). Components consume roles; they never set them.

## 2. Selectors

The active theme is chosen by attributes on `<html>`:

| Attribute | Values | Set by |
|---|---|---|
| `data-look` | a `ThemeId` (`ledger`, `presence`, `briefing`, `workbench`, `threshold`, `console`, `atlas`, `obsidian`, `graphite`) | `apply.ts` |
| `data-scheme` | the **resolved** scheme, `dark` or `light` (never `system`) | `apply.ts` |
| `data-font`, `data-density`, `data-motion` | the existing appearance values | `apply.ts` |

`.hud-root` keeps carrying its existing `data-*` attributes (tests rely on them) plus
`data-scheme`.

A theme file uses exactly these two selectors for its roles:

```css
:is(:root, .n-theme-scope)[data-look="<id>"]                      { /* dark (or the theme's base) */ }
:is(:root, .n-theme-scope)[data-look="<id>"][data-scheme="light"] { /* light */ }
```

`.n-theme-scope` lets any element preview a theme live (Personalisation's theme cards):
`<div class="n-theme-scope" data-look="atlas" data-scheme="light">…</div>` renders its
children in Atlas · light whatever the page theme is. A theme whose default scheme is light
(Briefing) still puts its **dark** values in the first block and its light values in the
second; `registry.ts` says which one `system` falls back to.

Breakpoint overrides (for example Ledger's larger reading sizes at ≥ 2200 px) go in an
`@media` block with the selector `:root[data-look="<id>"]`.

## 3. Roles

All names and fallback values are in `tokens.css`. Meaning, in short:

- **Grounds**: `bg` page · `bg-2` hover / quiet fill · `bg-3` pressed / selected / meter track ·
  `sheet` a raised surface (card, input, the signing sheet) · `sheet-2` nested raised ·
  `scrim` the backdrop behind a modal (may carry alpha).
- **Ink**: `text` · `text-2` secondary, navigation at rest · `text-3` meta and labels. All three
  must reach 4.5:1 — unlike the legacy `--ink-3`, `--n-text-3` is readable text.
- **Rules**: `rule` hairline · `rule-2` table heads, quiet control edges · `rule-field` an edge
  that identifies a control (≥ 3:1) · `rule-heavy` the rule that opens a register.
- **Accent** — the theme's one colour: `accent` (fills, outlines) · `accent-text` (text, ≥ 4.5:1)
  · `accent-wash` (soft surface) · `on-accent` (text on a solid accent). What the accent means is
  the theme's identity: in Ledger it is the owner's hand (signatures, approvals, the stop).
- **Stop**: `stop` / `on-stop` — the emergency stop. Ledger uses its seal; others use a red.
- **Status**: `ok` · `warn` · `bad` · `info` · `cloud` (a run that left the machine) and
  `ok-wash` · `warn-wash` · `bad-wash`. Status is always paired with a word or a shape in new
  components; the hues exist so legacy screens keep working — legends, health rings, the
  locality bar and meters still encode by hue. So a theme may keep its status colours quiet
  (low chroma), but **the five must stay apart from each other and from `text`**: OKLab
  distance ≥ 0.05 between any two of them and between each and `text` (the contract test
  checks it).
- **Interaction**: `focus` (focus ring, ≥ 3:1) · `selection` (text selection background).
- **Derived roles** (2026-11-23): each defaults in `tokens.css` to another role, and a theme
  points it elsewhere when its design says so. The value is a `var(--n-…)` of another role or an
  opaque literal; the contract test follows the reference.

  | Role | Default | Meaning | Floor |
  |---|---|---|---|
  | `emph` | `accent-text` | emphasis ink: the active item, the current tab, a highlighted name, legacy accent-as-text | 4.5:1 on every ground |
  | `emph-wash` | `accent-wash` | the soft ground behind an active or highlighted row | `text` on it 4.5:1 |
  | `primary` / `on-primary` | `accent` / `on-accent` | a primary action that is **not** a signature (Send, Save, Run) | `on-primary` 4.5:1 on it; `primary` 3:1 on `bg` and `sheet` |
  | `field-bg` | `sheet` | the fill of inputs, selects and textareas | `text` and `text-3` 4.5:1 on it |

  Ledger sets `emph: var(--n-text)`, `emph-wash: var(--n-bg-3)`, `primary: var(--n-text)`,
  `on-primary: var(--n-bg)`: its vermilion is spent only on the owner's hand. A theme whose
  accent is a pale highlighter in light (a fill keyed in ink) must point `primary` at a fill that
  reaches 3:1, usually its ink.
- The **stop** reaches 3:1 on `bg` and `sheet` as a shape, and `on-stop` 4.5:1 on it: draw the
  stop as a solid `stop` fill with `on-stop` text, never as `stop`-coloured text on a tint.

Every colour role is an opaque literal — `oklch(L C H)` or `#rrggbb` — except `scrim`, which may
carry alpha, the shadows, and the derived roles above. No `color-mix()` or `rgba()` in a colour
role: the contrast test reads the literal.

Non-colour roles a theme may override: the six font stacks (`--n-font-ui`, `-label`, `-text`,
`-title`, `-display`, `-mono`), the label voice (`--n-label-case`, `--n-label-track`,
`--n-label-weight`), weights (`--n-w-reg` is the body weight of a Nerva theme), the type scale
and line heights (never below 12px), `--n-title-track` (tracking at title sizes and up),
`--n-numerals` (`lining-nums`, or `lining-nums tabular-nums` for a theme that wants tabular
figures everywhere; columns of numbers ask for `tabular-nums` themselves), the radii (`--n-r-*`,
and `--n-r-control` for buttons and segmented controls — Atlas makes it a pill without turning
every legacy box into a stadium), the panel treatment (`--n-panel-bg`, `-border`, `-top`,
`-radius`, `-shadow`, `-pad`, and `--n-register-pad` below), a consequence's term column
(`--n-term-max`, below), shadows, control heights, `--n-measure`, `--n-col-gap`, `--n-bar-h`. Spacing (`--n-s-*`) belongs to the density axis; themes
leave it alone.

**The register's inner margin** (`--n-register-pad`, 2026-11-25). Default `0px` in `tokens.css` (a
length, not `0`: the kit takes `min()` of it). A look that draws its panels as cards, with a frame or
a fill, sets it in its base block: the Nerva card looks to their own `--n-panel-pad`, Atlas (`--n-s-5`,
20px), Console (`--n-s-3`, 12px), Threshold and Workbench (the default `--n-s-4`, 16px); Classic in
`bridge.css`'s Classic block to `--n-s-4` (16px) for both looks, not to its `--pad` (Graphite's 20px
narrowed its columns enough to wrap the docket's foot in Romanian at 1280px). Ledger, Briefing and
Presence draw registers with rules, not boxes, and leave it at 0, so nothing moves in them.
`frame/kit/kit.css` makes it a register's own padding on the sides and at the bottom (not the top: the
head's strut sets the title under the top edge), so the rule under the head, every row's hairline and a
scrolling body's scrollbar stay with the register's column, the frame's margin outside them. A register
with a foot leaves the bottom margin to the foot, where it collapses with a margin the foot's last part
keeps of its own (the docket's total, the composer: 16px each) rather than adding to it. The margin is
taken from the column, and the pages' columns were drawn for the width they had without it: below
1100px (one column) the kit takes at most `--n-s-2`, and below 760px (a phone) it draws a register with
rules in every look (its top rule, no frame, no fill, no margin), so no column there is narrower than
the rule looks draw it. No kit or page stylesheet asks which look is on (no `[data-look]` selector): a
new card look sets the role, a new rule look leaves it. `src/test/theme-contrast.test.ts` pins the
default and who sets it, `frame/kit/kit-css.test.ts` the rules, and the render matrix's `register-inset`
gate (`e2e/ledger-shots.spec.ts`) measures it: in a framed register no text, control or total comes
closer to the frame than that margin, and below 760px no register is framed.

**A consequence's term column** (`--n-term-max`, 2026-11-25). The kit draws a written-out consequence
(`.n-consequence`: "If you sign", "To undo", "If you wait") with a term column of 74px (82px from 2200px),
drawn for a label voice in sentence case. A page that needs its terms on one line in every look opts in
(the docket's open entry does, `docket/docket.css`), and the column then grows to this role. Default `0px`
in `tokens.css`: the column does not grow, so nothing moves in any Nerva look (a `minmax()` whose maximum is
below its minimum is its minimum). Classic sets `max-content` in `bridge.css`'s Classic block: its label
voice (mono capitals, tracked `.1em`) never fits 74px ("IF YOU SIGN" 92px, "CA SĂ ANULEZI" 109px), and a
term broken onto two lines made each row of the docket's open entry two lines tall, 21px (English) to 44px
(Romanian) in all, which put the entry's sign line below what the docket's body shows at 1280×800. A look
sets it only when its own label voice needs it; no kit or page stylesheet asks which look is on. Trust's
emergency-stop sheet does not opt in: it keeps the fixed column (in Classic its terms still take two lines).
`src/test/theme-contrast.test.ts` pins the default and who sets it, `frame/kit/kit-css.test.ts` the kit's
column and `docket/docket-css.test.ts` the docket's opt-in.

Every role a theme may set is declared in `tokens.css` on `:is(:root, .n-theme-scope)`, so a
preview scope starts from the defaults rather than inheriting the page theme's scale, weights or
control heights. Spacing, motion and `--n-page-x` stay on `:root`.

**Density** scales what the look resolved instead of replacing it (`overrides.css`): the spacing
steps go about 25% tighter (compact) or 20% looser (comfy), and control heights are multiplied
(compact × 0.875, never raising a look's height and never below 24px unless the look draws it
smaller; comfy × 1.2).

## 4. The type scale, and how legacy sizes map onto it

| Token | Default | Use | Legacy sizes mapped here |
|---|---|---|---|
| `--n-fs-meta` | 12px | times, sources, fine print | below 12px |
| `--n-fs-label` | 13px | table cells, labels, secondary lines | 12 – 12.9px |
| `--n-fs-ui` | 14px | controls, navigation, panel body | 13 – 14.4px |
| `--n-fs-own` | 15px | the owner's words, consequence prose | 14.5 – 16.4px |
| `--n-fs-prose` | 17px | replies, reading text | 16.5 – 19.9px |
| `--n-fs-title` | 22px | register and panel titles | 20 – 27.9px |
| `--n-fs-verdict` | 32px | a verdict | 28 – 39.9px |
| `--n-fs-figure` | 44px | the one large figure | 40px and up |

In CSS write `font-size: var(--n-fs-ui)`. In a React inline style write
`fontSize: 'var(--n-fs-ui)'`. Line heights: `--n-lh-<same name>`.

## 5. Typeface roles, and the label voice

The legacy stylesheet sets `font-family: var(--font-mono)` on about 150 rules; most of them are
small structural labels, not code. The rule from now on:

- labels, section heads, badges, tabs, buttons, table heads → `var(--n-font-label)` with
  `text-transform: var(--n-label-case); letter-spacing: var(--n-label-track);`
- identifiers, hashes, ids, addresses, model and capability names, code, logs, JSON →
  `var(--n-font-mono)`
- everything else → inherit `var(--n-font-ui)`; reading prose → `var(--n-font-text)`

Classic sets `--n-font-label` to its mono and `--n-label-case: uppercase`, so Classic keeps its
voice; Ledger sets a sentence-case sans. Never hard-code `text-transform: uppercase` or a
positive `letter-spacing` on a label again.

Helpers in `type.ts`: `LABEL` (the voice), `LABEL_STRONG` (a heading drawn in the label voice:
same face, case and tracking at `--n-w-semi`, for the h2–h4 and strong lead-ins that used to be
bold mono), `MONO` (identifiers), `IDENT` (an identifier inside a label: mono, and immune to the
label's case and tracking, because identifiers are case-sensitive), `PROSE`.

The panel kit's `mono` style is for identifiers only. Messages, notes, errors, descriptions and
hints that used to be set in `...mono` take `...note` from `panel-kit.tsx` (the label size in
the interface face). When a line mixes both, the identifier gets its own `<code>` or `IDENT`
span.

The owner's **typeface override** (`data-font`) replaces every face except mono: `ui`, `label`,
`text`, `title` and `display`. A theme's own pairing returns with "Theme default".

## 6. The legacy bridge (`bridge.css`)

For every **Nerva** theme, on `:root[data-look="<id>"]` **and** `:root[data-look="<id>"] .hud-root`
(the second is needed because `styles.css` re-declares the legacy tokens on `.hud-root`):

| Legacy token | Becomes |
|---|---|
| `--void` | `var(--n-bg)` |
| `--void-2` | `var(--n-bg-2)` |
| `--surface` | `var(--n-sheet)` |
| `--surface-2` | `var(--n-sheet-2)` |
| `--panel-line`, `--panel-line-2` | `var(--n-rule)` |
| `--field-line` (new 2026-11-23; `styles.css` defines it as `var(--panel-line)` for Classic) | `var(--n-rule-field)`: the edge of every legacy input, select, textarea and the composer's field |
| `--bracket` | `transparent` |
| `--accent` | `var(--n-emph)` (was `--n-accent` until 2026-11-23: in Ledger that painted the clock, the rail, agent names and every primary button in the seal's vermilion, and in a light theme whose accent is a pale highlighter it made accent-as-text unreadable) |
| `--accent-light` | `var(--n-emph)` |
| `--accent-dim` | `var(--n-rule-field)` |
| `--accent-faint` | `var(--n-emph-wash)` |
| `--accent-glow` | `transparent` |
| `--green` / `--green-dim` | `var(--n-ok)` / `var(--n-ok-wash)` |
| `--amber` | `var(--n-warn)` |
| `--red` | `var(--n-bad)` |
| `--violet` | `var(--n-cloud)` |
| `--ink`, `--ink-2`, `--ink-3` | `var(--n-text)`, `var(--n-text-2)`, `var(--n-text-3)` |
| `--ink-4` | `var(--n-rule-2)` |
| `--radius` | `var(--n-r-1)` |
| `--pad` | `var(--n-panel-pad)` |
| `--gap` | `var(--n-s-3)` |
| `--glow-text` | `none` |
| `--shadow` | `var(--n-shadow-1)` |
| `--tex-opacity` | `0` |
| `--font-ui` | `var(--n-font-ui)` |
| `--font-mono` | `var(--n-font-mono)` |

The `.hud-root[data-accent=…]` blocks in `styles.css` have lower specificity than
`:root[data-look="<id>"] .hud-root`, so the accent axis applies to Classic only.

Legacy rules that **fill** a control with the accent (the send button, a primary decision
button, a primary tool button) are rewritten in `styles.css` to `background: var(--n-primary);
color: var(--n-on-primary)`, which every look defines (Classic through the reverse bridge), so
they keep the theme's designed primary instead of the emphasis ink. Text sitting on an accent
fill is never `var(--void)` again.

For **Classic** (`obsidian`, `graphite`) the bridge runs the other way: on
`:root[data-look="obsidian"|"graphite"]` and their `.hud-root` descendant it defines every
`--n-*` colour role from the legacy tokens (`--n-bg: var(--void)`, …, `--n-accent: var(--accent)`,
`--n-emph: var(--accent-light)`, `--n-emph-wash: var(--accent-faint)`, `--n-primary:
var(--accent)`, `--n-on-primary: var(--void)`, `--n-field-bg: var(--surface)`,
`--n-font-label: var(--font-mono)`, `--n-label-case: uppercase`, `--n-label-track: .1em`), so new
components render in Classic too. A Classic preview scope follows the owner's Classic accent:
`.n-theme-scope:is([data-look="obsidian"], [data-look="graphite"])` with a `:where([data-accent=…])`
qualifier restates each accent's legacy tokens (cyan, the default, included), with the literal
values of `styles.css`'s `.hud-root[data-accent=…]` blocks (`theme-apply.test.ts` fails if they
drift), and Personalisation puts `data-accent` on its Classic cards.

The bridge also, for Nerva themes only: paints `html`/`body` with `var(--n-bg)` / `var(--n-text)`
in the theme's `--n-font-ui` at `--n-w-reg` with `font-variant-numeric: var(--n-numerals)`, sets
`color-scheme`, styles `::selection`, scrollbars and form controls from roles (fields on
`--n-field-bg`), and switches off the cockpit decoration (texture layers, scan bar, corner
brackets `.bk`, clip-path chamfers, text glows, the spinning reactor, pulsing dots, the marquee
animation — a ticker that does not move is still readable). Panels (`.panel`, the panel kit
`Card`) take the panel-treatment roles.

## 7. Appearance (one owner instance, synced)

- `look` gains the new ids; **default `ledger`**. Server order (`agents/core/appearance.py`):
  `('ledger', 'obsidian', 'graphite', 'presence', 'briefing', 'workbench', 'threshold', 'console', 'atlas')`
  — index 0 is the default and the coercion target.
- New field **`scheme`**: `('dark', 'light', 'system')`, default `dark`. Client, server
  (`OPTIONS` + the Pydantic model in `agents/core/routers/preferences.py`), OpenAPI types and
  snapshots all learn it in one change. Native ignores it.
- `accent`, `scanline`, `dotgrid` stay (Classic uses them); Personalisation shows accent only for
  Classic and does not offer scanline/dot grid for Nerva themes.
- Cache migration: the cache key stays `hud.appearance.v1:<base>`. The stored object gains
  `version: 2`. When a cached object has `version: 1`, its `look` is ignored if it equals
  `obsidian` (that was the old default, not a choice), so an unconfigured install moves to Ledger;
  any other cached value is kept. Pending edits in the journal are untouched.
- `apply.ts` exports `applyAppearanceToDocument(preferences, prefersDark)` and
  `applyInitialAppearance()` (reads the cache synchronously; called in `main.tsx` before React
  renders, so the first paint is already themed — no inline script, the CSP forbids it). It sets the
  `<html>` attributes in §2, `color-scheme`, and `<meta name="theme-color">` from the resolved
  theme's `--n-bg`. `system` follows `prefers-color-scheme` live.
- One owner instance: `App` creates `useAppearance()` once and provides it through
  `AppearanceProvider`; any component reads it with `useAppearanceContext()`, which returns
  `{ preferences, setPreference(key, value), status, error, retry, motion }` (the same shape
  `useAppearance()` returns). Outside the provider it returns `null`.

## 8. Personalisation (Settings)

A real settings page, not only the command palette: Console panel id `appearance`
("Personalisation" / "Personalizare"), later a second-level page of the Settings area.
It offers, in this order: **Theme** (a card per theme with a live `.n-theme-scope` preview,
the name and tagline, the schemes it supports), **Scheme** (Dark · Light · Same as system), then
Density, Motion, Typeface (the existing five font ids), Language, and Accent (Classic only).
Every change applies instantly and syncs like every other appearance edit. Copy exists in
English and Romanian. While this page is open, the shell does not repeat its own
appearance-sync notice: the page's own status line (localised, with Retry) is the only live
region announcing a sync failure.

## 8b. The kit's class names (shared with Phase B)

`kit.css` owns the primitives; Phase B (docs/design/hud-next/PHASE_B_PLAN.md §1.3) builds on
these names and does not redefine them:

| Class | What |
|---|---|
| `n-btn` + `--sm` | a button at `--n-control-h` (or `-sm`), radius `--n-r-control` |
| `n-btn--primary` | a primary action that is not a signature: `--n-primary` / `--n-on-primary` |
| `n-btn--ink` | an ink button (`--n-text` fill, `--n-bg` text) whatever the theme |
| `n-btn--accent` | the theme's accent fill (`--n-accent` / `--n-on-accent`); in Ledger, only for signing |
| `n-btn--quiet`, `n-btn--bare` | a framed quiet button; a borderless text button |
| `n-btn--danger` | the stop's colours, for destructive actions |
| `n-seg` | a segmented control (radio group drawn as joined buttons; `aria-checked` marks the choice) |
| `n-field` (aliases `n-input`, `n-textarea`) + `n-field--code` | fields on `--n-field-bg` |
| `n-link` | an in-app text link in the emphasis ink, underlined on hover and focus |
| `n-kbd` | a key cap |
| `n-tag` (+ tones), `n-chip`, `n-row`, `n-state`, `n-json`, `n-card`, `n-meter` | as in Phase A |

Deviations accepted on 2026-11-23: a Card title uses the label voice at `--n-fs-label`
(Cards nest inside hand-written panels whose titles are labels); the meter track is `bg-3`;
tags use the label face but not its case or tracking, because tags carry case-sensitive ids.

Kit rules settled in the integration round (2026-11-23), so Phase B draws the same way:
- `n-btn--quiet` is framed with `--n-rule-2` (the quiet control edge) in secondary ink.
- `n-link` keeps a quiet underline at rest in `--n-rule-field` and inks it on hover and focus:
  in most themes the emphasis ink equals the body ink, and a link in prose must still read as a
  link without colour (WCAG 1.4.1).
- A chosen segment (`n-seg`, `aria-checked="true"`) is `--n-emph-wash` with `--n-text` at
  semibold and an inset 2px bar in `--n-emph`; hovering a segment inks its word and draws a quiet
  `--n-rule-field` bar with no fill.
- Pressed buttons (`:active`, `aria-pressed="true"`) are `--n-bg-3` with `--n-text`; filled
  variants keep their fill when pressed. `aria-disabled="true"` reads as `:disabled`.
- The ink button's hover fill is `--n-text-2`; primary, accent and danger brighten slightly.
- Tag tone `n-tag--emph`: a tag tinted with the legacy accent or `--n-emph` gets the emphasis ink
  at semibold in the neutral frame, no wash; only `--n-accent` / `--n-accent-text` keep the
  accent tone with its wash.
- Figures in columns use `lining-nums tabular-nums` (a `font-variant-numeric` replaces the
  inherited `--n-numerals` rather than adding to it).
- `n-kbd` keeps the case it is written in, at `--n-fs-meta`.
- `src/test/kit-classes.test.ts` pins these names and rules.

## 9. Gates

- `src/test/theme-contrast.test.ts` (this contract's test) passes for every theme file: every
  colour role declared, text roles 4.5:1 on every ground, fills and edges as in §3, the derived
  roles resolved and checked, the five status colours apart.
- `npx tsc --noEmit` clean; the targeted tests you touched pass; nothing under 12px on screen in a
  Nerva theme; no new colour literal in a component.
- No remote font or asset: every face is self-hosted or a local system stand-in.
