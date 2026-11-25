import React from 'react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { DESKTOP_STRINGS, DesktopControls, isFloatingDesktop } from '../desktop';
import { DOCKET_STRINGS } from '../docket/strings';
import { LANGS, pick, stringProblems } from '../frame/strings';
import { talkStrings } from '../home/talk/strings';
import { AppearanceProvider, type AppearanceApi } from '../theme/appearance-context';

const invoke = vi.fn();
/** The appearance cache App reads its language from at its first render, and the prefix of the
 *  edits it journals beside it until the hub takes them (appearance.ts). */
const APPEARANCE_CACHE = 'hud.appearance.v1:/';
function forgetAppearance() {
  for (let i = localStorage.length - 1; i >= 0; i -= 1) {
    const key = localStorage.key(i);
    if (key?.startsWith(APPEARANCE_CACHE)) localStorage.removeItem(key);
  }
}
beforeEach(() => { window.history.replaceState({}, '', '/v2/'); (window as any).__TAURI__ = { core: { invoke } }; invoke.mockReset(); invoke.mockResolvedValue({ positioning: true, alwaysOnTop: true, compositor: 'Cocoa' }); });
afterEach(() => { cleanup(); delete (window as any).__TAURI__; forgetAppearance(); });
it('browser does not expose native window controls', () => { delete (window as any).__TAURI__; render(<DesktopControls />); expect(screen.queryByRole('button')).toBeNull(); });
it('floating route requires the native bridge', () => { window.history.replaceState({}, '', '/v2/?desktop=floating'); expect(isFloatingDesktop()).toBe(true); delete (window as any).__TAURI__; expect(isFloatingDesktop()).toBe(false); });
it('main opener sends only the fixed show action', async () => { render(<DesktopControls />); fireEvent.click(screen.getByRole('button', { name: 'Float chat' })); await waitFor(() => expect(invoke).toHaveBeenCalledWith('desktop_action', { action: 'show' })); });
it('floating controls hide, reset, and hand off using fixed actions', async () => { render(<DesktopControls floating />); for (const [name, action] of [['Hide chat', 'hide'], ['Reset layout', 'reset'], ['Open in app', 'handoff']]) { fireEvent.click(screen.getByRole('button', { name })); await waitFor(() => expect(invoke).toHaveBeenCalledWith('desktop_action', { action })); } });
it('refused native action has visible error feedback', async () => { invoke.mockRejectedValue(new Error('window unavailable')); render(<DesktopControls />); fireEvent.click(screen.getByRole('button', { name: 'Float chat' })); expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'window unavailable'); });
it('unsupported placement is explained from native capability response', async () => { invoke.mockResolvedValue({ positioning: false, alwaysOnTop: false, compositor: 'Wayland' }); render(<DesktopControls floating />); expect(await screen.findByText(/Wayland.*placement.*topmost/i)).toBeTruthy(); });

it('floating app renders existing chat without normal shell or world control', async () => {
  const { default: App } = await import('../app');
  (globalThis as any).fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ turns: [{ role: 'user', content: 'Shared server conversation' }] }) });
  render(<App floating />);
  // wait for the actual transcript, not a one-second cold module-transform budget
  expect(await screen.findByText('Shared server conversation', {}, { timeout: 5000 })).toBeTruthy();
  // the conversation page's floating variant, and none of the main window's frame: no masthead
  // (areas, Find, the stop), no page region, no running foot, no World page
  expect(document.querySelector('[data-chatpage="floating"] [data-register="talk"]')).not.toBeNull();
  for (const part of ['masthead', 'page', 'runfoot']) expect(document.querySelector(`[data-frame="${part}"]`), part).toBeNull();
  expect(screen.queryByRole('button', { name: /^Search or run a command/ })).toBeNull();
  expect(screen.queryByTitle(/World Intelligence/)).toBeNull();
  expect(screen.getByRole('button', { name: 'Open in app' })).toBeTruthy();
}, 10000);

it('refreshes the same authenticated server conversation on focus', async () => {
  const { useDesktopConversation } = await import('../desktop');
  const setMessages = vi.fn();
  localStorage.setItem('hud.user_token', 'test-desktop-token');
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ turns: [{ role: 'user', content: 'Main window turn' }] }) });
  vi.stubGlobal('fetch', fetch);
  function Harness() { useDesktopConversation(setMessages, false, false); return null; }
  render(<Harness />);
  fireEvent(window, new Event('focus'));
  await waitFor(() => expect(setMessages).toHaveBeenCalledWith([expect.objectContaining({ text: 'Main window turn' })]));
  expect(fetch).toHaveBeenCalledWith('/memory', expect.objectContaining({ headers: expect.objectContaining({ 'X-User-Token': 'test-desktop-token' }) }));
  localStorage.removeItem('hud.user_token');
});
it('a stale focus response cannot overwrite an in-flight turn', async () => {
  const { useDesktopConversation } = await import('../desktop');
  const setMessages = vi.fn();
  let resolve: (r: unknown) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise(r => { resolve = r; })));
  function Harness({ busy }: { busy: boolean }) { useDesktopConversation(setMessages, busy, false); return null; }
  const view = render(<Harness busy={false} />);
  fireEvent(window, new Event('focus'));
  view.rerender(<Harness busy />);
  await React.act(async () => { resolve!({ ok: true, json: async () => ({ turns: [{ role: 'user', content: 'old' }] }) }); });
  expect(setMessages).not.toHaveBeenCalled();
});
it('normal app retains its panel finder and native opener', async () => {
  const { default: App } = await import('../app');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
  render(<App />);
  // the retired CONSOLE button's place: the masthead's Find, which carries its tour anchor and
  // opens every panel (the backtick opens it filtered to panels)
  const find = screen.getByRole('button', { name: /^Search or run a command/ });
  expect(find.closest('[data-frame="masthead"]')).not.toBeNull();
  expect(find.getAttribute('data-anchor')).toBe('console');
  expect(screen.getByRole('button', { name: 'Float chat' })).toBeTruthy();
});

