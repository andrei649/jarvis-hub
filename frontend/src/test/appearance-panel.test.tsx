/* Settings → Personalisation (theme contract v1, §8). The panel reads and writes appearance
   only through the shared AppearanceProvider: a live-preview card per registry theme (Nerva
   first, then Classic), the colour scheme, density, motion, typeface and language, and the
   accent only while a Classic theme is in use. Copy exists in English and Romanian; outside
   the provider it renders a read-only notice. The fake API below is stateful, so a choice
   shows up at once the way the real one-owner instance does. */
import React, { useState } from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { AppearancePanel } from '../panels/appearance';
import { AppearanceProvider, type AppearanceApi } from '../theme/appearance-context';
import { SCHEME_PREFERENCES, THEMES } from '../theme/registry';

const BASE: Record<string, string> = {
  look: 'ledger', scheme: 'dark', accent: 'cyan', density: 'normal', motion: 'system',
  font: 'theme', lang: 'en', scanline: 'on', dotgrid: 'off',
};
const ORDER = [...THEMES.filter((t) => t.family === 'nerva'), ...THEMES.filter((t) => t.family === 'classic')];

type Extra = Partial<Pick<AppearanceApi, 'status' | 'error' | 'retry' | 'motion'>>;

function renderPanel(preferences: Record<string, string> = {}, extra: Extra = {}) {
  const calls: [string, string][] = [];
  function Harness() {
    const [prefs, setPrefs] = useState<Record<string, string>>({ ...BASE, ...preferences });
    const value: AppearanceApi = {
      preferences: prefs,
      setPreference: (key, next) => {
        calls.push([key, next]);
        setPrefs((current) => ({ ...current, [key]: next }));
      },
      status: 'synced',
      error: '',
      retry: () => {},
      motion: 'calm',
      ...extra,
    };
    return <AppearanceProvider value={value}><AppearancePanel /></AppearanceProvider>;
  }
  return { ...render(<Harness />), calls };
}

const card = (name: string) => screen.getByRole('button', { name });
const preview = (button: HTMLElement) => button.querySelector('.n-theme-scope') as HTMLElement;
const group = (name: string) => screen.getByRole('radiogroup', { name });
const radio = (groupName: string, name: string) => within(group(groupName)).getByRole('radio', { name }) as HTMLInputElement;
const describedBy = (el: Element) => (el.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean)
  .map((id) => document.getElementById(id)?.textContent);

/** A stand-in for the OS colour scheme that can change while the page is open. `dark: null`
    answers neither query, the way an engine that cannot tell does. */
function stubSystemScheme(initial: boolean | null) {
  const system = { dark: initial, listeners: new Set<() => void>() };
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() {
      if (system.dark === null) return false;
      if (query.includes('prefers-color-scheme: dark')) return system.dark;
      if (query.includes('prefers-color-scheme: light')) return !system.dark;
      return false;
    },
    media: query,
    addEventListener: (_type: string, listener: () => void) => { system.listeners.add(listener); },
    removeEventListener: (_type: string, listener: () => void) => { system.listeners.delete(listener); },
  }));
  return {
    system,
    change(dark: boolean | null) { act(() => { system.dark = dark; system.listeners.forEach((listener) => listener()); }); },
  };
}

let logged: unknown[][];
beforeEach(() => {
  logged = [];
  document.documentElement.lang = '';
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => { logged.push(['error', ...args]); });
  vi.spyOn(console, 'warn').mockImplementation((...args: unknown[]) => { logged.push(['warn', ...args]); });
});
afterEach(() => {
  vi.unstubAllGlobals();
  expect(logged, 'the panel must render without console errors or warnings').toEqual([]);
});

