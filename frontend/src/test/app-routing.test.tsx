import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import WorldAwareApp from '../world_app';
import App from '../app';

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => ({}), createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../modes', () => ({ AgentsMode: () => <div>Agents route loaded</div>, Dossier: () => null, TrustMode: () => <div>Trust route loaded</div>, MemoryMode: () => <input aria-label="Memory draft" /> }));
vi.mock('../modes3', () => ({ ChatMode: () => <div>Chat route loaded</div>, CommsMode: () => null, AdminMode: () => null }));
vi.mock('../modes_world', () => ({ WorldIntelligenceMode: () => <div>World route loaded<input aria-label="World draft" /></div> }));
vi.mock('../panels/jobs', () => ({ JobsWorkspace: () => <div>Jobs route loaded</div> }));
vi.mock('../gap', () => ({ ConsoleOverlay: ({ panelId, onClose }: any) => <div>Console route {panelId}<button onClick={onClose}>Close console</button></div>, FirstRunGate: () => null, ProjectsMode: () => <div>Projects route loaded</div> }));

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, '', '/v2/chat?demo=1');
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
});

it('connects rail, palette, hotkeys, console and desktop handoff to the same URL', async () => {
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.click(screen.getByTitle('Projects'));
  await screen.findByText('Projects route loaded');
  expect(location.pathname).toBe('/v2/projects');
  fireEvent.keyDown(window, { key: '2' });
  await screen.findByText('Agents route loaded');
  expect(location.pathname).toBe('/v2/agents');
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  fireEvent.click(screen.getByText('Memory & Knowledge'));
  await screen.findByLabelText('Memory draft');
  expect(location.pathname).toBe('/v2/memory');
  fireEvent.click(screen.getByTitle('World Intelligence (W)'));
  await screen.findByText('World route loaded');
  fireEvent.click(screen.getByText('close · esc'));
  expect(location.pathname).toBe('/v2/memory');
  fireEvent.keyDown(window, { key: '`' });
  await screen.findByText('Close console');
  expect(location.pathname).toBe('/v2/console');
  fireEvent.click(screen.getByText('Close console'));
  expect(location.pathname).toBe('/v2/memory');
  act(() => window.dispatchEvent(new Event('nerva-desktop-handoff')));
  await screen.findByText('Chat route loaded');
  expect(location.pathname).toBe('/v2/chat');
});
it('loads World bookmarks and restores its overlay through Back/Forward', async () => {
  history.replaceState(null, '', '/v2/world?demo=1');
  render(<WorldAwareApp />);
  await screen.findByText('World route loaded');
  expect(document.title).toBe('World · Nerva');
  fireEvent.click(screen.getByText('close · esc'));
  expect(location.pathname).toBe('/v2/cockpit');
  act(() => history.back());
  await screen.findByText('World route loaded');
  act(() => history.forward());
  await waitFor(() => expect(screen.queryByText('World route loaded')).toBeNull());
});
it('loads a selected console bookmark and clears form state across route changes', async () => {
  history.replaceState(null, '', '/v2/console/decision-inbox?demo=1');
  render(<App />);
  await screen.findByText('Console route decision-inbox');
  fireEvent.keyDown(window, { key: '4' });
  fireEvent.change(await screen.findByLabelText('Memory draft'), { target: { value: 'private draft' } });
  fireEvent.keyDown(window, { key: '2' });
  await screen.findByText('Agents route loaded');
  act(() => history.back());
  expect((await screen.findByLabelText('Memory draft') as HTMLInputElement).value).toBe('');
});
it('keeps floating desktop on canonical chat and preserves its query context', async () => {
  history.replaceState(null, '', '/v2/memory?desktop=floating&demo=1#anchor');
  render(<App floating />);
  await screen.findByText('Chat route loaded');
  expect(location.pathname).toBe('/v2/chat');
  expect(location.search).toBe('?desktop=floating&demo=1');
  expect(location.hash).toBe('#anchor');
});

it('remounts World content when the existing demo context changes', async () => {
  history.replaceState(null, '', '/v2/world?demo=1');
  render(<WorldAwareApp />);
  fireEvent.change(await screen.findByLabelText('World draft'), { target: { value: 'demo draft' } });
  fireEvent.click(screen.getByRole('button', { name: /exit demo/i }));
  await waitFor(() => expect((screen.getByLabelText('World draft') as HTMLInputElement).value).toBe(''));
  expect(location.pathname).toBe('/v2/world');
});

