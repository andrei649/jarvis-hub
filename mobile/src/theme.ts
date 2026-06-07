/**
 * Jarvis mobile palette — derived from the HUD v2 theme
 * (background #030810, accent cyan #00aeef).
 */
export const theme = {
  bg: '#030810',
  surface: '#0a1422',
  surfaceAlt: '#0f1d30',
  border: '#1b3350',
  accent: '#00aeef',
  accentDim: '#0a6b8f',
  text: '#e6f0fa',
  textDim: '#7d93ab',
  userBubble: '#0a2740',
  ok: '#3ddc97',
  warn: '#ffb454',
  danger: '#ff5c7a',
} as const;

export type Theme = typeof theme;
