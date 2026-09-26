// @ts-nocheck
/* H209 — one registry for every HUD shortcut; a panel (mod+/) lists, searches and rebinds
   them; no chord can reach an approval or a decision. */
import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react';
import {
  ACTIONS, CATEGORIES, FORBIDDEN_TARGET, STORAGE_KEY, bindings, chordFromEvent, conflictsFor, defineActions,
  displayChord, loadOverrides, matchAction, normalizeChord, readOverrides, rebind, resetBinding, saveOverrides,
  searchBindings,
} from '../shortcuts';
import { ShortcutsPanel } from '../shortcuts-panel';

beforeEach(() => { cleanup(); localStorage.clear(); });

const ev = (key, mods = {}) => ({ key, ...mods });

describe('the registry — H209', () => {
  it('holds every HUD shortcut with its default chord', () => {
    const defaults = Object.fromEntries(ACTIONS.map((a) => [a.id, a.chord]));
    expect(defaults).toEqual({
      'mode.cockpit': '1', 'mode.agents': '2', 'mode.trust': '3', 'mode.memory': '4', 'mode.autonomy': '5',
      'mode.build': '6', 'mode.observe': '7', 'mode.interop': '8', 'mode.chat': '9', 'mode.comms': '0',
      'view.world': 'w', 'view.console': '`', 'view.ambient': 'a', 'view.cinema': 'm',
      'cinema.orb': 'o', 'cinema.mesh': 'n', 'cinema.brain': 'b',
      'composer.focus': '/', 'session.palette': 'mod+k', 'session.shortcuts': 'mod+/',
    });
    expect(CATEGORIES).toEqual(['Navigation', 'View', 'Composer', 'Session']);
    for (const c of CATEGORIES) expect(ACTIONS.some((a) => a.category === c)).toBe(true);
    expect(ACTIONS.filter((a) => a.scope === 'cinema').map((a) => a.id)).toEqual(['cinema.orb', 'cinema.mesh', 'cinema.brain']);
    expect(STORAGE_KEY).toBe('hud.shortcuts');
  });

  it('refuses an action that targets an approval or a decision', () => {
    for (const bad of [
      { id: 'inbox.approve', category: 'Session', label: 'x', chord: 'y', scope: 'global' },
      { id: 'x.y', category: 'Session', label: 'Accept the card', chord: 'y', scope: 'global' },
      { id: 'decision.next', category: 'Session', label: 'x', chord: 'y', scope: 'global' },
      { id: 'x.reject', category: 'Session', label: 'x', chord: 'y', scope: 'global' },
      { id: 'x.z', category: 'Session', label: 'Deny it', chord: 'y', scope: 'global' },
      { id: 'x.w', category: 'Session', label: 'Give consent', chord: 'y', scope: 'global' },
      { id: 'x.v', category: 'Session', label: 'Decide now', chord: 'y', scope: 'global' },
    ]) expect(() => defineActions([bad])).toThrow(/approval or decision/);
    for (const a of ACTIONS) expect(FORBIDDEN_TARGET.test(`${a.id} ${a.category} ${a.label}`)).toBe(false);
  });

  it('refuses duplicates, unknown categories and a default that is not normal', () => {
    const ok = { id: 'x.one', category: 'View', label: 'One', chord: 'q', scope: 'global' };
    expect(defineActions([ok])).toEqual([ok]);
    expect(() => defineActions([ok, ok])).toThrow(/duplicate/);
    expect(() => defineActions([{ ...ok, category: 'Other' }])).toThrow(/category/);
    expect(() => defineActions([{ ...ok, chord: 'Ctrl+Q' }])).toThrow(/not normal/);
  });
});