it('restores the invoking mode of a historical World visit', async () => {
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.click(screen.getByTitle('World Intelligence (W)'));
  await screen.findByText('World route loaded');
  fireEvent.click(screen.getByText('close · esc'));
  fireEvent.keyDown(window, { key: '4' });
  await screen.findByLabelText('Memory draft');
  fireEvent.click(screen.getByTitle('World Intelligence (W)'));
  await screen.findByText('World route loaded');
  fireEvent.click(screen.getByText('close · esc'));
  // Entries: chat, World-from-chat, chat, memory, World-from-memory, memory.
  act(() => history.go(-4));
  await screen.findByText('World route loaded');
  fireEvent.click(screen.getByText('close · esc'));
  expect(location.pathname).toBe('/v2/chat');
});
it('restores the invoking mode of a historical console visit', async () => {
  render(<App />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: '`' });
  await screen.findByText('Close console');
  fireEvent.click(screen.getByText('Close console'));
  fireEvent.keyDown(window, { key: '4' });
  await screen.findByLabelText('Memory draft');
  fireEvent.keyDown(window, { key: '`' });
  await screen.findByText('Close console');
  fireEvent.click(screen.getByText('Close console'));
  act(() => history.go(-4));
  await screen.findByText('Close console');
  fireEvent.click(screen.getByText('Close console'));
  expect(location.pathname).toBe('/v2/chat');
});

it('closes a prefixed console through the same toggle hotkey', async () => {
  window.__NERVA_BASE_PATH__ = '/one';
  try {
    history.replaceState(null, '', '/one/v2/chat?demo=1');
    render(<App />);
    await screen.findByText('Chat route loaded');
    fireEvent.keyDown(window, {key:'`'});
    await screen.findByText('Close console');
    fireEvent.keyDown(window, {key:'`'});
    expect(location.pathname).toBe('/one/v2/chat');
  } finally {delete window.__NERVA_BASE_PATH__;}
});
it('closes prefixed World with Escape and restores the invoking mode', async () => {
  window.__NERVA_BASE_PATH__ = '/one';
  try {
    history.replaceState(null, '', '/one/v2/chat?demo=1');
    render(<WorldAwareApp />);
    await screen.findByText('Chat route loaded');
    fireEvent.keyDown(window, {key:'w'});
    await screen.findByText('World route loaded');
    fireEvent.keyDown(window, {key:'Escape'});
    expect(location.pathname).toBe('/one/v2/chat');
  } finally {delete window.__NERVA_BASE_PATH__;}
});

it('H209: mod+/ opens the shortcuts panel, a rebinding moves the key, and it persists', async () => {
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  const dialog = await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: '2' });                          // the panel owns the keyboard
  expect(location.pathname).toBe('/v2/chat');
  fireEvent.click(screen.getByRole('button', { name: 'Rebind Go to Agents' }));
  fireEvent.keyDown(window, { key: 'x' });
  expect(JSON.parse(localStorage.getItem('hud.shortcuts') || '{}')).toEqual({ 'mode.agents': 'x' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(dialog.isConnected).toBe(false);
  fireEvent.keyDown(window, { key: '2' });
  expect(location.pathname).toBe('/v2/chat');
  fireEvent.keyDown(window, { key: 'x' });
  await screen.findByText('Agents route loaded');
  expect(location.pathname).toBe('/v2/agents');
});

it('H209: a rebound World key opens World and the old one no longer does', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'view.world': 'y' }));
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: 'w' });
  expect(location.pathname).toBe('/v2/chat');
  expect(screen.getByTitle('World Intelligence (Y)')).toBeTruthy();   // the hint names the new key
  fireEvent.keyDown(window, { key: 'y' });
  await screen.findByText('World route loaded');
});

it('H209: a key typed into a field is the field\'s, not a mode switch', async () => {
  history.replaceState(null, '', '/v2/memory?demo=1');
  render(<WorldAwareApp />);
  const box = await screen.findByLabelText('Memory draft');
  box.focus();
  fireEvent.keyDown(box, { key: '2' });
  fireEvent.keyDown(box, { key: 'w' });
  await act(async () => {});
  expect(location.pathname).toBe('/v2/memory');
  expect(screen.queryByText('Agents route loaded')).toBeNull();
  expect(screen.queryByText('World route loaded')).toBeNull();
});

it('H209: a rebinding made in the panel reaches the World button beside the app', async () => {
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  expect(screen.getByTitle('World Intelligence (W)')).toBeTruthy();
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.click(screen.getByRole('button', { name: 'Rebind Open World Intelligence' }));
  fireEvent.keyDown(window, { key: 'y' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByTitle('World Intelligence (Y)')).toBeTruthy();
});

it('H209: / focuses the message box', async () => {
  history.replaceState(null, '', '/v2/cockpit?demo=1');
  render(<WorldAwareApp />);
  const box = await waitFor(() => { const el = document.querySelector('[data-composer]'); if (!el) throw new Error('no composer'); return el; });
  fireEvent.keyDown(window, { key: '/' });
  expect(document.activeElement).toBe(box);
});

it('H209: Ctrl+Space on the panel itself opens it, and a stored "mod+" no longer locks it out (F1)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'session.shortcuts': 'mod+' }));
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.click(screen.getByRole('button', { name: 'Rebind Keyboard shortcuts' }));
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true });
  expect(JSON.parse(localStorage.getItem('hud.shortcuts') || '{}')).toEqual({ 'session.shortcuts': 'mod+space' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  fireEvent.keyDown(window, { key: ' ', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
});

it('H209: the palette still opens the panel when its chord is taken (F2)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.cockpit': 'mod+/', 'session.shortcuts': 'mod+k' }));
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });            // Cockpit's now (the first action wins)
  await waitFor(() => expect(location.pathname).toBe('/v2/cockpit'));
  expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
  fireEvent.click(screen.getByTitle('command palette'));
  fireEvent.click(screen.getByText('Keyboard shortcuts'));
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
});

