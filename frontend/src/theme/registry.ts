/**
 * Theme registry (contract v1, see ./CONTRACT.md).
 *
 * A theme is a visual language — palette, typefaces, shape, density and its signature
 * details — applied to the one HUD structure. Its CSS lives in ./themes/<id>.css and is
 * selected by `data-look` on <html> (and on `.n-theme-scope` for live previews).
 *
 * `look` is the existing appearance field, so the server, the browser cache and the native
 * app keep one field. `obsidian` and `graphite` are the HUD v2 looks, kept as "Classic":
 * they have no file in ./themes (bridge.css derives their --n-* roles from the old tokens)
 * and they are dark only.
 */
export type ThemeId =
  | 'ledger' | 'presence' | 'briefing' | 'workbench' | 'threshold' | 'console' | 'atlas'
  | 'obsidian' | 'graphite';
export type Scheme = 'dark' | 'light';
export type SchemePreference = Scheme | 'system';
type Text = { en: string; ro: string };

export interface ThemeInfo {
  id: ThemeId;
  name: Text;
  /** One line shown under the name in Personalisation. */
  tagline: Text;
  /** Schemes the theme designs. Classic looks are dark only. */
  schemes: readonly Scheme[];
  /** What `system` falls back to when the OS preference cannot be read. */
  defaultScheme: Scheme;
  family: 'nerva' | 'classic';
}

export const THEMES: readonly ThemeInfo[] = [
  {
    id: 'ledger', family: 'nerva', schemes: ['dark', 'light'], defaultScheme: 'dark',
    name: { en: 'Ledger', ro: 'Ledger' },
    tagline: {
      en: 'A typeset working ledger. One colour, vermilion, means your signature.',
      ro: 'Un registru de lucru tipografic. O singură culoare, vermilionul, înseamnă semnătura ta.',
    },
  },
  {
    id: 'presence', family: 'nerva', schemes: ['dark', 'light'], defaultScheme: 'dark',
    name: { en: 'Presence', ro: 'Presence' },
    tagline: {
      en: 'One calm presence: large type, few things on screen, warm amber.',
      ro: 'O singură prezență calmă: text mare, puține lucruri pe ecran, chihlimbar cald.',
    },
  },
  {
    id: 'briefing', family: 'nerva', schemes: ['light', 'dark'], defaultScheme: 'light',
    name: { en: 'Briefing', ro: 'Briefing' },
    tagline: {
      en: 'An editorial morning brief: headlines, a reading serif, a highlighter.',
      ro: 'Un brief editorial de dimineață: titluri, un serif de citit, un marker.',
    },
  },
  {
    id: 'workbench', family: 'nerva', schemes: ['dark', 'light'], defaultScheme: 'dark',
    name: { en: 'Workbench', ro: 'Workbench' },
    tagline: {
      en: 'The converged 2026 workspace: quiet neutrals, dense and exact.',
      ro: 'Spațiul de lucru din 2026: neutre liniștite, dens și exact.',
    },
  },
  {
    id: 'threshold', family: 'nerva', schemes: ['dark', 'light'], defaultScheme: 'dark',
    name: { en: 'Threshold', ro: 'Threshold' },
    tagline: {
      en: 'A line between the machine and you. Yellow marks what waits at the line.',
      ro: 'O linie între mașină și tine. Galbenul marchează ce așteaptă la linie.',
    },
  },
  {
    id: 'console', family: 'nerva', schemes: ['dark', 'light'], defaultScheme: 'dark',
    name: { en: 'Console', ro: 'Console' },
    tagline: {
      en: 'A dense terminal-grade instrument: tight rows, tabular figures, amber signals.',
      ro: 'Un instrument dens, de terminal: rânduri strânse, cifre tabulare, semnale chihlimbar.',
    },
  },
  {
    id: 'atlas', family: 'nerva', schemes: ['dark', 'light'], defaultScheme: 'dark',
    name: { en: 'Atlas', ro: 'Atlas' },
    tagline: {
      en: 'Soft near-black, emerald and rounded floating sheets, like the 3D brain.',
      ro: 'Negru moale, smarald și foi rotunjite care plutesc, ca în creierul 3D.',
    },
  },
  {
    id: 'obsidian', family: 'classic', schemes: ['dark'], defaultScheme: 'dark',
    name: { en: 'Classic · Obsidian', ro: 'Clasic · Obsidian' },
    tagline: {
      en: 'The HUD v2 cockpit look: cyan on navy, mono labels.',
      ro: 'Aspectul cockpitului HUD v2: cyan pe bleumarin, etichete mono.',
    },
  },
  {
    id: 'graphite', family: 'classic', schemes: ['dark'], defaultScheme: 'dark',
    name: { en: 'Classic · Graphite', ro: 'Clasic · Graphite' },
    tagline: {
      en: 'The HUD v2 look with rounded, frosted panels.',
      ro: 'Aspectul HUD v2 cu panouri rotunjite, mate.',
    },
  },
] as const;

export const THEME_IDS: readonly ThemeId[] = THEMES.map((theme) => theme.id);
export const DEFAULT_THEME: ThemeId = 'ledger';
export const DEFAULT_SCHEME_PREFERENCE: SchemePreference = 'dark';
export const SCHEME_PREFERENCES: readonly SchemePreference[] = ['dark', 'light', 'system'];

export function themeById(id: string | null | undefined): ThemeInfo {
  return THEMES.find((theme) => theme.id === id) ?? THEMES[0];
}

export function isClassicLook(id: string | null | undefined): boolean {
  return themeById(id).family === 'classic';
}

/**
 * The scheme a theme actually renders in. `system` follows the OS; a scheme the theme does
 * not design falls back to the theme's own default (Classic is always dark).
 */
export function resolveScheme(theme: ThemeInfo, preference: SchemePreference, prefersDark: boolean | null): Scheme {
  const wanted: Scheme = preference === 'system'
    ? (prefersDark === null ? theme.defaultScheme : prefersDark ? 'dark' : 'light')
    : preference;
  return theme.schemes.includes(wanted) ? wanted : theme.defaultScheme;
}
