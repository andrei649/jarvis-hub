import { useMemo } from 'react';
import { Platform } from 'react-native';
import { useAppearance } from './context/AppearanceContext';
import { DEFAULT_APPEARANCE, type Appearance, type Look } from './appearance';

type Palette = {
  bg: string; surface: string; surfaceAlt: string; border: string; text: string; textDim: string;
  accent: string; accentDim: string; userBubble: string; ok: string; warn: string; danger: string;
};

/**
 * The browser HUD's Nerva themes in their dark scheme, converted to hex from the theme files
 * (frontend/src/theme/themes/<id>.css, a var(--n-…) value followed to the role it names; contract:
 * frontend/src/theme/CONTRACT.md). Native follows the look but not the scheme, and the Classic accent
 * choice does not apply to a Nerva theme.
 *
 * Native's roles are the HUD v2 roles, so they map the way the browser's legacy bridge maps them
 * (CONTRACT.md §6, 2026-11-23): accent <- --n-emph, the emphasis ink (the bridge's --accent);
 * accentDim <- --n-rule-field (--accent-dim); userBubble <- --n-emph-wash (--accent-faint, the
 * browser's own user bubble and the ground of a chosen row). A theme's own accent colour (Ledger's
 * vermilion, Presence's tungsten, Workbench's yellow, ...) is spent only on what waits for the owner,
 * and native has no role for that, so native chrome, links and Send are drawn in each theme's ink.
 * The rest: bg <- --n-bg, surface <- --n-sheet, surfaceAlt <- --n-sheet-2, border <- --n-rule-2,
 * text <- --n-text, textDim <- --n-text-2, ok/warn/danger <- --n-ok/--n-warn/--n-bad. Each theme keeps
 * its status colours apart from each other and from its text (contract §3), so they carry meaning
 * here too. frontend/native-tests/transport.test.tsx fails with the hex to paste when a theme moves.
 */
const NERVA: Partial<Record<Look, Palette>> = {
  ledger: { bg: '#0e1210', surface: '#151a18', surfaceAlt: '#191f1c', border: '#323a36', text: '#dde4db', textDim: '#b0b8b0',
    accent: '#dde4db', accentDim: '#68716c', userBubble: '#1b211e', ok: '#9dc3a3', warn: '#e0bb7d', danger: '#db959c' },
  presence: { bg: '#0f0e0c', surface: '#191815', surfaceAlt: '#1e1c1a', border: '#474541', text: '#f3f0ea', textDim: '#c1bdb7',
    accent: '#f3f0ea', accentDim: '#6f6d69', userBubble: '#2d2b28', ok: '#a0c6a7', warn: '#f6bc63', danger: '#fd7468' },
  briefing: { bg: '#121417', surface: '#1f2024', surfaceAlt: '#232529', border: '#3f4145', text: '#ebe9e4', textDim: '#bcbab5',
    accent: '#ebe9e4', accentDim: '#696c71', userBubble: '#292b30', ok: '#a3c9aa', warn: '#f1cf44', danger: '#fd8074' },
  workbench: { bg: '#0e0d0b', surface: '#151412', surfaceAlt: '#171715', border: '#383633', text: '#eeede8', textDim: '#bfbeb9',
    accent: '#eeede8', accentDim: '#6d6c68', userBubble: '#272623', ok: '#5fcf83', warn: '#d6d4d0', danger: '#ff655a' },
  threshold: { bg: '#0b0b09', surface: '#141311', surfaceAlt: '#1d1c19', border: '#494744', text: '#f2efe9', textDim: '#c2bfba',
    accent: '#f2efe9', accentDim: '#72706c', userBubble: '#312f2b', ok: '#c2bfba', warn: '#e8ac7c', danger: '#fa7a6c' },
  console: { bg: '#0c0b09', surface: '#141211', surfaceAlt: '#1d1b19', border: '#3f3d3a', text: '#f2f0ec', textDim: '#c3c1bd',
    accent: '#f2f0ec', accentDim: '#716e6a', userBubble: '#1d1b19', ok: '#c3c1bd', warn: '#e5ab7f', danger: '#fe7d6f' },
  atlas: { bg: '#070a09', surface: '#141816', surfaceAlt: '#1c211f', border: '#414744', text: '#ecf1ef', textDim: '#c4cbc8',
    accent: '#ecf1ef', accentDim: '#656c69', userBubble: '#272d2b', ok: '#c4cbc8', warn: '#f8c35b', danger: '#ff847f' },
};

/** Classic (the HUD v2 looks): Obsidian or Graphite grounds with the owner's accent, as before. */
function classicPalette(appearance: Appearance): Palette {
  const graphite = appearance.look === 'graphite';
  const accents = {
    cyan: ['#00aeef', '#0a6b8f', '#0a2740'], amber: ['#ffb23f', '#805b26', '#302719'],
    green: ['#41f59b', '#237d52', '#153026'], violet: ['#a78bfa', '#66508f', '#28203d'],
  };
  const [accent, accentDim, userBubble] = accents[appearance.accent];
  return {
    bg: graphite ? '#0b0d11' : '#030810', surface: graphite ? '#1a1e26' : '#0a1422',
    surfaceAlt: graphite ? '#20252e' : '#0f1d30', border: graphite ? '#3b4554' : '#1b3350',
    text: graphite ? '#eef1f5' : '#e6f0fa', textDim: graphite ? '#a4afc1' : '#7d93ab',
    accent, accentDim, userBubble, ok: '#3ddc97', warn: '#ffb454', danger: '#ff5c7a',
  };
}

/** Native palette roles, derived only from fixed server appearance choices. */
export function createTheme(appearance: Appearance, platform: string = Platform.OS) {
  const palette = NERVA[appearance.look] ?? classicPalette(appearance);
  const codeFont = platform === 'ios' ? 'Menlo' : 'monospace';
  const fontFamily = appearance.font === 'system-serif' ? (platform === 'ios' ? 'Georgia' : 'serif')
    : appearance.font === 'system-mono' || appearance.font === 'jetbrains-mono' ? codeFont : undefined;
  return {
    ...palette, fontFamily, codeFont,
    fontFallback: appearance.font === 'jetbrains-mono' ? 'JetBrains Mono is unavailable on this native app; using platform monospace.' : '',
  };
}
export type Theme = ReturnType<typeof createTheme>;
export const defaultTheme = createTheme(DEFAULT_APPEARANCE);
export function useTheme(): Theme {
  const { preferences } = useAppearance();
  return useMemo(() => createTheme(preferences), [preferences]);
}
export function useThemeStyles<T>(factory: (theme: Theme) => T) {
  const theme = useTheme();
  const styles = useMemo(() => factory(theme), [factory, theme]);
  return { theme, styles };
}
