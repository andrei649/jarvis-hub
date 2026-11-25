/* App routing under the Ledger frame, the default since the cutover (PHASE_B_PLAN.md §8.3).

   Every way of moving through the HUD drives the same URL: the masthead's nine areas, an area's
   contents column, the search and command sheet (Ctrl K; the backtick opens it on panels), the
   number keys in masthead order, `a` for Glance, a Console panel
   as a page of its area, and the desktop window's hand-off. Mode pages and the panels are ordinary
   pages, so Back and Forward walk them through normal history; Glance is the one overlay route,
   and its Escape returns to the page that opened it, entry by entry. The H209 rebinding cases
   use the Agents key and the Keyboard shortcuts panel; a key hint now shows on the masthead's Find
   button, the sheet's rows and the contents column instead of the retired buttons.

   Heavy modes and panels are stand-ins: this pins the route wiring, not each page's content. */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';
import { resetPolling } from '../signals/poll';

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {}, status: 'idle' }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => ({}), createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../modes', () => ({ AgentsMode: () => <div>Agents route loaded</div>, Dossier: () => null, MemoryMode: () => <input aria-label="Memory draft" /> }));
vi.mock('../modes3', () => ({ CommsMode: () => null, AdminMode: () => null }));
vi.mock('../panels/jobs', () => ({ JobsWorkspace: () => <div>Jobs route loaded<input aria-label="Jobs draft" /></div> }));
vi.mock('../gap', () => ({
  ConsolePanel: ({ panelId }: { panelId: string }) => <div>Console route {panelId}</div>,
  FirstRunGate: () => null,
  ProjectsMode: () => <div>Projects route loaded</div>,
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function (this: HTMLDialogElement) { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function (this: HTMLDialogElement) { this.removeAttribute('open'); };
});
beforeEach(() => {
  resetPolling();
  localStorage.clear();
  localStorage.setItem('hud.seen', '1');
  history.replaceState(null, '', '/v2/chat?demo=1');
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
});
afterEach(() => { resetPolling(); });

const frame = (part: string) => document.querySelector(`[data-frame="${part}"]`) as HTMLElement | null;
const sheet = () => screen.queryByRole('dialog', { name: 'Search or run a command' }) as HTMLElement | null;
const shortcutsPanel = () => screen.queryByRole('dialog', { name: 'Keyboard shortcuts' });
/** The masthead's Find: its accessible name begins with the words it shows and ends with its key. */
const findButton = () => screen.getByRole('button', { name: /^Search or run a command/ });
/** The masthead's link to an area, and the area it marks current. */
const area = (id: string) => document.querySelector(`[data-frame="masthead"] a[data-area="${id}"]`) as HTMLElement;
const currentArea = () => document.querySelector('[data-frame="masthead"] a[data-area][aria-current="page"]')?.getAttribute('data-area') ?? null;
/** The page the contents column marks current. */
const currentPage = () => frame('contents')?.querySelector('[aria-current="page"]')?.getAttribute('data-page') ?? null;

/** Home › Conversation: the conversation register and its composer, inside the frame. */
async function chatPage() {
  await waitFor(() => expect(document.querySelector('[data-frame="page"] [data-chatpage="chat"] [data-register="talk"] [data-composer]')).not.toBeNull());
}
/** Glance: full screen, without the frame. */
async function glance() {
  await waitFor(() => expect(document.querySelector('[data-glance]')).not.toBeNull());
  expect(frame('masthead')).toBeNull();
}
/** In the sheet opened on panels (the backtick), find a panel and run it. */
function runPanel(query: string, id: string) {
  const open = sheet() as HTMLElement;
  expect(open, 'the sheet is open').not.toBeNull();
  expect(open.querySelector('[data-cmd="scope"]'), 'the sheet is filtered to panels').not.toBeNull();
  fireEvent.change(within(open).getByRole('combobox'), { target: { value: query } });
  const row = open.querySelector(`[data-command="page:panel:${id}"]`) as HTMLElement | null;
  expect(row, `the panel ${id} is found by "${query}"`).not.toBeNull();
  fireEvent.click(row as HTMLElement);
}

it('connects the masthead, the contents column, the sheet, hotkeys, panel pages and the desktop handoff to the same URL', async () => {
  render(<App />);
  await chatPage();
  expect(currentArea()).toBe('home');
  // the masthead: an area's landing page
  fireEvent.click(area('work'));
  await waitFor(() => expect(location.pathname).toBe('/v2/work'));
  await waitFor(() => expect(frame('contents')?.getAttribute('data-area')).toBe('work'));
  expect(currentArea()).toBe('work');
  // the contents column: another page of the area
  fireEvent.click(within(frame('contents') as HTMLElement).getByRole('link', { name: 'Projects' }));
  await screen.findByText('Projects route loaded');
  expect(location.pathname).toBe('/v2/projects');
  expect(currentPage()).toBe('mode:projects');
  // a number key, in masthead order: 3 is Agents
  fireEvent.keyDown(window, { key: '3' });
  await screen.findByText('Agents route loaded');
  expect(location.pathname).toBe('/v2/agents');
  // the sheet: Ctrl K, find the area, run it
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  fireEvent.change(within(sheet() as HTMLElement).getByRole('combobox'), { target: { value: 'memory' } });
  fireEvent.click((sheet() as HTMLElement).querySelector('[data-command="area:memory"]') as HTMLElement);
  await screen.findByLabelText('Memory draft');
  expect(location.pathname).toBe('/v2/memory');
  expect(sheet()).toBeNull();
  // a number key again: an ordinary history entry Back leaves
  fireEvent.keyDown(window, { key: '3' });
  await screen.findByText('Agents route loaded');
  expect(location.pathname).toBe('/v2/agents');
  expect(currentArea()).toBe('agents');
  act(() => history.back());
  await screen.findByLabelText('Memory draft');
  expect(location.pathname).toBe('/v2/memory');
  // the backtick: the sheet on panels; a panel opens as a page of its area, Back returns
  fireEvent.keyDown(window, { key: '`' });
  runPanel('decisions', 'decision-inbox');
  await screen.findByText('Console route decision-inbox');
  expect(location.pathname).toBe('/v2/console/decision-inbox');
  expect(currentArea()).toBe('work');
  act(() => history.back());
  await screen.findByLabelText('Memory draft');
  expect(location.pathname).toBe('/v2/memory');
  // the desktop window hands the conversation over
  act(() => window.dispatchEvent(new Event('nerva-desktop-handoff')));
  await chatPage();
  expect(location.pathname).toBe('/v2/chat');
}, 30_000);

it('loads a mode bookmark as a page of its area and walks it through Back/Forward', async () => {
  history.replaceState(null, '', '/v2/jobs?demo=1');
  render(<App />);
  await screen.findByText('Jobs route loaded');
  expect(document.title).toBe('Scheduled jobs · Work · Nerva');
  expect(currentArea()).toBe('work');
  expect(currentPage()).toBe('mode:jobs');
  expect(within(frame('page') as HTMLElement).getByText('Jobs route loaded')).toBeTruthy();
  // a page, not an overlay: Escape does not leave it
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(location.pathname).toBe('/v2/jobs');
  fireEvent.click(area('home'));
  await waitFor(() => expect(location.pathname).toBe('/v2/cockpit'));
  await waitFor(() => expect(screen.queryByText('Jobs route loaded')).toBeNull());
  act(() => history.back());
  await screen.findByText('Jobs route loaded');
  expect(location.pathname).toBe('/v2/jobs');
  act(() => history.forward());
  await waitFor(() => expect(screen.queryByText('Jobs route loaded')).toBeNull());
  expect(location.pathname).toBe('/v2/cockpit');
}, 20_000);

it('loads a selected console bookmark as a page of its area and clears form state across route changes', async () => {
  history.replaceState(null, '', '/v2/console/decision-inbox?demo=1');
  render(<App />);
  await screen.findByText('Console route decision-inbox');
  expect(document.title).toBe('Decisions · Work · Nerva');
  expect(currentArea()).toBe('work');
  expect(currentPage()).toBe('panel:decision-inbox');
  // the panel page moves the focus to its heading, as the Console overlay did
  await waitFor(() => expect(document.activeElement?.textContent).toBe('Decisions'));
  expect(document.activeElement?.tagName).toBe('H1');
  fireEvent.keyDown(window, { key: '4' });
  fireEvent.change(await screen.findByLabelText('Memory draft'), { target: { value: 'private draft' } });
  fireEvent.keyDown(window, { key: '3' });
  await screen.findByText('Agents route loaded');
  act(() => history.back());
  expect((await screen.findByLabelText('Memory draft') as HTMLInputElement).value).toBe('');
}, 20_000);

it('keeps floating desktop on canonical chat and preserves its query context', async () => {
  history.replaceState(null, '', '/v2/memory?desktop=floating&demo=1#anchor');
  render(<App floating />);
  await waitFor(() => expect(document.querySelector('[data-chatpage="floating"] [data-register="talk"] [data-composer]')).not.toBeNull());
  expect(location.pathname).toBe('/v2/chat');
  expect(location.search).toBe('?desktop=floating&demo=1');
  expect(location.hash).toBe('#anchor');
  expect(frame('masthead')).toBeNull();
});

it('remounts a mode page\'s content when the existing demo context changes', async () => {
  history.replaceState(null, '', '/v2/jobs?demo=1');
  render(<App />);
  fireEvent.change(await screen.findByLabelText('Jobs draft'), { target: { value: 'demo draft' } });
  fireEvent.click(screen.getByRole('button', { name: /exit demo/i }));
  await waitFor(() => expect((screen.getByLabelText('Jobs draft') as HTMLInputElement).value).toBe(''));
  expect(location.pathname).toBe('/v2/jobs');
});

it('restores the invoking page of a historical Glance visit', async () => {
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: 'a' });
  await glance();
  expect(location.pathname).toBe('/v2/glance');
  fireEvent.keyDown(window, { key: 'Escape' });
  await chatPage();
  expect(location.pathname).toBe('/v2/chat');
  fireEvent.keyDown(window, { key: '4' });
  await screen.findByLabelText('Memory draft');
  fireEvent.keyDown(window, { key: 'a' });
  await glance();
  fireEvent.keyDown(window, { key: 'Escape' });
  await screen.findByLabelText('Memory draft');
  expect(location.pathname).toBe('/v2/memory');
  // Entries: chat, Glance-from-chat, chat, memory, Glance-from-memory, memory.
  act(() => history.go(-4));
  await glance();
  fireEvent.keyDown(window, { key: 'Escape' });
  await chatPage();
  expect(location.pathname).toBe('/v2/chat');
}, 30_000);

