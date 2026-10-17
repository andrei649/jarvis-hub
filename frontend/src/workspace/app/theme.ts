/* Theme application. The choice lives on <html data-theme="light|dark|system">; workspace.css
   resolves "system" with prefers-color-scheme, so following the OS needs no listener here. The
   value is mirrored in storage only so the sign-in screen opens in the user's last theme. */
import type { Theme } from '../api/types';
import { writePref } from './storage';

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  writePref('theme', theme);
}
