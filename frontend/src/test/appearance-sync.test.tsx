/* Appearance sync through the App, under the Ledger frame (the default since the cutover).
   The search and command sheet keeps the old palette's appearance rows word for word (PHASE_B_PLAN.md
   §8.2 row 11); it lists them for a query (with nothing typed it shows the recent items, the areas
   and the actions), so these tests open it from the masthead's Find button (or Ctrl K) and type
   the row's words before choosing it. Personalisation is a page of Settings, left by navigating. */
import React from 'react';
import { render, screen, fireEvent, waitFor, act, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';
import { resetPolling } from '../signals/poll';
import { THEMES } from '../theme/registry';

vi.mock('../voice', () => ({useVoice: () => ({active:false, toggle:()=>{}})}));
vi.mock('../mesh', () => ({NeuralMesh:()=>null,isExecutingAgent:()=>false}));
vi.mock('../api/loaders', () => ({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live', () => ({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics', () => ({initAnalytics:()=>{},trackPageview:()=>{}}));
// The conversation page (/v2/chat, home/ChatPage) stands in for any component that reads appearance
// through the shared provider. It also records, after every commit, the scheme preference beside
// the scheme <html> was given in that commit (its passive effect runs after App's layout effect has
// applied the appearance).
const commits = vi.hoisted(() => [] as string[]);
vi.mock('../home/ChatPage', async () => {
  const { useAppearanceContext } = await import('../theme/appearance-context');
  const { useEffect } = await import('react');
  return {ChatPage:()=> {
    const appearance = useAppearanceContext();
    useEffect(() => { commits.push(`${appearance?.preferences.scheme}:${document.documentElement.getAttribute('data-scheme')}`); });
    return <div>Chat<span data-testid="shared-look">{appearance ? appearance.preferences.look : 'no provider'}</span>
      <button onClick={()=>appearance?.setPreference('look','presence')}>Choose Presence</button></div>;
  }};
});
// A panel page shows the real Personalisation page (theme contract §8); any other panel is a stub.
vi.mock('../gap', async () => {
  const { AppearancePanel } = await import('../panels/appearance');
  return {FirstRunGate:()=>null, ConsolePanel:({panelId}:{panelId: string}) =>
    panelId === 'appearance' ? <AppearancePanel/> : <p>Panel page {panelId}</p>};
});

const html = () => document.documentElement;
/** A server that answers GET with `stored` and merges every PUT into it. */
function server(stored: Record<string, string> = {}, configured = true) {
  let saved = {...stored};
  const fetch = vi.fn().mockImplementation(async (_path, init) => {
    if (init?.method === 'PUT') { const {_revision, ...patch} = JSON.parse(init.body); saved = {...saved, ...patch}; configured = true; }
    return new Response(JSON.stringify({configured, revision:'0', preferences:saved}));
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
/** matchMedia with a live `matches` per query and `change` listeners. */
function stubMedia(state: Record<string, boolean>) {
  const listeners = new Map<string, Set<() => void>>();
  vi.stubGlobal('matchMedia', (query: string) => ({
    get matches() { return !!state[query]; }, media: query,
    addEventListener: (_type: string, fn: () => void) => { if (!listeners.has(query)) listeners.set(query, new Set()); listeners.get(query)!.add(fn); },
    removeEventListener: (_type: string, fn: () => void) => { listeners.get(query)?.delete(fn); },
  }));
  return (changes: Record<string, boolean>) => {
    Object.assign(state, changes);
    for (const query of Object.keys(changes)) listeners.get(query)?.forEach(fn => fn());
  };
}
const SHEET = 'Search or run a command';
const sheet = () => screen.queryByRole('dialog',{name:SHEET});
/** The sheet with `words` typed, opened from the masthead's Find button (or with Ctrl K). */
async function search(words: string, opener: 'find' | 'keys' = 'find') {
  if (!sheet()) {
    if (opener === 'keys') fireEvent.keyDown(window,{key:'k',ctrlKey:true});
    else fireEvent.click(await screen.findByRole('button',{name:/^Search or run a command/}));
  }
  const open = sheet() as HTMLElement;
  expect(open).not.toBeNull();
  fireEvent.change(within(open).getByRole('combobox'),{target:{value:words}});
  return open;
}
/** An appearance row of the sheet, found by typing its own words. */
async function row(label: string, opener: 'find' | 'keys' = 'find') {
  return within(await search(label, opener)).getByText(label);
}

beforeEach(() => {
  resetPolling();
  localStorage.clear(); history.replaceState(null,'','/v2/chat?demo=1');
  for (const name of ['data-look','data-scheme','data-font','data-density','data-motion','style']) html().removeAttribute(name);
});
afterEach(() => { vi.unstubAllGlobals(); resetPolling(); });

it('hydrates appearance from the server without writing at boot', async () => {
  // A fresh answer per request, as a server sends: under the Ledger frame the masthead's stop asks
  // /api/security/kill-switch first, and one Response body can be read only once.
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({configured:true, preferences:{accent:'amber',look:'graphite',density:'compact',motion:'system',scanline:'off',dotgrid:'on'}})));
  vi.stubGlobal('fetch',fetch);
  const {container} = render(<App/>);
  await waitFor(() => expect(container.querySelector('.hud-root')?.getAttribute('data-accent')).toBe('amber'));
  expect(container.querySelector('.hud-root')?.getAttribute('data-look')).toBe('graphite');
  expect(fetch.mock.calls.some(call => call[1]?.method==='PUT')).toBe(false);
});
it('saves an explicit palette choice to the narrow preference endpoint', async () => {
  const fetch = vi.fn().mockImplementation(async (_path, init) => new Response(JSON.stringify({configured:!!init?.body,preferences:{accent:init?.body?'violet':'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off'}})));
  vi.stubGlobal('fetch', fetch);
  render(<App/>);
  fireEvent.click(await row('Accent · Violet'));
  expect(sheet()).toBeNull();
  await waitFor(() => expect(fetch.mock.calls.some(call => call[0]==='/api/preferences/appearance' && call[1]?.method==='PUT' && JSON.parse(call[1].body).accent==='violet')).toBe(true));
});

it('shows failed explicit saves without reopening the palette', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_url, init) => {
    if (init?.method==='PUT') throw new TypeError('offline');
    return new Response(JSON.stringify({configured:false,preferences:{}}));
  }));
  render(<App/>);
  fireEvent.click(await row('Accent · Violet'));
  await screen.findByText('Appearance saved on this browser only. Sync failed.');
  // the shell says it, with its retry; the sheet stays closed
  expect(screen.getByRole('button',{name:'Retry sync'})).toBeTruthy();
  expect(sheet()).toBeNull();
});