it('opens a panel page from the panels sheet; Back returns to the page that opened it, Forward to the panel', async () => {
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: '`' });
  runPanel('logs', 'logs');
  await screen.findByText('Console route logs');
  expect(location.pathname).toBe('/v2/console/logs');
  expect(document.title).toBe('Logs · Observe · Nerva');
  expect(sheet()).toBeNull();
  act(() => history.back());
  await chatPage();
  expect(location.pathname).toBe('/v2/chat');
  act(() => history.forward());
  await screen.findByText('Console route logs');
  fireEvent.keyDown(window, { key: '4' });
  await screen.findByLabelText('Memory draft');
  fireEvent.keyDown(window, { key: '`' });
  runPanel('payments', 'payments');
  await screen.findByText('Console route payments');
  expect(currentArea()).toBe('trust');
  act(() => history.back());
  await screen.findByLabelText('Memory draft');
  expect(location.pathname).toBe('/v2/memory');
}, 30_000);

it('under a base path, Escape closes the panels sheet where it was and a panel page keeps the prefix', async () => {
  window.__NERVA_BASE_PATH__ = '/one';
  try {
    history.replaceState(null, '', '/one/v2/chat?demo=1');
    render(<App />);
    await chatPage();
    fireEvent.keyDown(window, { key: '`' });
    expect(sheet()?.querySelector('[data-cmd="scope"]')).not.toBeNull();
    fireEvent.keyDown(within(sheet() as HTMLElement).getByRole('combobox'), { key: 'Escape' });
    expect(sheet()).toBeNull();
    expect(location.pathname).toBe('/one/v2/chat');
    fireEvent.keyDown(window, { key: '`' });
    runPanel('logs', 'logs');
    await screen.findByText('Console route logs');
    expect(location.pathname).toBe('/one/v2/console/logs');
    act(() => history.back());
    await chatPage();
    expect(location.pathname).toBe('/one/v2/chat');
  } finally { delete window.__NERVA_BASE_PATH__; }
}, 20_000);

