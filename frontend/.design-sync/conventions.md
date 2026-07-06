# Building with the JARVIS HUD design system

This is a **dark-first sci-fi cockpit HUD**. Everything you build sits on the void
background and speaks in CSS custom properties — there is no utility-class system.

## Wrapping and setup (required)

Wrap every screen you build in the theme root:

```jsx
<div className="hud-root" style={{ background: 'var(--void)', minHeight: '100vh' }}>
  {/* your layout */}
</div>
```

`.hud-root` carries the token scope and the theme switches. Without it (or outside a
dark background) the light ink washes out to near-invisible. Theme variants are
data-attributes ON `.hud-root`:

- `data-look="graphite"` — alternate look (default is obsidian; no attribute needed)
- `data-accent="cyan" | "green" | "amber" | "violet"` — accent family (default cyan)
- `data-density="compact" | "comfy"` — spacing density
- `data-motion="calm"` — reduced motion

## The styling idiom: tokens via var(--*), never hardcoded colors

Style your own layout glue with the DS tokens (all defined at the top of `styles.css`):

- Surfaces: `--void`, `--void-2` (page), `--surface`, `--surface-2` (panels),
  `--panel-line`, `--panel-line-2` (hairlines), `--bracket` (corner brackets)
- Ink: `--ink` (primary text)
- Accent family: `--accent`, `--accent-light`, `--accent-dim`, `--accent-faint`, `--accent-glow`
- Status: `--green`, `--green-dim`, `--amber`, `--red`, `--violet`
- Typography: `--font-ui` (Space Grotesk — labels, headings),
  `--font-mono` (JetBrains Mono — data, timestamps, readouts). Both ship as
  self-hosted variable fonts; uppercase mono micro-labels are the HUD voice.

Components draw in `currentColor` where it matters: `Icon`, `Glyph`, `Reactor` inherit
the surrounding `color` — set `color: 'var(--accent)'` (or a status token) on a parent
span to tint them. `Icon` takes its path from the exported `ICONS` map:
`<Icon d={ICONS.shield} size={24} />`.

## Where the truth lives

- `styles.css` — the full token set (top of file) and every component's classes. Read it
  before inventing any styling.
- `components/<group>/<Name>/<Name>.prompt.md` — per-component usage docs.
- The `V2` export — the seed data world (agents roster, ticker feed, dossiers,
  glyph ids). Use it for realistic content: `V2.AGENTS`, `V2.TICKER`, `V2.GLYPHS`,
  `V2.SEED_MESSAGES`, `V2.DOSSIER`, `V2.I18N.en` (pass as the `t` prop where a
  component takes translations).

## Idiomatic example

```jsx
import { Meter, Icon, ICONS, Ticker, V2 } from 'jarvis-hud-v2';

<div className="hud-root" style={{ background: 'var(--void)', minHeight: '100vh', padding: 16 }}>
  <Ticker items={V2.TICKER} t={V2.I18N.en} />
  <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 12, marginTop: 12 }}>
    <aside style={{ background: 'var(--surface)', border: '1px solid var(--panel-line)',
                    borderRadius: 8, padding: 12, display: 'grid', gap: 10 }}>
      <span style={{ color: 'var(--accent)', fontFamily: 'var(--font-ui)' }}>
        <Icon d={ICONS.cockpit} size={18} /> SYSTEMS
      </span>
      <Meter label="VRAM" val={71} />
      <Meter label="CPU" val={23} />
    </aside>
    {/* main column: compose panels (TodayPanel, KgPanel, …) here */}
  </div>
</div>
```

Notes for composing: the dashboard `*Panel` components are self-contained (they fetch
their own data live; in static contexts they render designed frame/empty states) and sit
naturally in 340–480px columns. Full-screen `*Mode` components expect ≥1100px width —
below that the DS's responsive breakpoint hides secondary columns by design.
