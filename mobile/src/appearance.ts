/** Native consumes only portable appearance choices, never browser layout/texture CSS. */
export type Appearance = { accent: 'cyan' | 'amber' | 'green' | 'violet'; look: 'obsidian' | 'graphite';
  font: 'theme' | 'system-sans' | 'system-serif' | 'system-mono' | 'jetbrains-mono' };
export const DEFAULT_APPEARANCE: Appearance = { accent: 'cyan', look: 'obsidian', font: 'theme' };
const choices = { accent: ['cyan', 'amber', 'green', 'violet'], look: ['obsidian', 'graphite'],
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