it('closes prefixed Glance with Escape and restores the invoking page; a prefixed mode page is a page', async () => {
  window.__NERVA_BASE_PATH__ = '/one';
  try {
    history.replaceState(null, '', '/one/v2/chat?demo=1');
    render(<App />);
    await chatPage();
    fireEvent.keyDown(window, { key: 'a' });
    await glance();
    expect(location.pathname).toBe('/one/v2/glance');
    fireEvent.keyDown(window, { key: 'Escape' });
    await chatPage();
    expect(location.pathname).toBe('/one/v2/chat');
    fireEvent.keyDown(window, { key: '3' });
    await screen.findByText('Agents route loaded');
    expect(location.pathname).toBe('/one/v2/agents');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(location.pathname).toBe('/one/v2/agents');
  } finally { delete window.__NERVA_BASE_PATH__; }
}, 20_000);

it('H209: mod+/ opens the shortcuts panel, a rebinding moves the key, and it persists', async () => {
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  const dialog = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: '3' });                          // the panel owns the keyboard
  expect(location.pathname).toBe('/v2/chat');
  fireEvent.click(screen.getByRole('button', { name: 'Rebind Go to Agents' }));
  fireEvent.keyDown(window, { key: 'x' });
  expect(JSON.parse(localStorage.getItem('hud.shortcuts') || '{}')).toEqual({ 'mode.agents': 'x' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(shortcutsPanel()).toBeNull());
  expect(dialog.isConnected).toBe(false);
  fireEvent.keyDown(window, { key: '3' });
  expect(location.pathname).toBe('/v2/chat');
  fireEvent.keyDown(window, { key: 'x' });
  await screen.findByText('Agents route loaded');
  expect(location.pathname).toBe('/v2/agents');
});