describe('chords', () => {
  it('have one spelling', () => {
    expect(normalizeChord('Ctrl+K')).toBe('mod+k');
    expect(normalizeChord('shift+alt+cmd+P')).toBe('mod+alt+shift+p');
    expect(normalizeChord('meta+/')).toBe('mod+/');
    expect(normalizeChord('mod++')).toBe('mod++');
    expect(normalizeChord('space')).toBe(' ');
    expect(normalizeChord('')).toBe('');
  });

  it('are read from key events', () => {
    expect(chordFromEvent(ev('k', { ctrlKey: true }))).toBe('mod+k');
    expect(chordFromEvent(ev('K', { metaKey: true, shiftKey: true }))).toBe('mod+shift+k');
    expect(chordFromEvent(ev('?', { shiftKey: true }))).toBe('?');           // the shift is in the symbol
    expect(chordFromEvent(ev('ArrowUp', { shiftKey: true, altKey: true }))).toBe('alt+shift+arrowup');
    expect(chordFromEvent(ev('1'))).toBe('1');
    for (const key of ['Shift', 'Control', 'Meta', 'Alt', 'Dead', 'Unidentified', '', undefined]) {
      expect(chordFromEvent(ev(key, { ctrlKey: true }))).toBeNull();
    }
  });

  it('are shown the platform way', () => {
    expect(displayChord('mod+k', true)).toBe('⌘K');
    expect(displayChord('mod+alt+shift+p', false)).toBe('Ctrl+Alt+Shift+P');
    expect(displayChord(' ', false)).toBe('Space');
    expect(displayChord('arrowup', false)).toBe('arrowup');
    expect(displayChord('alt+x', true)).toBe('⌥X');
    expect(displayChord('shift+x', true)).toBe('⇧X');
  });
});

describe('overrides', () => {
  it('keep only known actions and normal chords', () => {
    expect(readOverrides({ 'view.ambient': 'Ctrl+J', 'nope': 'x', 'view.cinema': 3, 'mode.chat': '', 'mode.trust': 'x'.repeat(41) }))
      .toEqual({ 'view.ambient': 'mod+j' });
    for (const raw of [null, 'x', [], 7]) expect(readOverrides(raw)).toEqual({});
  });

  it('persist per viewer and survive storage that is off or broken', () => {
    saveOverrides({ 'view.ambient': 'j' });
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY))).toEqual({ 'view.ambient': 'j' });
    expect(loadOverrides()).toEqual({ 'view.ambient': 'j' });
    saveOverrides({});
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    localStorage.setItem(STORAGE_KEY, '{broken');
    expect(loadOverrides()).toEqual({});
    const throwing = { getItem: () => { throw new Error('off'); }, setItem: () => { throw new Error('off'); }, removeItem: () => { throw new Error('off'); } };
    expect(loadOverrides(throwing)).toEqual({});
    expect(() => saveOverrides({ 'view.ambient': 'j' }, throwing)).not.toThrow();
  });

  it('rebind, reset one, and a rebind back to the default is no override', () => {
    let o = rebind({}, 'view.ambient', 'Ctrl+J');
    expect(o).toEqual({ 'view.ambient': 'mod+j' });
    expect(rebind(o, 'view.ambient', 'a')).toEqual({});
    expect(rebind(o, 'no.such', 'x')).toBe(o);
    o = rebind(o, 'view.cinema', 'z');
    expect(resetBinding(o, 'view.ambient')).toEqual({ 'view.cinema': 'z' });
    const list = bindings(o);
    expect(list.find((b) => b.id === 'view.ambient')).toMatchObject({ current: 'mod+j', custom: true, chord: 'a' });
    expect(list.find((b) => b.id === 'mode.chat')).toMatchObject({ current: '9', custom: false });
  });
});

describe('dispatch', () => {
  it('matches the first action on a chord, in its scope only', () => {
    const list = bindings({});
    expect(matchAction(ev('2'), list, 'global').id).toBe('mode.agents');
    expect(matchAction(ev('k', { metaKey: true }), list, 'global').id).toBe('session.palette');
    expect(matchAction(ev('/', { ctrlKey: true }), list, 'global').id).toBe('session.shortcuts');
    expect(matchAction(ev('o'), list, 'global')).toBeNull();
    expect(matchAction(ev('o'), list, 'cinema').id).toBe('cinema.orb');
    expect(matchAction(ev('2'), list, 'cinema')).toBeNull();
    expect(matchAction(ev('Shift'), list, 'global')).toBeNull();
    const moved = bindings({ 'mode.agents': 'x' });
    expect(matchAction(ev('2'), moved, 'global')).toBeNull();
    expect(matchAction(ev('x'), moved, 'global').id).toBe('mode.agents');
    const clash = bindings({ 'view.cinema': 'a' });
    expect(matchAction(ev('a'), clash, 'global').id).toBe('view.ambient');
    expect(conflictsFor('view.cinema', 'a', clash).map((b) => b.id)).toEqual(['view.ambient']);
    expect(conflictsFor('view.cinema', 'm', bindings({}))).toEqual([]);
  });

  it('searches by label, category, id and chord', () => {
    const list = bindings({});
    expect(searchBindings(list, '').length).toBe(ACTIONS.length);
    expect(searchBindings(list, 'palette').map((b) => b.id)).toEqual(['session.palette']);
    expect(searchBindings(list, 'COMPOSER').map((b) => b.id)).toEqual(['composer.focus']);
    expect(searchBindings(list, 'cinema.').map((b) => b.id)).toEqual(['cinema.orb', 'cinema.mesh', 'cinema.brain']);
    expect(searchBindings(list, 'ctrl+k').map((b) => b.id)).toEqual(['session.palette']);
    expect(searchBindings(list, '`').map((b) => b.id)).toEqual(['view.console']);
  });
});

