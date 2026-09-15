import { useMemo } from 'react';
import { Platform } from 'react-native';
import { useAppearance } from './context/AppearanceContext';
import { DEFAULT_APPEARANCE, type Appearance } from './appearance';

/** Native palette roles, derived only from fixed server appearance choices. */
export function createTheme(appearance: Appearance, platform: string = Platform.OS) {
  const graphite = appearance.look === 'graphite';
  const accents = {
    cyan: ['#00aeef', '#0a6b8f', '#0a2740'], amber: ['#ffb23f', '#805b26', '#302719'],
    green: ['#41f59b', '#237d52', '#153026'], violet: ['#a78bfa', '#66508f', '#28203d'],
  };
  const [accent, accentDim, userBubble] = accents[appearance.accent];
  const codeFont = platform === 'ios' ? 'Menlo' : 'monospace';
  const fontFamily = appearance.font === 'system-serif' ? (platform === 'ios' ? 'Georgia' : 'serif')
    : appearance.font === 'system-mono' || appearance.font === 'jetbrains-mono' ? codeFont : undefined;
  return {
    bg: graphite ? '#0b0d11' : '#030810', surface: graphite ? '#1a1e26' : '#0a1422',
    surfaceAlt: graphite ? '#20252e' : '#0f1d30', border: graphite ? '#3b4554' : '#1b3350',
    text: graphite ? '#eef1f5' : '#e6f0fa', textDim: graphite ? '#a4afc1' : '#7d93ab',
    accent, accentDim, userBubble, ok: '#3ddc97', warn: '#ffb454', danger: '#ff5c7a', fontFamily, codeFont,
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
