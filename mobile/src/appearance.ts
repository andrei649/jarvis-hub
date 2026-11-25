/** Native consumes only portable appearance choices, never browser layout/texture CSS. */
/** The browser HUD's themes (frontend/src/theme/registry.ts): seven Nerva themes and the two Classic
 *  looks. Native follows the look in its dark scheme; the browser-only `scheme` field is ignored. */
export type Look = 'ledger' | 'obsidian' | 'graphite' | 'presence' | 'briefing' | 'workbench' | 'threshold' | 'console' | 'atlas';
export type Appearance = { accent: 'cyan' | 'amber' | 'green' | 'violet'; look: Look;
  font: 'theme' | 'system-sans' | 'system-serif' | 'system-mono' | 'jetbrains-mono' };
export const DEFAULT_APPEARANCE: Appearance = { accent: 'cyan', look: 'ledger', font: 'theme' };
const choices = { accent: ['cyan', 'amber', 'green', 'violet'],
  look: ['ledger', 'obsidian', 'graphite', 'presence', 'briefing', 'workbench', 'threshold', 'console', 'atlas'],
  font: ['theme', 'system-sans', 'system-serif', 'system-mono', 'jetbrains-mono'] };
export function normalizeAppearance(value: unknown): Appearance {
  const source = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const result = { ...DEFAULT_APPEARANCE };
  for (const key of Object.keys(result) as (keyof Appearance)[]) {
    if (typeof source[key] === 'string' && choices[key].includes(source[key] as string)) {
      (result as Record<string, string>)[key] = source[key] as string;
    }
  }
  return result;
}