/* The window's controls speak the language the rest of the window speaks: the owner's, from App's
   appearance (the one App hands the floating window's page and Glance as their `lang`), read from
   its provider. What each control sends the bridge stays the fixed action it always was. */
const appearanceIn = (lang: string): AppearanceApi => ({
  preferences: { lang }, setPreference: () => {}, status: 'synced', error: '', retry: () => {}, motion: 'calm',
});
const inLang = (lang: string, ui: React.ReactElement) => <AppearanceProvider value={appearanceIn(lang)}>{ui}</AppearanceProvider>;
/** What the controls asked the bridge to do, in order (the capabilities read is not an action). */
const actions = () => invoke.mock.calls.filter(([command]) => command === 'desktop_action').map(([, args]) => args);

it('words the floating window\'s controls in Romanian, and they still send only the fixed actions', async () => {
  render(inLang('ro', <DesktopControls floating />));
  for (const [name, action] of [['Ascunde conversația', 'hide'], ['Resetează poziția și mărimea', 'reset'], ['Deschide în aplicație', 'handoff']]) {
    fireEvent.click(screen.getByRole('button', { name }));
    await waitFor(() => expect(invoke).toHaveBeenCalledWith('desktop_action', { action }));
  }
  const move = screen.getByRole('button', { name: 'Mută conversația plutitoare' });
  expect(move.textContent).toBe('NERVA · CONVERSAȚIE');
  fireEvent.mouseDown(move, { button: 0 });
  fireEvent.mouseDown(screen.getByRole('button', { name: 'Redimensionează conversația plutitoare' }), { button: 0 });
  await waitFor(() => expect(actions()).toEqual([{ action: 'hide' }, { action: 'reset' }, { action: 'handoff' }, { action: 'drag' }, { action: 'resize' }]));
  // no English word is left among them
  for (const name of ['Open in app', 'Reset layout', 'Hide chat', 'Move floating chat', 'Resize floating chat']) {
    expect(screen.queryByRole('button', { name })).toBeNull();
  }
  expect(document.querySelector('.desktop-controls')?.textContent).not.toMatch(/NERVA · CHAT|Open in app|Reset layout|Hide chat/);
});

it('words the main window\'s opener in Romanian, and it still sends only the show action', async () => {
  render(inLang('ro', <DesktopControls />));
  expect(screen.queryByRole('button', { name: 'Float chat' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Deschide conversația plutitoare' }));
  await waitFor(() => expect(actions()).toEqual([{ action: 'show' }]));
});

it('follows a change of language at once, also when its parent keeps the same element (the frame\'s foot)', () => {
  const controls = <DesktopControls floating />;
  const view = render(inLang('en', controls));
  expect(screen.getByRole('button', { name: 'Open in app' })).toBeTruthy();
  view.rerender(inLang('ro', controls));
  expect(screen.getByRole('button', { name: 'Deschide în aplicație' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Open in app' })).toBeNull();
  view.rerender(inLang('en', controls));
  expect(screen.getByRole('button', { name: 'Hide chat' })).toBeTruthy();
});

it('says what the compositor keeps to itself in Romanian', async () => {
  invoke.mockResolvedValue({ positioning: false, alwaysOnTop: false, compositor: 'Wayland' });
  render(inLang('ro', <DesktopControls floating />));
  expect((await screen.findByRole('status')).textContent)
    .toBe('Wayland: poziția și afișarea deasupra celorlalte ferestre sunt controlate de compozitorul tău.');
});

it('has every word in both languages, and words "Open in app" as the conversation and the docket do', () => {
  expect(stringProblems(DESKTOP_STRINGS)).toEqual([]);
  for (const lang of LANGS) {
    expect(DESKTOP_STRINGS[lang].openInApp).toBe(talkStrings(lang).openInApp);
    expect(DESKTOP_STRINGS[lang].openInApp).toBe(pick(DOCKET_STRINGS, lang).openInApp);
  }
  expect(DESKTOP_STRINGS.ro.openInApp).toBe('Deschide în aplicație');
});

it('words the main window\'s opener in the language the owner chooses in the masthead, at once', async () => {
  const { default: App } = await import('../app');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
  render(<App />);
  const foot = () => document.querySelector('[data-frame="runfoot"]') as HTMLElement;
  expect(within(foot()).getByRole('button', { name: 'Float chat' })).toBeTruthy();
  fireEvent.click(screen.getByRole('radio', { name: 'Romanian' }));
  expect(await within(foot()).findByRole('button', { name: 'Deschide conversația plutitoare' })).toBeTruthy();
  expect(within(foot()).queryByRole('button', { name: 'Float chat' })).toBeNull();
  fireEvent.click(within(foot()).getByRole('button', { name: 'Deschide conversația plutitoare' }));
  await waitFor(() => expect(actions()).toEqual([{ action: 'show' }]));
});

it('draws the floating window\'s controls in the owner\'s language, the one the rest of the window speaks', async () => {
  const { default: App } = await import('../app');
  localStorage.setItem(APPEARANCE_CACHE, JSON.stringify({ version: 2, preferences: { lang: 'ro' } }));
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ turns: [] }) }));
  render(<App floating />);
  expect(await screen.findByRole('button', { name: 'Deschide în aplicație' }, { timeout: 5000 })).toBeTruthy();
  expect(document.documentElement.lang).toBe('ro');
  expect(screen.getByRole('button', { name: 'Ascunde conversația' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Open in app' })).toBeNull();
}, 10000);
