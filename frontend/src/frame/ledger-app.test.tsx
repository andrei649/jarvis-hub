/* The App, the one frame there is (PHASE_B_PLAN.md §9.3; the classic shell and its development
   switch were deleted in stage 5), with every region wired in: every registry route renders inside
   the Ledger frame (Glance full screen, without it), live and in demo, without throwing; each page
   of an area carries its contents column; Home holds the day, the conversation, the docket and the
   record; the search and command sheet is Ctrl K; World is a page, not an overlay; the floating
   window is the conversation page's floating variant. A browser that still carries the old
   switch's word (?frame=classic, localStorage['hud.frame']) gets the same frame.

   Heavy modes and panels are stand-ins: this pins the route → page wiring and the frame, not each
   mode's content. */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

vi.hoisted(() => { history.replaceState(null, '', '/v2/cockpit'); });
const loader = vi.hoisted(() => ({ data: null as any }));

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {}, status: 'idle' }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({
  loadJarvisData: async () => ({}),
  createLatestRefreshRunner: (opts: any) => ({
    refresh: () => { if (loader.data) opts.commitData(loader.data); },
    stop: () => {},
  }),
}));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../modes', () => ({
  AgentsMode: () => <div data-testid="mode-body">agents</div>, Dossier: () => null,
  MemoryMode: () => <div data-testid="mode-body">memory</div>,
}));
vi.mock('../modes2', () => ({
  AutonomyMode: () => <div data-testid="mode-body">autonomy</div>, BuildMode: () => <div data-testid="mode-body">build</div>,
  ObserveMode: () => <div data-testid="mode-body">observe</div>, InteropMode: () => <div data-testid="mode-body">interop</div>,
}));
vi.mock('../modes3', () => ({
  CommsMode: () => <div data-testid="mode-body">comms</div>,
  AdminMode: () => <div data-testid="mode-body">admin</div>,
}));
vi.mock('../modes4', () => ({
  FinanceMode: () => <div data-testid="mode-body">finance</div>, HealthMode: () => <div data-testid="mode-body">health</div>,
  KnowledgeMode: () => <div data-testid="mode-body">knowledge</div>, FamilyMode: () => <div data-testid="mode-body">family</div>,
}));
vi.mock('../modes_world', () => ({ WorldIntelligenceMode: () => <div data-testid="mode-body">World route loaded</div> }));
vi.mock('../panels/jobs', () => ({ JobsWorkspace: () => <div data-testid="mode-body">jobs</div> }));
vi.mock('../artifacts', () => ({ ArtifactsPanel: () => <div data-testid="mode-body">artifacts</div>, artifactsTabLabel: () => 'Artifacts' }));
vi.mock('../gap', () => ({
  ConsolePanel: ({ panelId }: { panelId: string }) => <div data-testid="console-panel">{panelId}</div>,
  FirstRunGate: () => null,
  ProjectsMode: () => <div data-testid="mode-body">projects</div>,
}));

import App from '../app';
import { navigateHud, parseHudRoute } from '../hud-routing';
import { ALL_PAGES, PAGES, pageKey, type PageEntry } from '../nav/areas';
import { pageForRoute, pathOf } from '../nav/routes';
import { ACTIONS } from '../shortcuts';
import { resetPolling } from '../signals/poll';
import { stubHub } from './test-support';

function start(path: string) {
  history.replaceState(null, '', path);
}

const ROSTER = [
  { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', enabled: true, chat_routing: 'orchestrated', status: 'online' },
  { id: 'frigga', name: 'Frigga', rosterSource: 'api', enabled: true, chat_routing: 'local', status: 'online' },
];

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
beforeEach(() => {
  resetPolling();
  localStorage.clear();
  localStorage.setItem('hud.seen', '1');
  loader.data = null;
  global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: 'not initialized' }) });
});
afterEach(() => { resetPolling(); });