it('H209: a palette rebound to a bare key never fires while typing (F3)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'session.palette': 'p' }));
  history.replaceState(null, '', '/v2/memory?demo=1');
  render(<WorldAwareApp />);
  const box = await screen.findByLabelText('Memory draft');
  box.focus();
  expect(fireEvent.keyDown(box, { key: 'p' })).toBe(true);           // the letter is typed, not eaten
  expect(screen.queryByText('Accent · Cyan')).toBeNull();
  fireEvent.keyDown(box, { key: 'k', ctrlKey: true });
  await screen.findByText('Accent · Cyan');
});

it('H209: a HUD action on a rebound chord is not also the browser\'s (F4)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.agents': 'mod+d', 'view.world': 'mod+y' }));
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  expect(fireEvent.keyDown(window, { key: 'd', ctrlKey: true })).toBe(false);
  await screen.findByText('Agents route loaded');
  expect(fireEvent.keyDown(window, { key: 'y', ctrlKey: true })).toBe(false);
  await screen.findByText('World route loaded');
});

it('H209: World\'s key waits while the panel is open (F5)', async () => {
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: 'w' });
  expect(location.pathname).toBe('/v2/chat');
});

it('H209: with storage off, a World rebinding still takes for this page (F6)', async () => {
  const setItem = Storage.prototype.setItem;
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
    if (key === 'hud.shortcuts') throw new Error('storage off');
    return setItem.call(this, key, value);
  });
  try {
    render(<WorldAwareApp />);
    await screen.findByText('Chat route loaded');
    fireEvent.keyDown(window, { key: '/', ctrlKey: true });
    await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
    fireEvent.click(screen.getByRole('button', { name: 'Rebind Open World Intelligence' }));
    fireEvent.keyDown(window, { key: 'y' });
    expect(screen.getByRole('button', { name: 'Rebind Open World Intelligence' }).textContent).toBe('Y');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    fireEvent.keyDown(window, { key: 'w' });
    expect(location.pathname).toBe('/v2/chat');
    fireEvent.keyDown(window, { key: 'y' });
    await screen.findByText('World route loaded');
  } finally { spy.mockRestore(); }
});

it('H209: the HUD\'s key hints follow a rebinding (F7)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'mode.agents': 'x', 'view.world': 'y', 'view.console': 'c', 'session.palette': 'mod+p' }));
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  expect(screen.getByTitle('World Intelligence (Y)')).toBeTruthy();
  expect(screen.getByTitle('console (C)')).toBeTruthy();
  const paletteButton = screen.getByTitle('command palette');
  expect(paletteButton.textContent).toBe('Ctrl+P');
  fireEvent.click(paletteButton);
  const item = (name: string) => [...document.querySelectorAll('.pal-item')].find((el) => el.querySelector('.pi-name')?.textContent === name);
  expect(item('Agents')?.querySelector('.pi-hint')?.textContent).toBe('X');
  expect(item('Cockpit')?.querySelector('.pi-hint')?.textContent).toBe('1');
});

it('H209: the Escape that closes the panel leaves World open beneath it (F8)', async () => {
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: 'w' });
  await screen.findByText('World route loaded');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(location.pathname).toBe('/v2/world');
});

it('H209: in Cinema the panel does not open unseen; stage keys and hints follow the registry (F10, F4, F7)', async () => {
  localStorage.setItem('hud.shortcuts', JSON.stringify({ 'cinema.orb': 'q' }));
  render(<WorldAwareApp />);
  await screen.findByText('Chat route loaded');
  fireEvent.keyDown(window, { key: 'm' });
  const picker = await screen.findByTitle('voice orb (Q)');
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  expect(screen.queryByRole('dialog', { name: 'Keyboard shortcuts' })).toBeNull();
  expect(fireEvent.keyDown(window, { key: 'q' })).toBe(false);
  await waitFor(() => expect(screen.getByTitle('voice orb (Q)').className).toBe('on'));
  fireEvent.keyDown(window, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByTitle('voice orb (Q)')).toBeNull());
  expect(picker.isConnected).toBe(false);
  fireEvent.keyDown(window, { key: '/', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Keyboard shortcuts' });
});