it('H209: a rebound Agents key opens Agents and the old one no longer does', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.agents': 'y' }));
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: '3' });
  expect(location.pathname).toBe('/v2/chat');
  // the removed World key answers nothing either
  fireEvent.keyDown(window, { key: 'w' });
  expect(location.pathname).toBe('/v2/chat');
  // the hint names the new key: the Keyboard shortcuts panel lists it
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  expect((await screen.findByRole('button', { name: 'Rebind Go to Agents' })).textContent).toBe('Y');
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(shortcutsPanel()).toBeNull());
  fireEvent.keyDown(window, { key: 'y' });
  await screen.findByText('Agents route loaded');
  expect(location.pathname).toBe('/v2/agents');
});

it('H209: a key typed into a field is the field\'s, not a page switch', async () => {
  history.replaceState(null, '', '/v2/memory?demo=1');
  render(<App />);
  const box = await screen.findByLabelText('Memory draft');
  box.focus();
  for (const key of ['2', '3', 'a', '`']) fireEvent.keyDown(box, { key });
  await act(async () => {});
  expect(location.pathname).toBe('/v2/memory');
  expect(screen.queryByText('Agents route loaded')).toBeNull();
  expect(sheet()).toBeNull();
});

it('H209: a rebinding made in the panel reaches the masthead\'s Find key and the running foot at once', async () => {
  render(<App />);
  await chatPage();
  expect(findButton().getAttribute('aria-label')).toMatch(/· Ctrl\+K$/);
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.click(screen.getByRole('button', { name: 'Rebind Command palette' }));
  fireEvent.keyDown(window, { key: 'p', ctrlKey: true });
  expect(JSON.parse(localStorage.getItem('hud.shortcuts') || '{}')).toEqual({ 'session.palette': 'mod+p' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(shortcutsPanel()).toBeNull());
  expect(findButton().getAttribute('aria-label')).toMatch(/· Ctrl\+P$/);
  // the masthead's key cap is drawn from data-key (frame.css), not written as text
  expect(findButton().querySelector('kbd')?.getAttribute('data-key')).toBe('Ctrl+P');
  expect(document.querySelector('[data-frame="runfoot"] [data-runfoot="key-hint"] kbd')?.textContent).toBe('Ctrl+P');
  // and the key itself moved
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  expect(sheet()).toBeNull();
  fireEvent.keyDown(window, { key: 'p', ctrlKey: true });
  expect(sheet()).not.toBeNull();
});

it('H209: / focuses the message box', async () => {
  history.replaceState(null, '', '/v2/cockpit?demo=1');
  render(<App />);
  const box = await waitFor(() => { const el = document.querySelector('[data-composer]'); if (!el) throw new Error('no composer'); return el; });
  fireEvent.keyDown(window, { key: '/' });
  expect(document.activeElement).toBe(box);
});

it('H209: Ctrl+Space on the panel itself opens it, and a stored "mod+" no longer locks it out (F1)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'session.shortcuts': 'mod+' }));
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.click(screen.getByRole('button', { name: 'Rebind Keyboard shortcuts' }));
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true });
  expect(JSON.parse(localStorage.getItem('hud.shortcuts') || '{}')).toEqual({ 'session.shortcuts': 'mod+space' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(shortcutsPanel()).toBeNull());
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
});