describe('the Keyboard Shortcuts panel', () => {
  function setup(initial = {}) {
    let overrides = initial;
    const changes = [];
    let closed = 0;
    const view = render(<ShortcutsPanel overrides={overrides} onChange={(n) => { changes.push(n); overrides = n; view.rerender(<ShortcutsPanel overrides={n} onChange={(m) => { changes.push(m); }} onClose={() => { closed += 1; }} />); }} onClose={() => { closed += 1; }} />);
    return { view, changes, closed: () => closed };
  }

  it('lists every action by category', () => {
    setup();
    for (const c of CATEGORIES) expect(screen.getByRole('region', { name: c })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /^Rebind / }).length).toBe(ACTIONS.length);
    expect(screen.getByText(/Approvals and decisions have no shortcut/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Reset all' }).disabled).toBe(true);
  });

  it('searches', () => {
    setup();
    fireEvent.change(screen.getByLabelText('Search shortcuts'), { target: { value: 'cinema' } });
    expect(screen.getAllByRole('button', { name: /^Rebind / }).length).toBe(4);
    expect(screen.queryByRole('region', { name: 'Session' })).toBeNull();
    fireEvent.change(screen.getByLabelText('Search shortcuts'), { target: { value: 'zzz' } });
    expect(screen.getByText(/No shortcut matches/)).toBeTruthy();
  });

  it('records a new chord, ignoring lone modifiers, and Escape cancels', () => {
    const { changes, closed } = setup();
    fireEvent.click(screen.getByRole('button', { name: 'Rebind Ambient mode' }));
    expect(screen.getByRole('button', { name: 'Rebind Ambient mode' }).textContent).toBe('Press a key…');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(changes).toEqual([]);
    expect(closed()).toBe(0);                                  // Escape cancelled the recording only
    fireEvent.click(screen.getByRole('button', { name: 'Rebind Ambient mode' }));
    fireEvent.keyDown(window, { key: 'Control', ctrlKey: true });
    expect(changes).toEqual([]);
    fireEvent.keyDown(window, { key: 'j', ctrlKey: true });
    expect(changes).toEqual([{ 'view.ambient': 'mod+j' }]);
  });

  it('names a clash, resets one binding and resets all', () => {
    const { changes } = setup({ 'view.cinema': 'a', 'mode.chat': 'q' });
    const row = document.querySelector('[data-action="view.cinema"]');
    expect(within(row).getByRole('note').textContent).toBe('Also bound to Ambient mode');
    expect(within(document.querySelector('[data-action="mode.cockpit"]')).queryByRole('note')).toBeNull();
    expect(screen.getByRole('button', { name: 'Reset Go to Cockpit' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Reset Cinema mode' }));
    expect(changes[0]).toEqual({ 'mode.chat': 'q' });
    fireEvent.click(screen.getByRole('button', { name: 'Reset all' }));
    expect(changes[1]).toEqual({});
  });

  it('closes on Escape and on the backdrop, not on a click inside', () => {
    const { closed } = setup();
    fireEvent.click(screen.getByRole('dialog'));
    expect(closed()).toBe(0);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(closed()).toBe(1);
    fireEvent.click(screen.getByRole('dialog').parentElement);
    expect(closed()).toBe(2);
  });
});
