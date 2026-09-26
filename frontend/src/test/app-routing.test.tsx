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
  fireEvent.keyDown(window, { key: 'y' });
  await screen.findByText('World route loaded');
});

it('H209: / focuses the message box', async () => {
  history.replaceState(null, '', '/v2/cockpit?demo=1');
  render(<WorldAwareApp />);
  const box = await waitFor(() => { const el = document.querySelector('[data-composer]'); if (!el) throw new Error('no composer'); return el; });
  fireEvent.keyDown(window, { key: '/' });
  expect(document.activeElement).toBe(box);
});