it('H209: the sheet still opens the panel when its chord is taken (F2)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.cockpit': 'mod+/', 'session.shortcuts': 'mod+k' }));
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });            // Home's now (the first action wins)
  await waitFor(() => expect(location.pathname).toBe('/v2/cockpit'));
  expect(shortcutsPanel()).toBeNull();
  fireEvent.click(findButton());
  const open = sheet() as HTMLElement;
  expect(open).not.toBeNull();
  // with nothing typed the sheet lists its actions, the panel among them
  fireEvent.click(open.querySelector('[data-command="action:shortcuts"]') as HTMLElement);
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  expect(sheet()).toBeNull();
});

it('H209: a sheet rebound to a bare key never fires while typing (F3)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'session.palette': 'p' }));
  history.replaceState(null, '', '/v2/memory?demo=1');
  render(<App />);
  const box = await screen.findByLabelText('Memory draft');
  // the bare key was refused: Find still names Ctrl K
  expect(findButton().getAttribute('aria-label')).toMatch(/· Ctrl\+K$/);
  box.focus();
  expect(fireEvent.keyDown(box, { key: 'p' })).toBe(true);           // the letter is typed, not eaten
  expect(sheet()).toBeNull();
  fireEvent.keyDown(box, { key: 'k', ctrlKey: true });
  await waitFor(() => expect(sheet()).not.toBeNull());
});

it('H209: a HUD action on a rebound chord is not also the browser\'s (F4)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.agents': 'mod+d', 'mode.memory': 'mod+y' }));
  render(<App />);
  await chatPage();
  expect(fireEvent.keyDown(window, { key: 'd', ctrlKey: true })).toBe(false);
  await screen.findByText('Agents route loaded');
  expect(fireEvent.keyDown(window, { key: 'y', ctrlKey: true })).toBe(false);
  await screen.findByLabelText('Memory draft');
});