it('applies a palette font to the HUD root with only a finite font patch', async () => {
  const fetch=vi.fn().mockImplementation(async(_path,init)=>new Response(JSON.stringify({configured:true,revision:'0',preferences:init?.body?JSON.parse(init.body):{}})));
  vi.stubGlobal('fetch',fetch);
  const {container}=render(<App/>);
  fireEvent.click(await row('Font · System Serif', 'keys'));
  await waitFor(()=>expect(container.querySelector('.hud-root')?.getAttribute('data-font')).toBe('system-serif'));
  expect(fetch.mock.calls.filter(call=>call[1]?.method==='PUT').map(call=>JSON.parse(call[1].body))).toEqual([{font:'system-serif',_revision:'0'}]);
});

/* Theme contract v1 §2, §7. */
it('lands an unconfigured instance on Ledger, dark, on .hud-root and <html>', async () => {
  const fetch = server({}, false);
  const {container} = render(<App/>);
  await waitFor(() => expect(fetch).toHaveBeenCalled());
  const root = container.querySelector('.hud-root')!;
  expect(root.getAttribute('data-look')).toBe('ledger');
  expect(root.getAttribute('data-scheme')).toBe('dark');
  expect(html().getAttribute('data-look')).toBe('ledger');
  expect(html().getAttribute('data-scheme')).toBe('dark');
  expect(fetch.mock.calls.some(call => call[1]?.method==='PUT')).toBe(false);
});

