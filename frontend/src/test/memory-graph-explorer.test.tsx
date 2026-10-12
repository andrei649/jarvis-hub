import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryGraphExplorer } from '../panels/memory-graph';
import * as api from '../api/memory-graph';
import { encodeMapCode } from '../api/memory-map-code';

vi.mock('../api/memory-graph', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/memory-graph')>()),
  loadMemoryMap: vi.fn(), loadFacts: vi.fn(), loadSkills: vi.fn(), loadEntity: vi.fn(),
  saveEntity: vi.fn(), removeEntity: vi.fn(), switchSkill: vi.fn(),
}));

const bounds = { count: 2, firstIngested: 100, lastIngested: 300, firstValid: 100, lastChange: 400 };
const emptyFacts = (axis: api.TimelineAxis = 'known') => ({ axis, facts: [], bounds, clipped: false, skipped: 0 });
const fact = { id: 1, subject: 'andrei', predicate: 'lives_in', object: 'Bucharest', validFrom: 100, validTo: null, ingestedAt: 100 };
const map = (over: Partial<api.MemoryMapData> = {}): api.MemoryMapData => ({
  entities: [
    { name: 'Andrei', type: 'person', firstSeen: 100 }, { name: 'Cluj', type: 'city', firstSeen: 120 },
    { name: 'BMW', type: 'car', firstSeen: 300 }, { name: 'Mystery', type: 'unknown', firstSeen: null },
  ],
  relations: [{ source: 'Andrei', relation: 'lives_in', target: 'Cluj' }, { source: 'Andrei', relation: 'drives', target: 'BMW' }],
  clipped: false, relationsClipped: false, skipped: 0, ...over,
});
const skills: api.SkillInfo[] = [
  { name: 'core', category: '', essential: true, disabled: false },
  { name: 'web-search', category: 'research', essential: false, disabled: false },
];

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.loadMemoryMap).mockImplementation(async () => map());
  vi.mocked(api.loadSkills).mockResolvedValue(skills);
  vi.mocked(api.loadFacts).mockImplementation(async (axis, at) => (at === null ? emptyFacts(axis) : { axis, facts: [fact], bounds, clipped: false, skipped: 0 }));
  vi.mocked(api.loadEntity).mockResolvedValue({ name: 'Andrei', type: 'person', properties: { city: 'Cluj', age: 30, nested: { a: 1 } } });
});
afterEach(() => { vi.useRealTimers(); });

const ready = async () => {
  const view = render(<MemoryGraphExplorer />);
  await screen.findByRole('group', { name: /Memory graph canvas/ });
  return view;
};
const hasText = (el: Element | null, want: string | RegExp) => {
  const got = el?.textContent || '';
  if (typeof want === 'string') expect(got).toContain(want); else expect(got).toMatch(want);
};
const svgOf = (c: HTMLElement) => c.querySelector('svg.kg-svg') as SVGSVGElement;
const box = (c: HTMLElement) => (svgOf(c).getAttribute('viewBox') as string).split(' ').map(Number);
const node = (name: RegExp | string) => screen.getByRole('button', { name: typeof name === 'string' ? new RegExp('^' + name + ',') : name });
const openMenu = (name: string) => { fireEvent.contextMenu(node(name)); return screen.getByRole('menu'); };