it('H209: Glance\'s key waits while the panel is open (F5)', async () => {
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: 'a' });
  expect(location.pathname).toBe('/v2/chat');
});

it('H209: with storage off, an Agents rebinding still takes for this page (F6)', async () => {
  const setItem = Storage.prototype.setItem;
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
    if (key === 'hud.shortcuts') throw new Error('storage off');
    return setItem.call(this, key, value);
  });
  try {
    render(<App />);
    await chatPage();
    fireEvent.keyDown(window, { key: '/', ctrlKey: true });
    await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    fireEvent.click(screen.getByRole('button', { name: 'Rebind Go to Agents' }));
    fireEvent.keyDown(window, { key: 'y' });
    expect(screen.getByRole('button', { name: 'Rebind Go to Agents' }).textContent).toBe('Y');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(shortcutsPanel()).toBeNull());
    fireEvent.keyDown(window, { key: '3' });
    expect(location.pathname).toBe('/v2/chat');
    fireEvent.keyDown(window, { key: 'y' });
    await screen.findByText('Agents route loaded');
  } finally { spy.mockRestore(); }
});

it('H209: the HUD\'s key hints follow a rebinding (F7)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.agents': 'x', 'view.console': 'c', 'session.palette': 'mod+p' }));
  render(<App />);
  await chatPage();
  // the masthead's Find, and the contents column's "Ctrl K finds any of the N"
  expect(findButton().getAttribute('aria-label')).toMatch(/· Ctrl\+P$/);
  expect(findButton().querySelector('kbd')?.getAttribute('data-key')).toBe('Ctrl+P');
  expect(frame('contents')?.querySelector('kbd')?.textContent).toBe('Ctrl+P');
  // the sheet's rows carry their keys
  fireEvent.click(findButton());
  const open = sheet() as HTMLElement;
  const hint = (id: string) => open.querySelector(`[data-command="${id}"] kbd`)?.textContent;
  expect(hint('area:agents')).toBe('X');
  expect(hint('area:home')).toBe('1');
  fireEvent.keyDown(within(open).getByRole('combobox'), { key: 'Escape' });
  expect(sheet()).toBeNull();
  // and the keys themselves: c opens the sheet on panels, x goes to Agents
  fireEvent.keyDown(window, { key: 'c' });
  expect(sheet()?.querySelector('[data-cmd="scope"]')).not.toBeNull();
  fireEvent.keyDown(within(sheet() as HTMLElement).getByRole('combobox'), { key: 'Escape' });
  fireEvent.keyDown(window, { key: 'x' });
  await screen.findByText('Agents route loaded');
});

it('H209: the Escape that closes the panel leaves Glance open beneath it, and a page where it was (F8)', async () => {
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: 'a' });
  await glance();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(shortcutsPanel()).toBeNull());
  expect(location.pathname).toBe('/v2/glance');
  expect(document.querySelector('[data-glance]')).not.toBeNull();
  // Glance's own Escape still returns to the page that opened it
  fireEvent.keyDown(window, { key: 'Escape' });
  await chatPage();
  fireEvent.keyDown(window, { key: '3' });
  await screen.findByText('Agents route loaded');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(shortcutsPanel()).toBeNull());
  expect(location.pathname).toBe('/v2/agents');
}, 20_000);

it('H209: in Cinema the panel does not open unseen; stage keys and hints follow the registry (F10, F4, F7)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'cinema.orb': 'q' }));
  render(<App />);
  await chatPage();
  fireEvent.keyDown(window, { key: 'm' });
  const picker = await screen.findByTitle('voice orb (Q)');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  expect(shortcutsPanel()).toBeNull();
  expect(fireEvent.keyDown(window, { key: 'q' })).toBe(false);
  await waitFor(() => expect(screen.getByTitle('voice orb (Q)').className).toBe('on'));
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByTitle('voice orb (Q)')).toBeNull());
  expect(picker.isConnected).toBe(false);
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
});
