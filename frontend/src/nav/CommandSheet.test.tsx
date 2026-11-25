import React, { useState } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CommandSheet, type CommandSheetProps } from './CommandSheet';
import { RECENT_KEY, readRecent } from './commands';

function props(over: Partial<CommandSheetProps> = {}): CommandSheetProps {
  return {
    open: true, filter: null, onClose: vi.fn(), lang: 'en', navigate: vi.fn(),
    agents: [{ id: 'frigga', name: 'Frigga', enabled: true, rosterSource: 'api' }],
    onOpenAgent: vi.fn(), onWriteTo: vi.fn(),
    actions: { onGlance: vi.fn(), onCinema: vi.fn(), onShortcuts: vi.fn(), onVerifyRecord: vi.fn(), onRefresh: vi.fn(), demo: false, setDemo: vi.fn(), onPersonalisation: vi.fn() },
    ui: { look: 'ledger', scheme: 'dark', setScheme: vi.fn() },
    accent: 'cyan', setAccent: vi.fn(), setLang: vi.fn(), shortcutOverrides: {},
    ...over,
  };
}
const input = () => screen.getByRole('combobox') as HTMLInputElement;
const options = () => screen.queryAllByRole('option');
const names = () => options().map((o) => o.getAttribute('data-command'));
const type = (value: string) => fireEvent.change(input(), { target: { value } });
const key = (k: string, init: KeyboardEventInit = {}) => fireEvent.keyDown(input(), { key: k, ...init });

beforeEach(() => localStorage.clear());