describe('canvas of the real stored graph', () => {
  it('draws one node per entity and skill and one edge per relation, with no sample data', async () => {
    const { container } = await ready();
    expect(container.querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(4);
    expect(container.querySelectorAll('.kg-node.kg-skill')).toHaveLength(2);
    expect(container.querySelectorAll('.kg-edge')).toHaveLength(2);
    for (const demo of ['Digitaholic', 'Raiffeisen', 'Cosmina']) expect(screen.queryByText(demo)).toBeNull();
    expect(api.loadMemoryMap).toHaveBeenCalledWith(expect.any(AbortSignal));
  });

  it('shows a loading overlay, then no overlay', async () => {
    let resolve!: (m: api.MemoryMapData) => void;
    vi.mocked(api.loadMemoryMap).mockImplementation(() => new Promise(r => { resolve = r; }));
    render(<MemoryGraphExplorer />);
    expect(screen.getByText('Loading memory graph…')).toBeTruthy();
    await act(async () => resolve(map()));
    expect(screen.queryByText('Loading memory graph…')).toBeNull();
  });

  it('says "Could not load memory graph" and retries on request, without drawing anything', async () => {
    vi.mocked(api.loadMemoryMap).mockRejectedValueOnce({ code: 'unavailable' });
    const { container } = render(<MemoryGraphExplorer />);
    await screen.findByText('Could not load memory graph');
    expect(container.querySelectorAll('.kg-node')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByRole('group', { name: /Memory graph canvas/ });
    expect(container.querySelectorAll('.kg-node').length).toBeGreaterThan(0);
  });

  it('tells a credentials problem from a kernel denial in the error overlay', async () => {
    vi.mocked(api.loadMemoryMap).mockRejectedValueOnce({ code: 'auth' });
    render(<MemoryGraphExplorer />);
    await screen.findByText(/requires your current user credentials/);
  });

  it('shows "Nothing learned yet" for a real empty graph', async () => {
    vi.mocked(api.loadMemoryMap).mockResolvedValue(map({ entities: [], relations: [] }));
    vi.mocked(api.loadSkills).mockResolvedValue([]);
    render(<MemoryGraphExplorer />);
    await screen.findByText('Nothing learned yet');
  });

  it('keeps drawing entities when only the skills read fails, and says so', async () => {
    vi.mocked(api.loadSkills).mockRejectedValue({ code: 'unavailable' });
    const { container } = await ready();
    expect(container.querySelectorAll('.kg-node.kg-skill')).toHaveLength(0);
    expect(screen.getByText(/Skills could not be read/)).toBeTruthy();
  });

  it('discloses a clipped page', async () => {
    vi.mocked(api.loadMemoryMap).mockResolvedValue(map({ clipped: true }));
    await ready();
    expect(screen.getByText(/Showing the first 500 entities/)).toBeTruthy();
  });
});

describe('camera', () => {
  it('zooms with buttons, pans with arrow keys and resets to the fitted view', async () => {
    const { container } = await ready();
    const start = box(container);
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(box(container)[2]).toBeLessThan(start[2]);
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    fireEvent.click(screen.getByRole('button', { name: 'Zoom out' }));
    expect(box(container)[2]).toBeGreaterThan(start[2]);
    fireEvent.click(screen.getByRole('button', { name: 'Reset view' }));
    expect(box(container)).toEqual(start);
    fireEvent.keyDown(svgOf(container), { key: 'ArrowRight' });
    expect(box(container)[0]).toBeGreaterThan(start[0]);
    fireEvent.keyDown(svgOf(container), { key: 'ArrowUp' });
    expect(box(container)[1]).toBeLessThan(start[1]);
    fireEvent.keyDown(svgOf(container), { key: '0' });
    expect(box(container)).toEqual(start);
  });

  it('zooms with the wheel and resets on double click', async () => {
    const { container } = await ready();
    const start = box(container);
    fireEvent.wheel(svgOf(container), { deltaY: -100, clientX: 10, clientY: 10 });
    expect(box(container)[2]).toBeLessThan(start[2]);
    fireEvent.doubleClick(svgOf(container));
    expect(box(container)).toEqual(start);
  });

  it('never zooms beyond its clamp', async () => {
    const { container } = await ready();
    for (let i = 0; i < 40; i++) fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    const w = box(container)[2];
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    expect(box(container)[2]).toBe(w);
  });
});

describe('legend', () => {
  it('lists the distinct entity types with counts, skills, and the edge styles', async () => {
    await ready();
    const legend = screen.getByRole('group', { name: 'Legend' });
    for (const [type, n] of [['person', 1], ['city', 1], ['car', 1], ['unknown', 1]] as const) {
      hasText(within(legend).getByText(type).closest('li'), new RegExp(type + '\\s*' + n));
    }
    hasText(within(legend).getByText('skills').closest('li'), /skills\s*2/);
    expect(within(legend).getByText(/core = oldest/)).toBeTruthy();
    expect(within(legend).queryByText('type')).toBeNull();
  });

  it('gives an untyped entity the neutral swatch', async () => {
    await ready();
    const swatch = within(screen.getByRole('group', { name: 'Legend' })).getByText('unknown').closest('li')!.querySelector('i') as HTMLElement;
    expect(swatch.style.background).toBe('var(--ink-2)');
  });
});

describe('timeline scrubber', () => {
  const slider = () => screen.getByRole('slider', { name: 'Timeline scrubber' }) as HTMLInputElement;

  it('spans the store bounds and starts on the live graph', async () => {
    await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    expect(slider().min).toBe('100');
    expect(slider().value).toBe('400');
    expect(screen.getByText(/live · now/)).toBeTruthy();
    expect(api.loadFacts).toHaveBeenCalledWith('known', null, expect.any(AbortSignal));
  });

  it('asks what the store knew at T and draws those facts as edges', async () => {
    const { container } = await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    fireEvent.change(slider(), { target: { value: '250' } });
    await waitFor(() => expect(api.loadFacts).toHaveBeenCalledWith('known', 250, expect.any(AbortSignal)));
    await waitFor(() => expect(container.querySelectorAll('.kg-edge.fact')).toHaveLength(1));
    expect(container.querySelectorAll('.kg-node')).toHaveLength(2);
    expect(node('andrei')).toBeTruthy();
    expect(screen.getByText('lives_in')).toBeTruthy();
    expect(screen.getByText(/1970-01-01 00:04 UTC/)).toBeTruthy();
  });

  it('switches to "what was true" and re-reads the same instant on the valid axis', async () => {
    await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    fireEvent.change(slider(), { target: { value: '250' } });
    await waitFor(() => expect(api.loadFacts).toHaveBeenCalledWith('known', 250, expect.any(AbortSignal)));
    fireEvent.click(screen.getByRole('radio', { name: 'What was true' }));
    await waitFor(() => expect(api.loadFacts).toHaveBeenCalledWith('valid', 250, expect.any(AbortSignal)));
  });

  it('says so when nothing was known at that moment', async () => {
    vi.mocked(api.loadFacts).mockImplementation(async (axis, at) => (at === null ? emptyFacts(axis) : { axis, facts: [], bounds, clipped: false, skipped: 0 }));
    await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    fireEvent.change(slider(), { target: { value: '110' } });
    await screen.findByText(/Nothing was known by/);
  });

  it('returns to the live graph at the right end of the scrubber', async () => {
    const { container } = await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    fireEvent.change(slider(), { target: { value: '250' } });
    await waitFor(() => expect(container.querySelectorAll('.kg-edge.fact')).toHaveLength(1));
    fireEvent.change(slider(), { target: { value: '400' } });
    await waitFor(() => expect(container.querySelectorAll('.kg-edge.fact')).toHaveLength(0));
    expect(container.querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(4);
  });

  it('is disabled with an explanation when the store holds no facts', async () => {
    vi.mocked(api.loadFacts).mockResolvedValue({ axis: 'known', facts: [], clipped: false, skipped: 0,
      bounds: { count: 0, firstIngested: null, lastIngested: null, firstValid: null, lastChange: null } });
    await ready();
    await waitFor(() => expect(slider().disabled).toBe(true));
    expect(screen.getByText(/No timeline facts yet/)).toBeTruthy();
  });

  it('plays the history forward and pauses', async () => {
    await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    fireEvent.click(screen.getByRole('button', { name: 'Play timeline' }));
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy();
    expect(Number(slider().value)).toBe(100);                       // starts from the beginning
    act(() => { vi.advanceTimersByTime(700); });
    const moved = Number(slider().value);
    expect(moved).toBeGreaterThan(100);
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    act(() => { vi.advanceTimersByTime(2000); });
    expect(Number(slider().value)).toBe(moved);
    expect(screen.getByRole('button', { name: 'Play timeline' })).toBeTruthy();
  });

  it('stops playing and returns to live at the end', async () => {
    await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    fireEvent.click(screen.getByRole('button', { name: 'Play timeline' }));
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(slider().value).toBe('400');
    expect(screen.getByRole('button', { name: 'Play timeline' })).toBeTruthy();
  });
});

describe('node context menu', () => {
  it('opens on right-click with the entity actions and closes on Escape, returning focus', async () => {
    await ready();
    const n = node('Andrei');
    const menu = openMenu('Andrei');
    const items = within(menu).getAllByRole('menuitem').map(i => i.textContent);
    expect(items).toEqual(expect.arrayContaining(['Explore neighbours', 'Edit…', 'Delete…', 'Copy map code']));
    expect(items).not.toContain('Disable skill');
    fireEvent.keyDown(menu, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
    expect(document.activeElement).toBe(n);
  });

  it.each([{ key: 'ContextMenu' }, { key: 'F10', shiftKey: true }])('opens from the keyboard (%o)', async keys => {
    await ready();
    fireEvent.keyDown(node('Cluj'), keys);
    expect(screen.getByRole('menu')).toBeTruthy();
  });

  it('opens from the visible actions button of the selected node', async () => {
    await ready();
    fireEvent.click(node('BMW'));
    fireEvent.click(screen.getByRole('button', { name: 'Actions for BMW' }));
    expect(within(screen.getByRole('menu')).getByRole('menuitem', { name: 'Delete…' })).toBeTruthy();
  });

  it('"Explore neighbours" centres the node and dims what is not connected', async () => {
    const { container } = await ready();
    fireEvent.click(within(openMenu('Cluj')).getByRole('menuitem', { name: 'Explore neighbours' }));
    expect(screen.getByRole('button', { name: 'Show whole map' })).toBeTruthy();
    const dim = Array.from(container.querySelectorAll('.kg-node.faded')).map(g => g.getAttribute('data-label'));
    expect(dim).toEqual(expect.arrayContaining(['BMW', 'Mystery']));
    expect(dim).not.toContain('Andrei');
    expect(dim).not.toContain('Cluj');
  });
});

describe('node editor', () => {
  beforeEach(async () => { await ready(); });
  const openEditor = async () => {
    fireEvent.click(within(openMenu('Andrei')).getByRole('menuitem', { name: 'Edit…' }));
    return screen.findByRole('dialog', { name: /Edit Andrei/ });
  };

  it('saves type and properties through the mediated route, keeping non-text values', async () => {
    vi.mocked(api.saveEntity).mockResolvedValue({ name: 'Andrei', type: 'friend', properties: {} });
    const dialog = await openEditor();
    expect(within(dialog).getByText(/nested/)).toBeTruthy();         // kept as is, not editable
    fireEvent.change(within(dialog).getByLabelText('Entity type'), { target: { value: 'friend' } });
    fireEvent.change(within(dialog).getByLabelText('Value of city'), { target: { value: 'Brasov' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.saveEntity).toHaveBeenCalledWith('Andrei', 'friend', { city: 'Brasov', age: 30, nested: { a: 1 } }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(vi.mocked(api.loadMemoryMap).mock.calls.length).toBeGreaterThan(1);   // refreshed
  });

  it('shows a kernel refusal verbatim, stays open and leaves the node as it was', async () => {
    vi.mocked(api.saveEntity).mockRejectedValue({ code: 'denied', detail: 'kernel denied: halted' });
    const dialog = await openEditor();
    fireEvent.change(within(dialog).getByLabelText('Entity type'), { target: { value: 'friend' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    const alert = await within(dialog).findByRole('alert');
    hasText(alert, 'Refused');
    hasText(alert, 'kernel denied: halted');
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(within(screen.getByRole('group', { name: 'Legend' })).getByText('person')).toBeTruthy();
    expect(api.loadMemoryMap).toHaveBeenCalledTimes(1);
  });

  it('shows the server message for an invalid type and blocks an unsafe one locally', async () => {
    vi.mocked(api.saveEntity).mockRejectedValue({ code: 'invalid', detail: 'invalid entity type' });
    const dialog = await openEditor();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    hasText(await within(dialog).findByRole('alert'), 'invalid entity type');
    vi.mocked(api.saveEntity).mockClear();
    fireEvent.change(within(dialog).getByLabelText('Entity type'), { target: { value: 'bad type!' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    hasText(await within(dialog).findByRole('alert'), /Type must start with a letter/);
    expect(api.saveEntity).not.toHaveBeenCalled();
  });

  it('can add and remove a text property', async () => {
    vi.mocked(api.saveEntity).mockResolvedValue({ name: 'Andrei', type: 'person', properties: {} });
    const dialog = await openEditor();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Remove city' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add property' }));
    fireEvent.change(within(dialog).getByLabelText('New property name'), { target: { value: 'role' } });
    fireEvent.change(within(dialog).getByLabelText('New property value'), { target: { value: 'owner' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.saveEntity).toHaveBeenCalledWith('Andrei', 'person', { age: 30, nested: { a: 1 }, role: 'owner' }));
  });

  it('closes without a request on Cancel', async () => {
    const dialog = await openEditor();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.saveEntity).not.toHaveBeenCalled();
  });
});

describe('delete memory', () => {
  beforeEach(async () => { await ready(); });
  const container = () => document.body;
  const askDelete = async (name = 'BMW') => {
    fireEvent.click(within(openMenu(name)).getByRole('menuitem', { name: 'Delete…' }));
    return screen.findByRole('alertdialog');
  };

  it('sends nothing when the confirmation is cancelled', async () => {
    const dialog = await askDelete();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(api.removeEntity).not.toHaveBeenCalled();
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('explains what delete does, including that a later mention can re-create it', async () => {
    const dialog = await askDelete();
    hasText(dialog, /relations/);
    hasText(dialog, /timeline/i);
    hasText(dialog, /later mention can create it again/);
  });

  it('removes the node and its edges only after the server says 200, then refreshes the timeline', async () => {
    vi.mocked(api.removeEntity).mockResolvedValue({ factsRetracted: 2 });
    await waitFor(() => expect(api.loadFacts).toHaveBeenCalled());
    const before = vi.mocked(api.loadFacts).mock.calls.length;
    const dialog = await askDelete();
    vi.mocked(api.loadMemoryMap).mockImplementation(async () => map({
      entities: map().entities.filter(e => e.name !== 'BMW'),
      relations: [{ source: 'Andrei', relation: 'lives_in', target: 'Cluj' }] }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }));
    await waitFor(() => expect(api.removeEntity).toHaveBeenCalledWith('BMW'));
    await waitFor(() => expect(container().querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(3));
    expect(container().querySelectorAll('.kg-edge')).toHaveLength(1);
    hasText(screen.getByText(/Deleted BMW/), /2 timeline facts closed/);
    expect(vi.mocked(api.loadFacts).mock.calls.length).toBeGreaterThan(before);
  });

  it('keeps the node and shows the refusal when the kernel denies the delete', async () => {
    vi.mocked(api.removeEntity).mockRejectedValue({ code: 'denied', detail: 'kernel denied: halted' });
    const dialog = await askDelete();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }));
    hasText(await within(dialog).findByRole('alert'), 'kernel denied: halted');
    expect(container().querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(4);
    expect(api.loadMemoryMap).toHaveBeenCalledTimes(1);
  });

  it('does not offer edit or delete while looking at a past moment', async () => {
    const slider = await screen.findByRole('slider', { name: 'Timeline scrubber' });
    await waitFor(() => expect((slider as HTMLInputElement).max).toBe('400'));
    fireEvent.change(slider, { target: { value: '250' } });
    await waitFor(() => expect(screen.getAllByRole('button', { name: /^andrei,/ })).toHaveLength(1));
    const items = within(openMenu('andrei')).getAllByRole('menuitem').map(i => i.textContent);
    expect(items).not.toContain('Delete…');
    expect(items).not.toContain('Edit…');
  });
});

describe('skills on the map', () => {
  it('disables a skill through the existing switch and says it stays installed', async () => {
    vi.mocked(api.switchSkill).mockResolvedValue({ changed: ['web-search'], essential: [], pending: false, taskId: '' });
    await ready();
    fireEvent.click(within(openMenu('web-search')).getByRole('menuitem', { name: 'Disable skill' }));
    await waitFor(() => expect(api.switchSkill).toHaveBeenCalledWith('web-search', false));
    hasText(await screen.findByText(/Disabled skill web-search/), /stays installed/);
    expect(vi.mocked(api.loadSkills).mock.calls.length).toBeGreaterThan(1);
  });

  it('offers nothing to disable on an essential skill or an entity', async () => {
    await ready();
    expect(within(openMenu('core')).queryByRole('menuitem', { name: 'Disable skill' })).toBeNull();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(within(openMenu('Andrei')).queryByRole('menuitem', { name: 'Disable skill' })).toBeNull();
  });

  it('renders the refusal when the admin switch is not allowed', async () => {
    vi.mocked(api.switchSkill).mockRejectedValue({ code: 'admin' });
    await ready();
    fireEvent.click(within(openMenu('web-search')).getByRole('menuitem', { name: 'Disable skill' }));
    expect(await screen.findByText(/needs the admin token/)).toBeTruthy();
  });

  it('says re-enabling needs the owner when the hub answers pending', async () => {
    vi.mocked(api.loadSkills).mockResolvedValue([{ name: 'web-search', category: 'research', essential: false, disabled: true }]);
    vi.mocked(api.switchSkill).mockResolvedValue({ changed: [], essential: [], pending: true, taskId: 'T-9' });
    await ready();
    fireEvent.click(within(openMenu('web-search')).getByRole('menuitem', { name: 'Enable skill' }));
    expect(await screen.findByText(/owner approval · task T-9/)).toBeTruthy();
  });
});

describe('share / import a map code', () => {
  const writeText = vi.fn();
  beforeEach(() => { writeText.mockReset().mockResolvedValue(undefined); Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true }); });
  const openShare = () => { fireEvent.click(screen.getByRole('button', { name: 'Share / import map' })); return screen.getByRole('textbox', { name: 'Map code' }) as HTMLTextAreaElement; };

  it('prefills the code of the visible map and copies it', async () => {
    await ready();
    const box = openShare();
    expect(box.value).toMatch(/^NML1\./);
    fireEvent.click(screen.getByRole('button', { name: 'Copy map code' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(box.value));
    expect(box.value).not.toContain('PRIVATE');
  });

  it('loads a pasted code as a read-only imported map and returns to the live map', async () => {
    const { container } = await ready();
    const box = openShare();
    const code = encodeMapCode({
      nodes: [{ kind: 'memory', label: 'Elsewhere', category: 'place', state: 'active', t: 10 },
        { kind: 'memory', label: '<img src=x onerror=alert(1)>', category: 'thing', state: 'active', t: 4000 }],
      edges: [{ from: 0, to: 1, label: 'near' }] });
    fireEvent.change(box, { target: { value: code } });
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await screen.findByText('imported map');
    expect(screen.getByText(/Loaded a map with 2 nodes/)).toBeTruthy();
    expect(container.querySelectorAll('.kg-node')).toHaveLength(2);
    expect(container.querySelector('img')).toBeNull();                  // labels are text, never markup
    const items = within(openMenu('Elsewhere')).getAllByRole('menuitem').map(i => i.textContent);
    expect(items).not.toContain('Edit…');
    expect(items).not.toContain('Delete…');
    expect(api.saveEntity).not.toHaveBeenCalled();
    expect(api.removeEntity).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Back to my map' }));
    await waitFor(() => expect(container.querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(4));
    expect(screen.queryByText('imported map')).toBeNull();
  });

  it('scrubs an imported map by its own relative time', async () => {
    const { container } = await ready();
    const box = openShare();
    fireEvent.change(box, { target: { value: encodeMapCode({
      nodes: [{ kind: 'memory', label: 'Early', category: 'x', state: 'active', t: 10 }, { kind: 'memory', label: 'Late', category: 'x', state: 'active', t: 4000 }], edges: [] }) } });
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await screen.findByText('imported map');
    const slider = screen.getByRole('slider', { name: 'Timeline scrubber' });
    fireEvent.change(slider, { target: { value: '100' } });
    expect(container.querySelectorAll('.kg-node')).toHaveLength(1);
    expect(api.loadFacts).toHaveBeenCalledTimes(1);                       // no network for an imported map
  });

  it('rejects a malformed or hostile code with a message and keeps the live map', async () => {
    const { container } = await ready();
    const box = openShare();
    for (const bad of ['hello', 'NML1.00000000.@@@', '']) {
      fireEvent.change(box, { target: { value: bad } });
      fireEvent.click(screen.getByRole('button', { name: 'Load' }));
      hasText(await screen.findByRole('alert'), /map code/i);
    }
    expect(screen.queryByText('imported map')).toBeNull();
    expect(container.querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(4);
  });

  it('shows an imported empty map as imported, not as "Nothing learned yet"', async () => {
    await ready();
    const box = openShare();
    fireEvent.change(box, { target: { value: encodeMapCode({ nodes: [], edges: [] }) } });
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));
    await screen.findByText('imported map');
    expect(screen.queryByText('Nothing learned yet')).toBeNull();
    expect(screen.getByText(/imported map has no nodes/i)).toBeTruthy();
  });
});


describe('fix round 1: honest states', () => {
  const slider = () => screen.getByRole('slider', { name: 'Timeline scrubber' }) as HTMLInputElement;

  it('shows "Nothing learned yet" on an empty graph even though skills are installed', async () => {
    vi.mocked(api.loadMemoryMap).mockResolvedValue(map({ entities: [], relations: [] }));
    const { container } = render(<MemoryGraphExplorer />);
    await screen.findByText('Nothing learned yet');
    expect(container.querySelectorAll('.kg-node.kg-skill')).toHaveLength(2);     // the skills are still drawn
  });

  it('says how many stored entries could not be shown', async () => {
    vi.mocked(api.loadMemoryMap).mockResolvedValue(map({ skipped: 2 }));
    await ready();
    expect(screen.getByText(/2 stored entries could not be shown/)).toBeTruthy();
  });

  it('plays a timeline shorter than 40 seconds to its end instead of sticking on Pause', async () => {
    const short = { count: 2, firstIngested: 1000, lastIngested: 1010, firstValid: 1000, lastChange: 1010 };
    vi.mocked(api.loadFacts).mockImplementation(async (axis, at) => ({ axis, facts: at === null ? [] : [fact], bounds: short, clipped: false, skipped: 0 }));
    await ready();
    await waitFor(() => expect(slider().max).toBe('1010'));
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    fireEvent.click(screen.getByRole('button', { name: 'Play timeline' }));
    act(() => { vi.advanceTimersByTime(350); });
    expect(Number(slider().value)).toBeGreaterThan(1000);                         // it moved
    act(() => { vi.advanceTimersByTime(30_000); });
    expect(slider().value).toBe('1010');
    expect(screen.getByRole('button', { name: 'Play timeline' })).toBeTruthy();   // and it ended
  });

  it('refits the camera when the timeline facts arrive after the mode switch', async () => {
    const many = Array.from({ length: 60 }, (_, i) => ({ ...fact, id: i + 1, subject: 'S' + i, object: 'O' + i }));
    vi.mocked(api.loadFacts).mockImplementation(async (axis, at) => ({ axis, facts: at === null ? [] : many, bounds, clipped: false, skipped: 0 }));
    const { container } = await ready();
    await waitFor(() => expect(slider().max).toBe('400'));
    fireEvent.change(slider(), { target: { value: '250' } });
    await waitFor(() => expect(container.querySelectorAll('.kg-node').length).toBe(120));
    const [, , w] = box(container);
    expect(w).toBeGreaterThan(640);                                              // zoomed out to hold the outer rings
  });
});

describe('fix round 1: a delete that did not happen is never reported as done', () => {
  const askDelete = async (name = 'BMW') => {
    fireEvent.click(within(openMenu(name)).getByRole('menuitem', { name: 'Delete…' }));
    return screen.findByRole('alertdialog');
  };

  it('shows a 404 in the dialog, keeps the node, and offers a refresh instead of "Deleted"', async () => {
    await ready();
    vi.mocked(api.removeEntity).mockRejectedValue({ code: 'notfound' });
    const dialog = await askDelete();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }));
    hasText(await within(dialog).findByRole('alert'), /nothing was deleted/i);
    expect(screen.queryByText(/Deleted BMW/)).toBeNull();
    expect(document.body.querySelectorAll('.kg-node:not(.kg-skill)')).toHaveLength(4);
    const loads = vi.mocked(api.loadMemoryMap).mock.calls.length;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Refresh map' }));
    await waitFor(() => expect(vi.mocked(api.loadMemoryMap).mock.calls.length).toBeGreaterThan(loads));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(api.removeEntity).toHaveBeenCalledTimes(1);
  });

  it('does not claim "nothing was changed" after a lost reply: it says the result is unknown and reloads', async () => {
    await ready();
    vi.mocked(api.removeEntity).mockRejectedValue({ code: 'unknown' });
    const dialog = await askDelete();
    const loads = vi.mocked(api.loadMemoryMap).mock.calls.length;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete memory' }));
    const alert = await within(dialog).findByRole('alert');
    hasText(alert, /result is unknown/);
    expect(alert.textContent).not.toMatch(/Nothing was changed/);
    await waitFor(() => expect(vi.mocked(api.loadMemoryMap).mock.calls.length).toBeGreaterThan(loads));
  });

  it('says the same after a save whose reply was lost', async () => {
    await ready();
    vi.mocked(api.saveEntity).mockRejectedValue({ code: 'unknown' });
    fireEvent.click(within(openMenu('Andrei')).getByRole('menuitem', { name: 'Edit…' }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByLabelText('Entity type');
    const loads = vi.mocked(api.loadMemoryMap).mock.calls.length;
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }));
    hasText(await within(dialog).findByRole('alert'), /result is unknown/);
    await waitFor(() => expect(vi.mocked(api.loadMemoryMap).mock.calls.length).toBeGreaterThan(loads));
  });

  it('tells the owner what the default in-memory graph forgets', async () => {
    await ready();
    const dialog = await askDelete();
    hasText(dialog, /lasts until the hub restarts/);
  });
});