const frame = (part: string) => document.querySelector(`[data-frame="${part}"]`);
const fetched = () => (global.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls.map((call) => String(call[0]));
const sheet = () => screen.queryByRole('dialog', { name: 'Search or run a command' });

/** The Ledger's own pages: the register each one draws, live and in demo. */
const OWN_PAGE: Readonly<Record<string, (demo: boolean) => string>> = {
  work: () => '[data-register="work-needs"]',
  timeline: () => '[data-register="timeline"]',
  trust: () => '[data-register="trust-record"]',
  artifacts: (demo) => (demo ? '[data-page="artifacts"][data-demo="true"]' : '[data-page="artifacts"] [data-testid="mode-body"]'),
};

/** Go to an entry's page in the running App and check it is drawn where it belongs. */
async function visit(entry: PageEntry, demo: boolean) {
  const path = pathOf(entry.ref);
  act(() => navigateHud(path));
  const page = pageForRoute(parseHudRoute(path));
  const where = `${path}${demo ? ' (demo)' : ''}`;
  if (page.kind === 'glance') {
    await waitFor(() => expect(document.querySelector('[data-glance]'), where).not.toBeNull());
    expect(frame('masthead'), where).toBeNull();
    expect(document.querySelector('.ambient'), where).toBeNull();
    return;
  }
  await waitFor(() => expect(frame('page'), where).not.toBeNull());
  for (const part of ['masthead', 'runhead', 'notices', 'runfoot']) expect(frame(part), `${where} ${part}`).not.toBeNull();
  const current = document.querySelector('[data-frame="masthead"] .n-areas [aria-current="page"]');
  expect(current?.getAttribute('data-area') ?? null, where).toBe(entry.area);
  if (page.kind === 'home') {
    expect([...document.querySelectorAll('[data-home] [data-register]')].map((el) => el.getAttribute('data-register')), where)
      .toEqual(['day', 'talk', 'docket', 'record']);
    expect(document.querySelector('[data-home] [data-frame="dayband"]'), where).not.toBeNull();
    expect(document.querySelector('[data-home] [data-home-more]'), where).not.toBeNull();
    expect(frame('contents'), where).toBeNull();
  } else if (page.kind === 'allPages') {
    await waitFor(() => expect(frame('allpages'), where).not.toBeNull());
    expect(frame('contents'), where).toBeNull();
  } else {
    // a page of an area: its contents column, with this page (or the page it duplicates) marked
    const contents = frame('contents');
    expect(contents?.getAttribute('data-area'), where).toBe(entry.area);
    const marked = entry.duplicateOf ? pageKey(entry.duplicateOf) : entry.key;
    expect(contents?.querySelector('[aria-current="page"]')?.getAttribute('data-page'), where).toBe(marked);
    if (page.kind === 'chat') {
      expect(document.querySelector('[data-chatpage="chat"] [data-register="talk"]'), where).not.toBeNull();
    } else if (page.kind === 'panel') {
      await waitFor(() => expect(screen.getByTestId('console-panel').textContent, where).toBe((entry.ref as { id: string }).id));
    } else {
      await waitFor(() => expect(document.querySelector('.n-areapage__title'), where).not.toBeNull());
      const own = OWN_PAGE[(entry.ref as { id: string }).id];
      if (own) await waitFor(() => expect(document.querySelector(own(demo)), where).not.toBeNull());
    }
  }
  expect(screen.queryByText(/This page could not load/), where).toBeNull();
  expect(document.querySelector('[data-slot="placeholder"]'), where).toBeNull();
}

describe('App under the Ledger frame', () => {
  it('draws the frame, with Home\'s registers wired in', async () => {
    start('/v2/cockpit');
    render(<App />);
    await waitFor(() => expect(frame('masthead')).not.toBeNull());
    expect(document.querySelector('.hud-root')?.getAttribute('data-frame-root')).toBe('ledger');
    expect(document.querySelector('.workzone, .rail-btn, .topbar, .ticker, .pal')).toBeNull();
    expect([...document.querySelectorAll('[data-register]')].map((el) => el.getAttribute('data-register'))).toEqual(['day', 'talk', 'docket', 'record']);
    expect(screen.getByRole('link', { name: 'Skip to the conversation' }).getAttribute('href')).toBe('#n-talk');
    // the composer is the conversation register's, on Home
    expect(document.querySelector('#n-talk [data-register="talk"] [data-composer]')).not.toBeNull();
    // the docket asks its feed and, while it does not answer, claims nothing
    await waitFor(() => expect(fetched()).toContain('/autonomy/tasks?status=blocked&limit=200'));
    await waitFor(() => expect(document.querySelector('[data-register="docket"] [data-docket-state]')?.getAttribute('data-docket-state')).toBe('unknown'));
    expect(document.title).toBe('Today · Nerva');
  });

  it('draws the same frame for a browser that still carries the deleted switch\'s classic word, and keeps its URL', async () => {
    localStorage.setItem('hud.frame', 'classic');
    start('/v2/memory?frame=classic&demo=1');
    render(<App />);
    await waitFor(() => expect(frame('masthead')).not.toBeNull());
    expect(document.querySelector('.hud-root')?.getAttribute('data-frame-root')).toBe('ledger');
    expect(document.querySelector('.workzone, .rail-btn, .topbar, .ticker, .pal, .ambient')).toBeNull();
    expect((await screen.findByTestId('mode-body')).textContent).toBe('memory');
    expect(location.pathname + location.search).toBe('/v2/memory?frame=classic&demo=1');
    expect(document.title).toBe('Memory · Nerva');
    // Ctrl K is the search sheet, `a` is Glance: nothing of the HUD v2 shell answers
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(sheet()).not.toBeNull();
    expect(document.querySelector('.pal')).toBeNull();
    fireEvent.keyDown(within(sheet() as HTMLElement).getByRole('combobox'), { key: 'Escape' });
    fireEvent.keyDown(window, { key: 'a' });
    await waitFor(() => expect(location.pathname).toBe('/v2/glance'));
  });

  it.each([false, true])('renders every registry route in its frame, wired, without throwing (demo %s)', async (demo) => {
    start(`/v2/cockpit${demo ? '?demo=1' : ''}`);
    render(<App />);
    await waitFor(() => expect(frame('masthead')).not.toBeNull());
    for (const entry of [...PAGES, ALL_PAGES]) await visit(entry, demo);
  }, 180_000);

  it('draws a mode with no live source as the area-page empty state, and the mode itself in demo', async () => {
    start('/v2/memory');
    const { unmount } = render(<App />);
    await waitFor(() => expect(document.querySelector('[data-empty]')).not.toBeNull());
    expect(screen.queryByTestId('mode-body')).toBeNull();
    unmount();
    resetPolling();
    start('/v2/memory?demo=1');
    render(<App />);
    expect((await screen.findByTestId('mode-body')).textContent).toBe('memory');
    expect(document.querySelector('[data-notice="demo"]')).not.toBeNull();
  });

  it('draws the Ledger\'s own pages whatever the mode live keys say: Trust is its overview, not TrustMode', async () => {
    start('/v2/trust');
    render(<App />);
    await waitFor(() => expect(document.querySelector('[data-register="trust-record"]')).not.toBeNull());
    expect(document.querySelector('[data-empty]')).toBeNull();
    expect(screen.queryByTestId('mode-body')).toBeNull();
  });

  it('counts the docket beside Work in the masthead and draws its entries on Home, from the one feed', async () => {
    const tasks = [
      { id: 41, status: 'blocked', title: 'Restart qdrant', risk_tier: 2, kind: 'restart_service' },
      { id: 42, status: 'blocked', title: 'Send the weekly note', risk_tier: 1, kind: 'email.send' },
    ];
    const calls = stubHub((_method, path) => (path.includes('/autonomy/tasks?status=blocked')
      ? { status: 200, body: { tasks, groups: [] } } : { status: 503 }), (name, value) => { (globalThis as any)[name] = value; });
    start('/v2/build');
    render(<App />);
    await waitFor(() => expect(document.querySelector('[data-frame="masthead"] [data-anchor="area.work"] [data-note="docket"]')?.textContent).toContain('2'));
    // the contents column's Decisions carries the same count
    act(() => navigateHud('/v2/work'));
    await waitFor(() => expect(frame('contents')?.querySelector('[data-page="panel:decision-inbox"] [data-note]')?.textContent).toContain('2'));
    act(() => navigateHud('/v2/cockpit'));
    await waitFor(() => expect(document.querySelectorAll('[data-register="docket"] [data-docket-entry]')).toHaveLength(2));
    // one request per poll for every reader of the feed (masthead, contents, docket, day, record)
    const asked = calls.filter((c) => c.path.includes('/autonomy/tasks?status=blocked'));
    expect(asked.length).toBeGreaterThan(0);
    expect(new Set(asked.map((c) => c.path))).toEqual(new Set(['/autonomy/tasks?status=blocked&limit=200']));
  });

  it('commits the loader into the hub snapshot the running head reads', async () => {
    loader.data = { demo: false, serverUp: true, live: true, llm: { state: 'ready', model: 'gemma-4-31b', residents: [] },
      agents: [], sources: { agents: true }, chrome: { gateway: { state: 'running', running: ['web'], total: 1 }, sessions: { active: 2, windowS: 900 }, version: '9.9.9' } };
    start('/v2/build');
    render(<App />);
    await waitFor(() => expect(document.querySelector('[data-signal="data"]')?.getAttribute('data-state')).toBe('live'));
    expect(document.querySelector('[data-signal="data"]')?.textContent).toMatch(/Live · checked \d\d:\d\d/);
    expect(document.querySelector('[data-chrome="version"]')?.textContent).toBe('Nerva 9.9.9');
  });

  it('follows the Ledger keys: 1–9 the areas, 0 the conversation, w World, the backtick the panels, a Glance', async () => {
    // the one registry: the masthead's order on the number keys, none of the HUD v2 rail's ids
    expect(ACTIONS.find((a) => a.chord === '2')?.id).toBe('mode.work');
    expect(ACTIONS.some((a) => a.id === 'mode.comms' || a.id === 'mode.autonomy')).toBe(false);
    start('/v2/cockpit');
    render(<App />);
    await waitFor(() => expect(frame('masthead')).not.toBeNull());
    for (const [key, path] of [['2', '/v2/work'], ['3', '/v2/agents'], ['7', '/v2/interop'], ['9', '/v2/admin'], ['0', '/v2/chat'], ['1', '/v2/cockpit']]) {
      fireEvent.keyDown(window, { key });
      await waitFor(() => expect(location.pathname, key).toBe(path));
    }
    fireEvent.keyDown(window, { key: 'w' });
    await waitFor(() => expect(location.pathname).toBe('/v2/world'));
    expect((await screen.findByTestId('mode-body')).textContent).toBe('World route loaded');
    expect(document.querySelector('[data-frame="masthead"] [aria-current="page"]')?.getAttribute('data-area')).toBe('observe');
    fireEvent.keyDown(window, { key: '`' });
    const panels = sheet() as HTMLElement;
    expect(panels).not.toBeNull();
    expect(panels.querySelector('[data-cmd="scope"]')).not.toBeNull();
    expect(within(panels).getAllByRole('option').every((o) => o.getAttribute('data-command')?.startsWith('page:panel:'))).toBe(true);
    fireEvent.keyDown(within(panels).getByRole('combobox'), { key: 'Escape' });
    expect(sheet()).toBeNull();
    fireEvent.keyDown(window, { key: 'a' });
    await waitFor(() => expect(location.pathname).toBe('/v2/glance'));
    await waitFor(() => expect(document.querySelector('[data-glance]')).not.toBeNull());
    expect(frame('masthead')).toBeNull();
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(frame('masthead')).not.toBeNull());
    expect(location.pathname).toBe('/v2/world');
    expect(location.search).toBe('');
  });

  it('opens the sheet from Find, runs a page from it, and goes to Glance from the masthead', async () => {
    start('/v2/trust');
    render(<App />);
    fireEvent.click(await screen.findByRole('button', { name: /^Search or run a command/ }));
    const open = sheet() as HTMLElement;
    expect(open.querySelector('[data-cmd="scope"]')).toBeNull();
    const field = within(open).getByRole('combobox');
    fireEvent.change(field, { target: { value: 'payments' } });
    expect(within(open).getAllByRole('option')[0].getAttribute('data-command')).toBe('page:panel:payments');
    fireEvent.keyDown(field, { key: 'Enter' });
    await waitFor(() => expect(location.pathname).toBe('/v2/console/payments'));
    expect(sheet()).toBeNull();
    expect((await screen.findByTestId('console-panel')).textContent).toBe('payments');
    expect(document.title).toBe('Payments · Trust · Nerva');
    // the contents column's "Find a panel…" opens it filtered to panels
    fireEvent.click(within(frame('contents') as HTMLElement).getByRole('button', { name: 'Find a panel…' }));
    expect((sheet() as HTMLElement).querySelector('[data-cmd="scope"]')).not.toBeNull();
    fireEvent.keyDown(within(sheet() as HTMLElement).getByRole('combobox'), { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Glance — the day on one quiet screen' }));
    await waitFor(() => expect(location.pathname).toBe('/v2/glance'));
    await waitFor(() => expect(document.querySelector('[data-glance]')).not.toBeNull());
  });

  it('keeps the old palette\'s appearance rows in the sheet, and runs its read-only actions', async () => {
    start('/v2/build');
    render(<App />);
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const open = sheet() as HTMLElement;
    const field = within(open).getByRole('combobox');
    fireEvent.change(field, { target: { value: 'look' } });
    expect(within(open).getAllByRole('option').map((o) => o.textContent)).toEqual(expect.arrayContaining([expect.stringContaining('Look · Ledger ✓')]));
    // Personalisation is found as its page and as the action; the action opens the same page
    fireEvent.change(field, { target: { value: 'personalisation' } });
    const found = within(open).getAllByRole('option').map((o) => o.getAttribute('data-command'));
    expect(found).toEqual(expect.arrayContaining(['page:panel:appearance', 'action:personalisation']));
    fireEvent.click(open.querySelector('[data-command="action:personalisation"]') as HTMLElement);
    await waitFor(() => expect(location.pathname).toBe('/v2/console/appearance'));
    expect(sheet()).toBeNull();
    // the demo sample: on from the sheet, off again (leaving demo clears what it drew)
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    fireEvent.change(within(sheet() as HTMLElement).getByRole('combobox'), { target: { value: 'demo' } });
    fireEvent.keyDown(within(sheet() as HTMLElement).getByRole('combobox'), { key: 'Enter' });
    await waitFor(() => expect(location.search).toContain('demo=1'));
    await waitFor(() => expect(document.querySelector('[data-notice="demo"]')).not.toBeNull());
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    fireEvent.change(within(sheet() as HTMLElement).getByRole('combobox'), { target: { value: 'demo' } });
    fireEvent.keyDown(within(sheet() as HTMLElement).getByRole('combobox'), { key: 'Enter' });
    await waitFor(() => expect(location.search).not.toContain('demo=1'));
  });

  it('writes to an agent from the sheet: the recipient changes, the Dossier stays shut, Home\'s composer takes the focus', async () => {
    loader.data = { demo: false, serverUp: true, live: true, llm: { state: 'ready', model: 'm', residents: [] }, agents: ROSTER, sources: { agents: true } };
    start('/v2/build');
    render(<App />);
    await waitFor(() => expect(frame('masthead')).not.toBeNull());
    fireEvent.click(screen.getByRole('button', { name: /^Search or run a command/ }));
    const field = within(sheet() as HTMLElement).getByRole('combobox');
    fireEvent.change(field, { target: { value: 'write to frigga' } });
    expect(within(sheet() as HTMLElement).getAllByRole('option')[0].getAttribute('data-command')).toBe('agent:write:frigga');
    fireEvent.keyDown(field, { key: 'Enter' });
    await waitFor(() => expect(location.pathname).toBe('/v2/cockpit'));
    await waitFor(() => expect(document.activeElement?.hasAttribute('data-composer')).toBe(true));
    expect(document.querySelector('[data-register="talk"] .n-talk__with b')?.textContent).toBe('Frigga');
  });

  it('titles the document in the owner\'s language', async () => {
    start('/v2/trust');
    render(<App />);
    await waitFor(() => expect(document.title).toBe('Trust · Nerva'));
    fireEvent.click(screen.getByRole('radio', { name: 'Romanian' }));
    await waitFor(() => expect(document.title).toBe('Încredere · Nerva'));
    expect(document.documentElement.lang).toBe('ro');
  });

  it('titles every page in the owner\'s language, page after page, and nothing titles it again in English', async () => {
    start('/v2/trust');
    render(<App />);
    await waitFor(() => expect(document.title).toBe('Trust · Nerva'));
    fireEvent.click(screen.getByRole('radio', { name: 'Romanian' }));
    await waitFor(() => expect(document.title).toBe('Încredere · Nerva'));
    const settled = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    act(() => navigateHud('/v2/build'));
    await waitFor(() => expect(location.pathname).toBe('/v2/build'));
    // every effect of the navigation has run: nothing titled the page again in English
    await settled();
    expect(document.title).toBe('Construire · Nerva');
    act(() => navigateHud('/v2/console/kill-switch'));
    await waitFor(() => expect(location.pathname).toBe('/v2/console/kill-switch'));
    await settled();
    expect(document.title).toBe('Oprire de urgență · Încredere · Nerva');
  });

  it('names the page the router returned to, and withdraws the notice once the owner moves on', async () => {
    start('/v2/nope');
    render(<App />);
    await waitFor(() => expect(document.querySelector('[data-notice="route"]')).not.toBeNull());
    expect(location.pathname).toBe('/v2/cockpit');
    expect(location.search).toBe('');
    expect(document.querySelector('[data-notice="route"]')?.textContent).toContain('Page not found. Returned to Today.');
    act(() => navigateHud('/v2/trust'));
    await waitFor(() => expect(location.pathname).toBe('/v2/trust'));
    await waitFor(() => expect(document.querySelector('[data-notice="route"]')).toBeNull());
    expect(document.body.textContent).not.toMatch(/Returned to (Today|Overview|Trust)/);
  });

  it('opens no cognition stream and asks no cognition snapshot: nothing draws a trace (PHASE_B_PLAN.md §2.4)', async () => {
    const opened: string[] = [];
    class FakeEventSource {
      onmessage: unknown = null;
      onerror: unknown = null;
      constructor(url: string) { opened.push(url); }
      close() {}
    }
    vi.stubGlobal('EventSource', FakeEventSource);
    try {
      start('/v2/cockpit');
      render(<App />);
      await waitFor(() => expect(frame('masthead')).not.toBeNull());
      await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
      // (the power notice's own /api/power/stream may open; only the cognition reads are retired —
      // h595-chat-followup.test.tsx checks that a finished turn asks none either)
      expect(opened.filter((url) => url.includes('/api/cognition'))).toEqual([]);
      expect(fetched().filter((url) => url.includes('/api/cognition'))).toEqual([]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('keeps World a page in the shipped entry: no WORLD button, no overlay, no rail reservation', async () => {
    start('/v2/world');
    render(<App />);
    expect((await screen.findByTestId('mode-body')).textContent).toBe('World route loaded');
    expect(within(frame('page') as HTMLElement).getByTestId('mode-body')).toBeTruthy();
    expect(screen.queryByTitle(/World Intelligence/)).toBeNull();
    expect(screen.queryByText('close · esc')).toBeNull();
    expect([...document.querySelectorAll('style')].some((s) => s.textContent?.includes('.rail'))).toBe(false);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(location.pathname).toBe('/v2/world');
  });

  it('draws the floating window as the conversation page\'s floating variant', async () => {
    start('/v2/chat?desktop=floating');
    render(<App floating />);
    await waitFor(() => expect(document.querySelector('[data-chatpage="floating"]')).not.toBeNull());
    const page = document.querySelector('[data-chatpage="floating"]') as HTMLElement;
    expect(page.querySelector('.n-runhead--marks')).not.toBeNull();
    expect(page.querySelector('[data-register="talk"] [data-composer-variant="floating"]')).not.toBeNull();
    expect(frame('masthead')).toBeNull();
    expect(screen.queryByText('Chat route loaded')).toBeNull();
    // no signing in the floating window: no docket entry is ever drawn there
    expect(page.querySelector('[data-register="docket"], [data-docket-entry]')).toBeNull();
    // all eight running-head items, the mode read there
    expect(page.querySelectorAll('.n-runhead--marks [data-signal]')).toHaveLength(6);
    expect(page.querySelector('.n-runhead--marks [data-runhead="mode"][data-readonly]')).not.toBeNull();
    expect(page.querySelector('.n-runhead--marks [data-runhead="interrupts"]')).not.toBeNull();
    // and no page key moves it off the conversation (its router accepts nothing else)
    for (const key of ['w', 'a', '2', '`']) {
      fireEvent.keyDown(window, { key });
      expect(location.pathname, key).toBe('/v2/chat');
    }
  });
});