describe('CommandSheet', () => {
  it('draws nothing while closed', () => {
    const { container } = render(<CommandSheet {...props({ open: false })} />);
    expect(container.firstChild).toBeNull();
  });

  it('is a modal dialog with a combobox that owns a listbox, focused on open', () => {
    render(<CommandSheet {...props()} />);
    const dialog = screen.getByRole('dialog', { name: 'Search or run a command' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    const box = input();
    expect(document.activeElement).toBe(box);
    expect(box.getAttribute('aria-controls')).toBe(screen.getByRole('listbox').id);
    expect(box.getAttribute('aria-expanded')).toBe('true');
    expect(box.getAttribute('aria-autocomplete')).toBe('list');
    expect(box.getAttribute('aria-activedescendant')).toBe(options()[0].id);
    expect(options()[0].getAttribute('aria-selected')).toBe('true');
  });

  it('lists the areas and the actions when nothing is typed, and the recents first', () => {
    localStorage.setItem(RECENT_KEY, JSON.stringify(['page:panel:logs']));
    render(<CommandSheet {...props()} />);
    const groups = screen.getAllByRole('group').map((g) => g.textContent);
    expect(groups[0]).toContain('Recent');
    expect(names()[0]).toBe('page:panel:logs');
    expect(names().filter((n) => n?.startsWith('area:'))).toHaveLength(9);
    expect(names()).toContain('action:glance');
    expect(names().some((n) => n?.startsWith('page:panel:') && n !== 'page:panel:logs')).toBe(false);
  });

  it('finds a page by its Romanian name typed without diacritics', () => {
    render(<CommandSheet {...props({ lang: 'ro' })} />);
    type('incredere');
    expect(names()[0]).toBe('area:trust');
    type('Încredere');
    expect(names()[0]).toBe('area:trust');
    expect(screen.getByRole('status').textContent).toMatch(/rezultate|de rezultate/);
  });

  it('moves with the arrow keys (wrapping), and runs the active one with Enter', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    type('trust');
    expect(names()[0]).toBe('area:trust');
    expect(options().length).toBeGreaterThan(2);
    key('ArrowDown');
    expect(input().getAttribute('aria-activedescendant')).toBe(options()[1].id);
    key('ArrowUp'); key('ArrowUp');
    expect(input().getAttribute('aria-activedescendant')).toBe(options()[options().length - 1].id);
    key('ArrowDown');
    expect(input().getAttribute('aria-activedescendant')).toBe(options()[0].id);
    key('Enter');
    expect(p.navigate).toHaveBeenCalledWith('/v2/trust');
    expect(p.onClose).toHaveBeenCalledTimes(1);
    expect(readRecent()).toEqual(['area:trust']);
  });

  it('runs a command on a click, and ignores Enter while an input method composes', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    type('cinema');
    fireEvent.keyDown(input(), { key: 'Enter', isComposing: true });
    expect(p.actions.onCinema).not.toHaveBeenCalled();
    fireEvent.click(options().find((o) => o.getAttribute('data-command') === 'action:cinema') as HTMLElement);
    expect(p.actions.onCinema).toHaveBeenCalledTimes(1);
  });

  it('opens an agent without writing to it, and writes to it on the other row', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    type('frigga');
    fireEvent.click(screen.getByText('Open Frigga'));
    expect(p.onOpenAgent).toHaveBeenCalledWith('frigga');
    expect(p.onWriteTo).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Write to Frigga'));
    expect(p.onWriteTo).toHaveBeenCalledWith('frigga');
  });

  it('with the Panels filter lists only panels, shows the filter, and lifts it with Backspace', () => {
    render(<CommandSheet {...props({ filter: 'panels' })} />);
    const tag = screen.getByRole('button', { name: 'Remove the Panels filter' });
    expect(tag.textContent).toContain('Panels:');
    expect(options().length).toBeGreaterThan(100);
    expect(names().every((n) => n?.startsWith('page:panel:'))).toBe(true);
    type('kill');
    expect(names()[0]).toBe('page:panel:kill-switch');
    expect(names().every((n) => n?.startsWith('page:panel:'))).toBe(true);
    type('');
    key('Backspace');
    expect(screen.queryByRole('button', { name: 'Remove the Panels filter' })).toBeNull();
    expect(names()).toContain('area:work');
  });

  it('lifts the filter with its own control and keeps the focus in the field', () => {
    render(<CommandSheet {...props({ filter: 'panels' })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Remove the Panels filter' }));
    expect(names()).toContain('area:work');
    expect(document.activeElement).toBe(input());
  });

  it('says plainly when nothing matches', () => {
    render(<CommandSheet {...props()} />);
    type('zzzzqq');
    expect(options()).toHaveLength(0);
    expect(screen.getByText('Nothing matches “zzzzqq”.')).toBeTruthy();
    expect(input().getAttribute('aria-expanded')).toBe('false');
  });

  it('never offers a verdict, a signature, the stop or a mode change', () => {
    render(<CommandSheet {...props()} />);
    for (const word of ['approve', 'sign', 'reject', 'defer', 'consent', 'stop', 'resume', 'decide']) {
      type(word);
      const hits = options().filter((o) => ['action', 'agent'].includes(o.getAttribute('data-kind') as string));
      expect(hits.map((o) => o.textContent), word).toEqual([]);
    }
    type('decisions');
    expect(names()[0]).toBe('page:panel:decision-inbox');
    expect(options()[0].getAttribute('data-kind')).toBe('page');
  });

  it('keeps the old appearance rows word for word and applies one', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    type('scheme');
    expect(options().map((o) => within(o).getByText(/^Scheme/).textContent)).toEqual(['Scheme · Dark ✓', 'Scheme · Light', 'Scheme · System']);
    fireEvent.click(options()[1]);
    expect(p.ui.setScheme).toHaveBeenCalledWith('light');
  });

  describe('closing', () => {
    function Host({ onClose }: { onClose?: () => void }) {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Find</button>
          <textarea data-composer aria-label="Composer" />
          <CommandSheet {...props({ open, onClose: () => { onClose?.(); setOpen(false); }, onWriteTo: () => (document.querySelector('[data-composer]') as HTMLElement).focus() })} />
        </>
      );
    }

    it('on Esc closes and returns the focus to the opener', () => {
      const onClose = vi.fn();
      render(<Host onClose={onClose} />);
      const opener = screen.getByRole('button', { name: 'Find' });
      opener.focus();
      fireEvent.click(opener);
      expect(screen.getByRole('dialog')).toBeTruthy();
      expect(document.activeElement).toBe(input());
      key('Escape');
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(opener);
    });

    it('on a click on the scrim closes it, and a click inside does not', () => {
      const onClose = vi.fn();
      render(<Host onClose={onClose} />);
      fireEvent.click(screen.getByRole('button', { name: 'Find' }));
      fireEvent.mouseDown(screen.getByRole('dialog'));
      expect(onClose).not.toHaveBeenCalled();
      fireEvent.mouseDown(document.querySelector('[data-cmd="scrim"]') as HTMLElement);
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('after a command ran leaves the focus where the command put it', () => {
      render(<Host />);
      const opener = screen.getByRole('button', { name: 'Find' });
      opener.focus();
      fireEvent.click(opener);
      type('frigga');
      fireEvent.click(screen.getByText('Write to Frigga'));
      expect(screen.queryByRole('dialog')).toBeNull();
      expect(document.activeElement).toBe(screen.getByLabelText('Composer'));
    });

    it('starts clean each time it opens', () => {
      render(<Host />);
      fireEvent.click(screen.getByRole('button', { name: 'Find' }));
      type('logs');
      key('Escape');
      fireEvent.click(screen.getByRole('button', { name: 'Find' }));
      expect(input().value).toBe('');
    });
  });

  it('keeps Tab inside the dialog', () => {
    render(<CommandSheet {...props({ filter: 'panels' })} />);
    const tag = screen.getByRole('button', { name: 'Remove the Panels filter' });
    const close = screen.getByRole('button', { name: 'Close' });
    act(() => input().focus());
    fireEvent.keyDown(input(), { key: 'Tab' });
    expect(document.activeElement).toBe(close);
    fireEvent.keyDown(close, { key: 'Tab' });
    expect(document.activeElement).toBe(tag);
    fireEvent.keyDown(tag, { key: 'Tab' });
    expect(document.activeElement).toBe(input());
    fireEvent.keyDown(input(), { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(tag);
  });

  it('does not let a key reach the page behind it, whatever is focused', () => {
    const seen = vi.fn();
    const spy = (e: KeyboardEvent) => seen(e.key);
    document.addEventListener('keydown', spy);
    try {
      render(<CommandSheet {...props({ filter: 'panels' })} />);
      const tag = screen.getByRole('button', { name: 'Remove the Panels filter' });
      act(() => tag.focus());
      fireEvent.keyDown(tag, { key: '5' });
      fireEvent.keyDown(input(), { key: 'm' });
      expect(seen).not.toHaveBeenCalled();
    } finally { document.removeEventListener('keydown', spy); }
  });

  it('keeps the focus in the dialog when a part that cannot take it is clicked, and Esc still closes', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    const dialog = screen.getByRole('dialog');
    expect(dialog.getAttribute('tabindex')).toBe('-1');
    const notPrevented = fireEvent.mouseDown(dialog.querySelector('.n-cmd-foot') as HTMLElement);
    expect(notPrevented).toBe(false);
    expect(document.activeElement).toBe(input());
    key('Escape');
    expect(p.onClose).toHaveBeenCalled();
  });

  it('does not close on Esc while an input method composes', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    key('Escape', { isComposing: true });
    expect(p.onClose).not.toHaveBeenCalled();
    key('Escape');
    expect(p.onClose).toHaveBeenCalledTimes(1);
  });

  it('has a visible close control', () => {
    const p = props();
    render(<CommandSheet {...p} />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(p.onClose).toHaveBeenCalledTimes(1);
  });

  it('gives the focus back to the opener after a command that places none, but not over one that does', () => {
    vi.useFakeTimers();
    try {
      const opener = document.createElement('button');
      document.body.appendChild(opener);
      opener.focus();
      const p = props();
      const App = () => { const [open, setOpen] = useState(true); return <CommandSheet {...p} open={open} onClose={() => setOpen(false)} />; };
      const first = render(<App />);
      type('refresh');
      key('Enter');
      expect(p.actions.onRefresh).toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(100); });
      expect(document.activeElement).toBe(opener);
      first.unmount();
      const target = document.createElement('textarea');
      document.body.appendChild(target);
      opener.focus();
      const q = props({ onWriteTo: () => target.focus() });
      const Second = () => { const [open, setOpen] = useState(true); return <CommandSheet {...q} open={open} onClose={() => setOpen(false)} />; };
      render(<Second />);
      type('write to frigga');
      key('Enter');
      act(() => { vi.advanceTimersByTime(100); });
      expect(document.activeElement).toBe(target);
    } finally { vi.useRealTimers(); }
  });

  it('lists one entry for one label (Glance is a page and an action)', () => {
    render(<CommandSheet {...props()} />);
    type('glance');
    expect(names().filter((n) => /glance/.test(n || ''))).toHaveLength(1);
  });

  it('speaks Romanian when asked', () => {
    render(<CommandSheet {...props({ lang: 'ro', filter: 'panels' })} />);
    expect(screen.getByRole('dialog', { name: 'Caută sau rulează o comandă' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Scoate filtrul Panouri' }).textContent).toContain('Panouri:');
  });
});