it('mirrors every axis onto <html>, with the resolved scheme on both', async () => {
  server({look:'atlas', scheme:'light', density:'compact', motion:'calm', font:'system-serif'});
  const {container} = render(<App/>);
  await waitFor(() => expect(container.querySelector('.hud-root')?.getAttribute('data-scheme')).toBe('light'));
  expect(container.querySelector('.hud-root')?.getAttribute('data-look')).toBe('atlas');
  expect(html().getAttribute('data-look')).toBe('atlas');
  expect(html().getAttribute('data-scheme')).toBe('light');
  expect(html().getAttribute('data-density')).toBe('compact');
  expect(html().getAttribute('data-motion')).toBe('calm');
  expect(html().getAttribute('data-font')).toBe('system-serif');
});

it('keeps a Classic look dark even when the owner asked for light', async () => {
  server({look:'graphite', scheme:'light'});
  const {container} = render(<App/>);
  await waitFor(() => expect(html().getAttribute('data-look')).toBe('graphite'));
  expect(html().getAttribute('data-scheme')).toBe('dark');
  expect(container.querySelector('.hud-root')?.getAttribute('data-scheme')).toBe('dark');
});

it('follows the OS colour scheme live while the scheme is System', async () => {
  const change = stubMedia({'(prefers-color-scheme: dark)': true});
  server({look:'ledger', scheme:'system'});
  const {container} = render(<App/>);
  await waitFor(() => expect(html().getAttribute('data-scheme')).toBe('dark'));
  act(() => change({'(prefers-color-scheme: dark)': false, '(prefers-color-scheme: light)': true}));
  await waitFor(() => expect(html().getAttribute('data-scheme')).toBe('light'));
  expect(container.querySelector('.hud-root')?.getAttribute('data-scheme')).toBe('light');
});

it('starts System from the OS reading of now, not one taken before another scheme was chosen', async () => {
  const change = stubMedia({'(prefers-color-scheme: dark)': true});
  server({look:'ledger', scheme:'dark'});
  render(<App/>);
  await waitFor(() => expect(html().getAttribute('data-scheme')).toBe('dark'));
  // The OS turns light while the owner is on Dark: nothing on screen changes...
  act(() => change({'(prefers-color-scheme: dark)': false, '(prefers-color-scheme: light)': true}));
  expect(html().getAttribute('data-scheme')).toBe('dark');
  // ...and choosing System then paints light from its first frame.
  const choice = await row('Scheme · System');
  commits.length = 0;
  fireEvent.click(choice);
  await waitFor(() => expect(html().getAttribute('data-scheme')).toBe('light'));
  expect(commits.filter(entry => entry.startsWith('system:'))).not.toContain('system:dark');
  expect(commits).toContain('system:light');
});

it('shares the one appearance instance with the tree through AppearanceProvider', async () => {
  const fetch = server({look:'ledger'});
  const {container} = render(<App/>);
  expect((await screen.findByTestId('shared-look')).textContent).toBe('ledger');
  fireEvent.click(screen.getByText('Choose Presence'));
  await waitFor(() => expect(container.querySelector('.hud-root')?.getAttribute('data-look')).toBe('presence'));
  expect(screen.getByTestId('shared-look').textContent).toBe('presence');
  expect(html().getAttribute('data-look')).toBe('presence');
  await waitFor(() => expect(fetch.mock.calls.some(call => call[1]?.method==='PUT' && JSON.parse(call[1].body).look==='presence')).toBe(true));
});

