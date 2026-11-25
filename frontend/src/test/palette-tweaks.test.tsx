// @ts-nocheck
/* O26-P3.2 — the dropped TweaksPanel is covered by the search and command sheet (Ctrl K): look,
   density, motion, scanline, dot grid, language and scheme are all owner-changeable there, with the
   HUD v2 palette's row labels word for word (PHASE_B_PLAN.md §3.7, §8.2 row 11). Moved from the
   palette to nav/CommandSheet when the palette was deleted. The sheet lists the appearance rows for
   a query, so each case types first; a ✓ marks the active choice. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { cleanup, render, screen, fireEvent } from '@testing-library/react';
import { CommandSheet } from '../nav/CommandSheet';
import { LANGUAGES } from '../data';

beforeEach(() => { localStorage.clear(); });

function renderSheet(ui, extra = {}) {
  const props = {
    open: true, filter: null, onClose: vi.fn(), lang: 'en', navigate: vi.fn(), agents: [],
    onOpenAgent: vi.fn(), onWriteTo: vi.fn(),
    actions: { onGlance: vi.fn(), onCinema: vi.fn(), onShortcuts: vi.fn(), onVerifyRecord: vi.fn(), onRefresh: vi.fn(),
      demo: false, setDemo: vi.fn(), onPersonalisation: vi.fn() },
    ui, accent: 'cyan', setAccent: vi.fn(), setLang: vi.fn(), shortcutOverrides: {},
    ...extra,
  };
  render(<CommandSheet {...props} />);
  return props;
}
const search = (q) => fireEvent.change(screen.getByRole('combobox'), { target: { value: q } });
/** The row whose label reads exactly `label`. */
const row = (label) => screen.getByText(label, { selector: '.n-cmd-label' });

describe('Sheet display tweaks', () => {
  it('offers look, density, motion, scanline, and dot grid controls', () => {
    const ui = {
      look: 'obsidian', setLook: vi.fn(),
      density: 'normal', setDensity: vi.fn(),
      motion: 'lively', setMotion: vi.fn(),
      scanline: 'on', setScanline: vi.fn(),
      dotgrid: 'off', setDotgrid: vi.fn(),
    };
    for (const [query, label, setter, value] of [
      ['look', 'Look · Graphite', 'setLook', 'graphite'],
      ['density', 'Density · Comfy', 'setDensity', 'comfy'],
      ['motion', 'Motion · Calm', 'setMotion', 'calm'],
      ['scanline', 'Scanline · Off', 'setScanline', 'off'],
      ['dot grid', 'Dot grid · On', 'setDotgrid', 'on'],
    ]) {
      const { onClose } = renderSheet(ui);
      search(query);
      fireEvent.click(row(label));
      expect(ui[setter], label).toHaveBeenCalledWith(value);
      expect(onClose).toHaveBeenCalled();
      cleanup();
    }
  });

  // H221 — the Language row is an appearance row like the others: one entry per translated
  // language (its own name), the active one ticked, chosen by code rather than toggled.
  it('offers a Language row per translated language, the active one ticked', () => {
    const { setLang } = renderSheet({ look: 'obsidian', density: 'normal', motion: 'lively', scanline: 'on', dotgrid: 'off' }, { lang: 'ro' });
    search('language');
    for (const l of LANGUAGES) expect(row('Language · ' + l.label + (l.code === 'ro' ? ' ✓' : ''))).toBeTruthy();
    expect(screen.queryByText(/Toggle language/)).toBeNull();
    fireEvent.click(row('Language · English'));
    expect(setLang).toHaveBeenCalledWith('en');
  });

  // Theme contract v1 §7–8: every theme is a Look row; a missing look is Ledger, not Classic.
  it('offers a Look row per theme, ticking Ledger when no look is set', () => {
    const ui = { setLook: vi.fn(), density: 'normal', motion: 'lively', scanline: 'on', dotgrid: 'off' };
    renderSheet(ui);
    search('look');
    expect(row('Look · Ledger ✓')).toBeTruthy();
    for (const name of ['Presence', 'Briefing', 'Workbench', 'Threshold', 'Console', 'Atlas', 'Obsidian', 'Graphite']) {
      expect(row('Look · ' + name)).toBeTruthy();
    }
    fireEvent.click(row('Look · Atlas'));
    expect(ui.setLook).toHaveBeenCalledWith('atlas');
  });

  it('ticks the chosen Classic look under its existing name', () => {
    renderSheet({ look: 'obsidian', setLook: vi.fn() });
    search('look');
    expect(row('Look · Obsidian ✓')).toBeTruthy();
    expect(row('Look · Ledger')).toBeTruthy();
  });

  it('offers the colour scheme, Dark by default', () => {
    const ui = { look: 'ledger', setScheme: vi.fn() };
    renderSheet(ui);
    search('scheme');
    expect(row('Scheme · Dark ✓')).toBeTruthy();
    expect(row('Scheme · Light')).toBeTruthy();
    fireEvent.click(row('Scheme · System'));
    expect(ui.setScheme).toHaveBeenCalledWith('system');
  });

  it('ticks a chosen scheme', () => {
    renderSheet({ look: 'briefing', scheme: 'light' });
    search('scheme');
    expect(row('Scheme · Light ✓')).toBeTruthy();
    expect(row('Scheme · Dark')).toBeTruthy();
  });

  it('opens Personalisation and closes', () => {
    const { actions, onClose } = renderSheet({ look: 'ledger' });
    search('personalisation');
    fireEvent.click(row('Personalisation…'));
    expect(actions.onPersonalisation).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalled();
  });
});