describe('Personalisation — theme cards', () => {
  it('offers one card per registry theme, Nerva first, each a toggle named by the theme with a live preview', () => {
    renderPanel();
    const cards = within(screen.getByRole('list', { name: 'Theme' })).getAllByRole('button');
    expect(cards).toHaveLength(9);
    expect(cards).toHaveLength(THEMES.length);
    ORDER.forEach((theme, i) => {
      expect(card(theme.name.en)).toBe(cards[i]);
      expect(cards[i].getAttribute('aria-pressed')).toBe(String(theme.id === 'ledger'));
      expect(describedBy(cards[i])).toEqual([theme.tagline.en, theme.schemes.length > 1 ? (theme.schemes[0] === 'light' ? 'Light and dark' : 'Dark and light') : 'Dark only']);
      const scope = preview(cards[i]);
      expect(scope.getAttribute('data-look')).toBe(theme.id);
      expect(scope.getAttribute('data-scheme')).toBe('dark');
      expect(scope.getAttribute('aria-hidden')).toBe('true');
      // the miniature of the Ledger home: masthead, a register with two rows, a reply, the foot
      expect(scope.querySelectorAll('.ap-mini-mast, .ap-mini-reg, .ap-mini-reply, .ap-mini-sign, .ap-mini-foot')).toHaveLength(5);
      expect(scope.querySelectorAll('.ap-mini-row')).toHaveLength(2);
    });
    expect(within(cards[0]).getByText('In use')).toBeTruthy();
    expect(cards.filter((c) => c.getAttribute('aria-pressed') === 'true')).toHaveLength(1);
  });

  it('applies a theme on click through setPreference and does not rewrite the one in use', () => {
    const { calls } = renderPanel();
    fireEvent.click(card('Atlas'));
    expect(calls).toEqual([['look', 'atlas']]);
    expect(card('Atlas').getAttribute('aria-pressed')).toBe('true');
    expect(card('Ledger').getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(card('Atlas'));
    expect(calls).toEqual([['look', 'atlas']]);
    fireEvent.click(card('Classic · Graphite'));
    expect(calls).toEqual([['look', 'atlas'], ['look', 'graphite']]);
  });
});

describe('Personalisation — colour scheme', () => {
  it('writes the scheme and re-renders every preview in the scheme that theme would use', () => {
    const { calls } = renderPanel();
    expect(within(group('Colour scheme')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Dark', 'Light', 'Same as system']);
    expect(radio('Colour scheme', 'Dark').checked).toBe(true);
    fireEvent.click(radio('Colour scheme', 'Light'));
    expect(calls).toEqual([['scheme', 'light']]);
    expect(radio('Colour scheme', 'Light').checked).toBe(true);
    expect(preview(card('Ledger')).getAttribute('data-scheme')).toBe('light');
    expect(preview(card('Briefing')).getAttribute('data-scheme')).toBe('light');
    expect(preview(card('Classic · Obsidian')).getAttribute('data-scheme')).toBe('dark');

    // jsdom has no matchMedia: "system" falls back to each theme's own default scheme
    fireEvent.click(radio('Colour scheme', 'Same as system'));
    expect(calls).toEqual([['scheme', 'light'], ['scheme', 'system']]);
    expect(preview(card('Ledger')).getAttribute('data-scheme')).toBe('dark');
    expect(preview(card('Briefing')).getAttribute('data-scheme')).toBe('light');
    expect(screen.getByText('Your system’s choice cannot be read here, so this theme shows dark.')).toBeTruthy();
  });

  it('follows the system preference live when it can be read', () => {
    const os = stubSystemScheme(false);
    const { unmount } = renderPanel({ scheme: 'system' });
    expect(preview(card('Ledger')).getAttribute('data-scheme')).toBe('light');
    expect(preview(card('Classic · Graphite')).getAttribute('data-scheme')).toBe('dark');
    expect(screen.getByText('Now light, as your system asks.')).toBeTruthy();

    // the OS switches to dark while the page is open: previews and the note follow at once
    os.change(true);
    expect(preview(card('Ledger')).getAttribute('data-scheme')).toBe('dark');
    expect(preview(card('Briefing')).getAttribute('data-scheme')).toBe('dark');
    expect(screen.getByText('Now dark, as your system asks.')).toBeTruthy();

    unmount();
    expect(os.system.listeners.size, 'the panel stops listening when it closes').toBe(0);
  });

  it('resolves "system" the way the page does when the OS answers neither query', () => {
    // theme/apply.ts reads this as "cannot tell" (null), not as light; the previews must agree
    stubSystemScheme(null);
    renderPanel({ scheme: 'system' });
    expect(preview(card('Ledger')).getAttribute('data-scheme')).toBe('dark');
    expect(preview(card('Briefing')).getAttribute('data-scheme')).toBe('light');
    expect(screen.getByText('Your system’s choice cannot be read here, so this theme shows dark.')).toBeTruthy();
  });
});

describe('Personalisation — Classic themes', () => {
  it('shows the accent only for a Classic theme and disables light with the reason', () => {
    const { calls } = renderPanel({ look: 'obsidian' });
    expect(card('Classic · Obsidian').getAttribute('aria-pressed')).toBe('true');
    const light = radio('Colour scheme', 'Light');
    expect(light.disabled).toBe(true);
    expect(describedBy(light)).toEqual(['Classic themes are dark only, so they always show dark.']);
    expect(radio('Colour scheme', 'Dark').disabled).toBe(false);
    expect(within(group('Accent')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Cyan', 'Amber', 'Green', 'Violet']);
    expect(radio('Accent', 'Cyan').checked).toBe(true);
    fireEvent.click(radio('Accent', 'Amber'));
    expect(calls).toEqual([['accent', 'amber']]);
    expect(preview(card('Classic · Obsidian')).getAttribute('data-accent')).toBe('amber');
    expect(preview(card('Classic · Graphite')).getAttribute('data-accent')).toBe('amber');

    fireEvent.click(card('Ledger'));
    expect(screen.queryByRole('radiogroup', { name: 'Accent' })).toBeNull();
    expect(radio('Colour scheme', 'Light').disabled).toBe(false);
    expect(screen.queryByText('Classic themes are dark only, so they always show dark.')).toBeNull();
  });

  it('previews Classic in the owner’s accent whichever theme is in use, and only Classic', () => {
    // bridge.css restates the chosen accent on a Classic scope that carries data-accent (§6)
    renderPanel({ look: 'ledger', accent: 'violet' });
    for (const theme of ORDER) {
      expect(preview(card(theme.name.en)).getAttribute('data-accent'), theme.id)
        .toBe(theme.family === 'classic' ? 'violet' : null);
    }
  });

  it('previews an accent it does not know as the default, cyan, and checks it', () => {
    renderPanel({ look: 'graphite', accent: 'magenta' });
    expect(preview(card('Classic · Obsidian')).getAttribute('data-accent')).toBe('cyan');
    expect(preview(card('Classic · Graphite')).getAttribute('data-accent')).toBe('cyan');
    expect(radio('Accent', 'Cyan').checked).toBe(true);
  });

  it('keeps a stored light choice reachable by keyboard while a Classic theme shows dark', () => {
    // A radio that is checked and also disabled either takes its group out of the Tab order
    // (browsers that tab only to the checked radio, or to any when none is checked) or makes
    // an unchecked neighbour the Tab stop (Chromium 149), hiding the stored choice. So the
    // stored-but-unavailable choice stays checked and focusable, marked aria-disabled.
    const { calls } = renderPanel({ look: 'obsidian', scheme: 'light' });
    const radios = within(group('Colour scheme')).getAllByRole('radio') as HTMLInputElement[];
    expect(radios.filter((r) => r.checked && r.disabled).map((r) => r.value)).toEqual([]);
    const light = radio('Colour scheme', 'Light');
    expect(light.checked).toBe(true);
    expect(light.disabled).toBe(false);
    expect(light.getAttribute('aria-disabled')).toBe('true');
    light.focus();
    expect(document.activeElement, 'the group has a Tab stop').toBe(light);
    expect(radio('Colour scheme', 'Dark').disabled).toBe(false);
    expect(radio('Colour scheme', 'Same as system').disabled).toBe(false);
    expect(describedBy(light)).toEqual([
      'Classic themes are dark only, so they always show dark. The light scheme stays your choice for the themes that have it.',
    ]);
    fireEvent.click(light);
    expect(calls).toEqual([]);

    // choosing an available scheme leaves the unavailable one plainly disabled and unchecked
    fireEvent.click(radio('Colour scheme', 'Dark'));
    expect(calls).toEqual([['scheme', 'dark']]);
    expect(radio('Colour scheme', 'Light').checked).toBe(false);
    expect(radio('Colour scheme', 'Light').disabled).toBe(true);
    expect(radio('Colour scheme', 'Light').hasAttribute('aria-disabled')).toBe(false);
    expect(describedBy(radio('Colour scheme', 'Light'))).toEqual(['Classic themes are dark only, so they always show dark.']);
  });

  it('says the same in Romanian', () => {
    renderPanel({ lang: 'ro', look: 'graphite', scheme: 'light' });
    expect(radio('Schemă de culori', 'Luminoasă').getAttribute('aria-disabled')).toBe('true');
    expect(screen.getByText('Temele clasice sunt doar întunecate, așa că apar mereu întunecate. Schema luminoasă rămâne alegerea ta pentru temele care o au.')).toBeTruthy();
  });

  it('never leaves a group without a Tab stop, in any theme and scheme', () => {
    const stuck: string[] = [];
    for (const theme of THEMES) {
      for (const scheme of SCHEME_PREFERENCES) {
        const { unmount } = renderPanel({ look: theme.id, scheme });
        document.querySelectorAll<HTMLInputElement>('input[type="radio"]').forEach((r) => {
          if (r.checked && r.disabled) stuck.push(`${theme.id} · ${scheme}: ${r.value}`);
        });
        unmount();
      }
    }
    expect(stuck).toEqual([]);
  });

  it('never offers the accent while a Nerva theme is in use', () => {
    renderPanel({ look: 'presence' });
    expect(screen.queryByRole('radiogroup', { name: 'Accent' })).toBeNull();
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent))
      .toEqual(['Theme', 'Colour scheme', 'Density', 'Motion', 'Typeface', 'Language']);
  });
});

describe('Personalisation — the other axes', () => {
  it('writes density, motion, typeface and language through their own keys', () => {
    const { calls } = renderPanel();
    expect(within(group('Density')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Normal', 'Compact', 'Comfortable']);
    expect(within(group('Motion')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Same as system', 'Calm', 'Lively']);
    expect(within(group('Typeface')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Theme default', 'System sans', 'System serif', 'System mono', 'JetBrains Mono']);
    expect(within(group('Language')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['English', 'Română']);
    expect(screen.getByText('Calm now: your system asks for reduced motion.')).toBeTruthy();

    fireEvent.click(radio('Density', 'Compact'));
    fireEvent.click(radio('Motion', 'Lively'));
    fireEvent.click(radio('Typeface', 'System serif'));
    expect(radio('Density', 'Compact').checked).toBe(true);
    expect(radio('Typeface', 'System serif').checked).toBe(true);
    expect(screen.queryByText('Calm now: your system asks for reduced motion.')).toBeNull();
    fireEvent.click(radio('Language', 'Română'));
    expect(calls).toEqual([['density', 'compact'], ['motion', 'lively'], ['font', 'system-serif'], ['lang', 'ro']]);
    // the page follows the language it was just given
    expect(screen.getByRole('radiogroup', { name: 'Limbă' })).toBeTruthy();
  });

  it('marks the language options with their own language', () => {
    renderPanel();
    expect(radio('Language', 'Română').closest('label')?.querySelector('[lang]')?.getAttribute('lang')).toBe('ro');
  });
});

describe('Personalisation — Romanian', () => {
  it('renders every heading, option and tagline in Romanian when lang is ro', () => {
    renderPanel({ lang: 'ro', look: 'graphite' });
    expect(screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent))
      .toEqual(['Temă', 'Schemă de culori', 'Densitate', 'Mișcare', 'Font', 'Limbă', 'Accent']);
    const cards = within(screen.getByRole('list', { name: 'Temă' })).getAllByRole('button');
    expect(cards).toHaveLength(ORDER.length);
    cards.forEach((c, i) => expect(describedBy(c)[0]).toBe(ORDER[i].tagline.ro));
    expect(screen.getByRole('button', { name: 'Clasic · Graphite' }).getAttribute('aria-pressed')).toBe('true');
    expect(within(screen.getByRole('button', { name: 'Clasic · Graphite' })).getByText('Activă')).toBeTruthy();
    expect(within(group('Schemă de culori')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Întunecată', 'Luminoasă', 'La fel ca sistemul']);
    expect(within(group('Densitate')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Normală', 'Compactă', 'Confortabilă']);
    expect(within(group('Accent')).getAllByRole('radio').map((r) => r.closest('label')?.textContent))
      .toEqual(['Cyan', 'Chihlimbar', 'Verde', 'Violet']);
    expect(screen.getByText('Temele clasice sunt doar întunecate, așa că apar mereu întunecate.')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toBe('Salvat și sincronizat cu hubul.');
  });
});

describe('Personalisation — sync status', () => {
  it('says a change is being saved, and marks the setting changed last', () => {
    renderPanel({}, { status: 'saving' });
    expect(screen.getByRole('status').textContent).toBe('Saving…');
    const density = group('Density').closest('.ap-section') as HTMLElement;
    expect(within(density).queryByText('Saving…')).toBeNull();
    fireEvent.click(radio('Density', 'Comfortable'));
    expect(within(density).getByText('Saving…')).toBeTruthy();
  });

  it('shows a failed sync in words with a retry that calls the context', () => {
    const retry = vi.fn();
    renderPanel({}, { status: 'unsynced', error: 'Appearance saved on this browser only. Sync failed.', retry });
    expect(screen.getByRole('status').textContent).toBe('Appearance saved on this browser only. Sync failed.');
    fireEvent.click(screen.getByRole('button', { name: 'Sync again' }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it('translates the known sync failures into Romanian', () => {
    renderPanel({ lang: 'ro' }, { status: 'unsynced', error: 'Appearance is using this browser’s saved choices. Server unavailable.' });
    expect(screen.getByRole('status').textContent).toBe('Aspectul folosește alegerile salvate în acest browser. Serverul nu răspunde.');
    expect(screen.getByRole('button', { name: 'Sincronizează din nou' })).toBeTruthy();
  });

  it('offers no retry while the document is synced', () => {
    renderPanel();
    expect(screen.getByRole('status').textContent).toBe('Saved and synced to your hub.');
    expect(screen.queryByRole('button', { name: 'Sync again' })).toBeNull();
  });
});

describe('Personalisation — outside the HUD', () => {
  it('renders a read-only notice and no controls without the appearance provider', () => {
    render(<AppearancePanel />);
    expect(screen.getByText('Appearance is available inside the HUD.')).toBeTruthy();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
  });
});

describe('Personalisation — styling stays on the theme contract', () => {
  const read = (file: string) => readFileSync(join(process.cwd(), 'src', 'panels', file), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

  it('styles only from --n-* roles and the type scale: no colour literal, nothing below 12px, no hard-coded label voice', () => {
    const css = read('appearance.css');
    expect(css).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(css).not.toMatch(/\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color-mix|hwb)\(/i);
    expect([...css.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]).filter((name) => !name.startsWith('--n-'))).toEqual([]);
    expect(css, 'a component never sets a role').not.toMatch(/(?:^|[;{\s])--n-[\w-]+\s*:/);
    expect([...css.matchAll(/font-size\s*:\s*([^;}]+)/g)].map((m) => m[1].trim()).filter((v) => !/^var\(--n-fs-[a-z]+\)$/.test(v))).toEqual([]);
    expect(css).not.toMatch(/text-transform\s*:\s*uppercase/i);
    expect([...css.matchAll(/letter-spacing\s*:\s*([^;}]+)/g)].map((m) => m[1].trim()).filter((v) => !/^(?:var\(--n-label-track\)|normal)$/.test(v))).toEqual([]);
  });

  it('keeps colour and inline style out of the component', () => {
    const tsx = read('appearance.tsx');
    expect(tsx).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(tsx).not.toMatch(/\b(?:rgba?|hsla?|oklch|color-mix)\(/i);
    expect(tsx).not.toMatch(/\bstyle=\{/);
  });

  /** Every rule as [selector, declarations]; a rule inside @media is listed under its own selector. */
  const rules = (css: string) => [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((m) => [m[1].trim(), m[2]] as const);
  const declarations = (css: string, selector: string) => rules(css).find(([s]) => s === selector)?.[1] ?? '';
  const colour = (role: string) => new RegExp(`(?:^|[;\\s])color\\s*:\\s*var\\(${role}\\)`);

  it('draws the mini stop as a solid stop fill, and spends the accent on the signature alone', () => {
    // contract §3: the stop is a solid --n-stop fill with --n-on-stop on it, never stop-coloured
    // marks on a tint; a fill that is not a signature would take --n-primary / --n-on-primary
    const css = read('appearance.css');
    const stop = declarations(css, '.ap-mini-stop');
    expect(stop).toMatch(/background\s*:\s*var\(--n-stop\)/);
    expect(stop).toMatch(colour('--n-on-stop'));
    expect(declarations(css, '.ap-mini-stop::after')).toMatch(/currentColor/);
    expect(css).not.toMatch(colour('--n-stop'));
    expect(rules(css).filter(([, body]) => /var\(--n-accent\)/.test(body)).map(([selector]) => selector))
      .toEqual(['.ap-mini-sign']);
    expect(declarations(css, '.ap-mini-sign')).toMatch(colour('--n-on-accent'));
  });

  it('marks what is chosen in the emphasis roles and keeps the chosen word in ink', () => {
    const css = read('appearance.css');
    const chosen = declarations(css, '.ap-opt input:checked + .ap-opt-text');
    expect(chosen).toMatch(/background\s*:\s*var\(--n-emph-wash\)/);
    expect(chosen).toMatch(/border-bottom-color\s*:\s*var\(--n-emph\)/);
    expect(chosen).toMatch(colour('--n-text'));
    expect(declarations(css, '.ap-card[aria-pressed="true"] .ap-frame')).toMatch(/border-color\s*:\s*var\(--n-emph\)/);
    expect(declarations(css, '.ap-card-inuse')).toMatch(colour('--n-emph'));
    expect(declarations(css, '.ap-mini-nav.is-on')).toMatch(colour('--n-emph'));
  });
});