it('offers every theme and the scheme in the palette and syncs a scheme choice', async () => {
  const fetch = server({look:'ledger'});
  const {container} = render(<App/>);
  const looks = await search('look');
  await within(looks).findByText('Look · Ledger ✓');
  // every theme of the registry is a row (the Classic looks keep their old palette words)
  expect(THEMES).toHaveLength(9);
  for (const theme of THEMES) {
    const word = theme.family === 'nerva' ? theme.name.en : `${theme.id[0].toUpperCase()}${theme.id.slice(1)}`;
    expect(within(looks).getByText(`Look · ${word}${theme.id === 'ledger' ? ' ✓' : ''}`), theme.id).toBeTruthy();
  }
  expect(within(looks).getByText('Look · Atlas')).toBeTruthy();
  const schemes = await search('scheme');
  expect(within(schemes).getByText('Scheme · Dark ✓')).toBeTruthy();
  expect(within(schemes).getByText('Scheme · System')).toBeTruthy();
  fireEvent.click(within(schemes).getByText('Scheme · Light'));
  await waitFor(() => expect(container.querySelector('.hud-root')?.getAttribute('data-scheme')).toBe('light'));
  expect(html().getAttribute('data-scheme')).toBe('light');
  await waitFor(() => expect(fetch.mock.calls.some(call => call[1]?.method==='PUT' && JSON.parse(call[1].body).scheme==='light')).toBe(true));
});

/* Theme contract §8: while Personalisation is open, its own status line (localised, with its own
   retry) is the one live region announcing an appearance sync failure; the shell's notice waits. */
const UNREACHABLE = 'Appearance is using this browser’s saved choices. Server unavailable.';
/** A hub that answers everything but the appearance document, so the first read of it fails. */
function appearanceUnreachable() {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (path: unknown) => {
    if (String(path).includes('/api/preferences/appearance')) throw new TypeError('offline');
    return new Response(JSON.stringify({}));
  }));
}
const announcing = (text: RegExp) => screen.queryAllByRole('status').filter(region => text.test(region.textContent || ''));

it('leaves a sync failure to Personalisation while it is open, and the shell says it again after', async () => {
  appearanceUnreachable();
  history.replaceState(null,'','/v2/console/appearance?demo=1');
  render(<App/>);
  await screen.findByRole('button',{name:'Sync again'},{timeout:3000});
  expect(announcing(/Server unavailable/).map(region => region.textContent)).toEqual([UNREACHABLE]);
  expect(screen.getAllByText(UNREACHABLE)).toHaveLength(1);
  expect(screen.queryByRole('button',{name:'Retry sync'})).toBeNull();
  // leaving the page (another page of Settings, from its contents column) hands the failure back to the shell
  const contents = document.querySelector('[data-frame="contents"]') as HTMLElement;
  expect(contents.getAttribute('data-area')).toBe('settings');
  fireEvent.click(within(contents).getByRole('link',{name:'Model setup'}));
  expect(await screen.findByRole('button',{name:'Retry sync'})).toBeTruthy();
  expect(location.pathname).toBe('/v2/console/model-setup');
  expect(await screen.findByText('Panel page model-setup')).toBeTruthy();
  expect(screen.getAllByText(UNREACHABLE)).toHaveLength(1);
  expect(announcing(/Server unavailable/)).toHaveLength(1);
  expect(screen.queryByRole('button',{name:'Sync again'})).toBeNull();
});

it('lets Personalisation say it in Romanian, with no English copy from the shell', async () => {
  localStorage.setItem('hud.appearance.v1:/', JSON.stringify({version:2, preferences:{lang:'ro'}}));
  appearanceUnreachable();
  history.replaceState(null,'','/v2/console/appearance?demo=1');
  render(<App/>);
  await screen.findByRole('button',{name:'Sincronizează din nou'},{timeout:3000});
  expect(announcing(/Server unavailable|Serverul nu răspunde/).map(region => region.textContent))
    .toEqual(['Aspectul folosește alegerile salvate în acest browser. Serverul nu răspunde.']);
  expect(screen.queryByRole('button',{name:'Retry sync'})).toBeNull();
});

it('keeps the shell notice on every other panel page', async () => {
  appearanceUnreachable();
  history.replaceState(null,'','/v2/console/decision-inbox?demo=1');
  render(<App/>);
  expect(await screen.findByRole('button',{name:'Retry sync'},{timeout:3000})).toBeTruthy();
  expect(await screen.findByText('Panel page decision-inbox')).toBeTruthy();
  expect(announcing(/Server unavailable/)).toHaveLength(1);
});
