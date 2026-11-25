/* Leaving the demo is a provenance boundary, not a URL toggle (PHASE_B_PLAN.md §8.3, rewritten for
   the Ledger frame at the cutover). In the click that exits the demo every demo-owned surface is
   cleared before the demo notice goes: the conversation's seed, the roster, and the hub snapshot
   the frame and Home read (the day, the docket's demo flag, the running head). A demo refresh still
   in flight when the owner leaves is rejected, and only the next live answer is drawn.

   Home is a stand-in that writes out what App hands it (the hub snapshot, the conversation, the
   demo flag) on every render, so a render that mixes the demo's evidence into the live page is
   caught even if a later effect repairs it. The frame around it is the real one: its notice and
   its running head ("Data on screen") are read from the page. */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { V2 } from '../data';
import { resetPolling } from '../signals/poll';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  loadJarvisData: vi.fn(),
}));

/** What App hands Home on each render, as plain data. */
const home = vi.hoisted(() => ({
  renders: [] as Array<Record<string, any>>,
  evidence(props: any): Record<string, any> {
    const hub = props.hub;
    return {
      demo: props.demo,
      hub: {
        state: hub.state, demo: hub.demo, serverUp: hub.serverUp, agents: hub.agents, weather: hub.weather,
        calendar: hub.calendar, ticker: hub.ticker, tasks: hub.tasks, llm: hub.llm, trust: hub.trust, sys: hub.sys,
        locality: hub.locality, sources: hub.sources,
      },
      messages: props.talk.messages,
      agents: props.talk.agents,
      agent: props.talk.agent,
      outcome: props.talk.outcome,
      turns: props.turns,
    };
  },
}));

vi.mock('../home/Home', async () => {
  const { createElement } = await import('react');
  return {
    Home: (props: any) => {
      const evidence = home.evidence(props);
      home.renders.push(evidence);
      return createElement('output', { 'data-testid': 'home-evidence' }, JSON.stringify(evidence));
    },
  };
});

vi.mock('../api/loaders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/loaders')>();
  return { ...actual, loadJarvisData: mocks.loadJarvisData };
});

vi.mock('../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../api/client')>(),
  apiGet: mocks.apiGet,
  postStream: vi.fn(),
}));

vi.mock('../api/live', () => ({
  PREVIEW_MODE_LIVE_KEYS: {},
  useLiveModes: () => ({ live: {} }),
}));

vi.mock('../analytics', () => ({ initAnalytics: vi.fn(), trackPageview: vi.fn() }));
vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: vi.fn(), status: 'idle' }) }));
vi.mock('../LiveSourceChip', () => ({ LiveSourceChip: () => null, liveSourceState: () => null }));

vi.mock('../primitives', () => ({
  useClock: () => new Date(0),
  fmtTimeShort: () => '00:00',
  Icon: () => null,
  Glyph: () => null,
  ICONS: { brain: '' },
}));

// Cinema is all that is left of the HUD v2 shell module (and the only place the mesh is drawn since
// the cutover): a stand-in that writes out the inputs App hands it, so a Cinema left open across the
// demo's exit is checked like Home.
vi.mock('../shell', async () => {
  const { createElement } = await import('react');
  return {
    CinemaMesh: (props: any) => createElement('output', { 'data-testid': 'cinema-evidence' }, JSON.stringify({
      demo: props.demo, agents: props.agents, tasks: props.tasks, llm: props.llm, trust: props.trust, sources: props.sources,
      localPct: props.localPct ?? null, localPctSource: props.localPctSource ?? null, decisions: props.decisions,
      calendar: props.calendar, heartbeat: props.heartbeat, serverUp: props.serverUp,
    })),
  };
});

vi.mock('../cockpit', () => ({
  Conversation: () => null,
  InputBar: () => null,
}));

vi.mock('../mesh', () => ({ NeuralMesh: () => null }));

vi.mock('../modes', () => ({
  AgentsMode: () => null,
  Dossier: () => null,
  MemoryMode: () => null,
}));
vi.mock('../modes2', () => ({
  AutonomyMode: () => null,
  BuildMode: () => null,
  ObserveMode: () => null,
  InteropMode: () => null,
}));
vi.mock('../modes3', () => ({ CommsMode: () => null, AdminMode: () => null }));
vi.mock('../modes4', () => ({
  FinanceMode: () => null,
  HealthMode: () => null,
  KnowledgeMode: () => null,
  FamilyMode: () => null,
}));
vi.mock('../gap', () => ({
  ConsolePanel: () => null,
  FirstRunGate: () => null,
  ProjectsMode: () => null,
}));
vi.mock('../artifacts', () => ({ ArtifactsPanel: () => null, artifactsTabLabel: () => 'Artifacts' }));

import App from '../app';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const UNKNOWN_LLM = { state: 'unknown', model: null, residents: [] };
/** The hub snapshot before the first live answer: Checking…, nothing carried over. */
const CHECKING_HUB = {
  state: 'unknown', demo: false, serverUp: false, agents: [], weather: null, calendar: [], ticker: [], tasks: [],
  llm: UNKNOWN_LLM, trust: null, sys: null, locality: null, sources: {},
};

function dataSnapshot(label: string, demo: boolean) {
  return {
    demo,
    serverUp: true,
    live: true,
    agents: [{ id: label.toLowerCase(), name: `${label} AGENT`, status: 'active' }],
    sys: { cpu: label },
    ticker: [{ text: `${label} TICKER` }],
    weather: { city: `${label} WEATHER` },
    calendar: [{ ti: `${label} CALENDAR` }],
    heartbeat: [{ x: `${label} HEARTBEAT` }],
    tasks: [{ id: `${label} TASK`, state: 'running' }],
    llm: { state: 'ready', model: `${label} MODEL`, residents: [{ provider: 'ollama', id: `${label} MODEL` }] },
    trust: { mic: 'off', strict_local: true },
    sources: { tasks: true, trust: true },
  };
}

/** The demo's evidence: App's own seed, and what the demo loader committed. */
const DEMO_EVIDENCE = ['Morning Jarvis', 'Raiffeisen quarterly review', 'Bucharest', 'SEEDED DEMO'];

const latest = () => home.renders[home.renders.length - 1];
const dataSignal = () => document.querySelector('[data-frame="runhead"] [data-signal="data"]')?.getAttribute('data-state') ?? null;
const demoCalls = () => mocks.loadJarvisData.mock.calls.filter(([demo]) => demo === true);

beforeEach(() => {
  resetPolling();
  localStorage.clear();
  localStorage.setItem('hud.seen', '1');
  window.history.replaceState({}, '', '/v2/?demo=1');
  home.renders.length = 0;
  mocks.apiGet.mockReset();
  mocks.apiGet.mockResolvedValue({});
  mocks.loadJarvisData.mockReset();
});

describe('App demo-to-live provenance', () => {
  it('clears seeded evidence with the URL and rejects a late demo refresh', async () => {
    const seededDemo = deferred<any>();
    const staleDemo = deferred<any>();
    const currentLive = deferred<any>();
    const demoCycles = [seededDemo, staleDemo];
    mocks.loadJarvisData.mockImplementation((demo: boolean) => (
      demo ? (demoCycles.shift() ?? deferred<any>()).promise : currentLive.promise
    ));

    render(<App />);
    await waitFor(() => expect(mocks.loadJarvisData).toHaveBeenCalledWith(true, expect.any(Function)));
    const firstScope = demoCalls()[0][1] as () => boolean;
    expect(firstScope()).toBe(true);
    // the demo notice, and App's own seed handed to Home
    expect(screen.getByText('Demo sample on screen — seeded data, not your live hub.')).toBeTruthy();
    expect(latest().demo).toBe(true);
    expect(latest().hub.state).toBe('demo');
    expect(latest().agents).toEqual(V2.AGENTS);

    // the demo loader commits its corpus: the hub carries it to Home and the frame
    await act(async () => { seededDemo.resolve({ ...dataSnapshot('SEEDED DEMO', true), weather: V2.WEATHER, calendar: V2.CALENDAR }); });
    for (const seen of DEMO_EVIDENCE) expect(document.body.textContent).toContain(seen);
    expect(dataSignal()).toBe('demo');

    // a second demo refresh is asked (the sheet's "Refresh live data") and is still in flight
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    const sheet = screen.getByRole('dialog', { name: 'Search or run a command' });
    fireEvent.change(within(sheet).getByRole('combobox'), { target: { value: 'refresh' } });
    fireEvent.click(sheet.querySelector('[data-command="action:refresh"]') as HTMLElement);
    await waitFor(() => expect(demoCalls()).toHaveLength(2));
    const lateScope = demoCalls()[1][1] as () => boolean;
    expect(lateScope()).toBe(true);

    const beforeExit = home.renders.length;
    fireEvent.click(screen.getByRole('button', { name: 'Exit demo' }));

    expect(window.location.search).toBe('');
    expect(document.querySelector('[data-notice="demo"]')).toBeNull();
    expect(screen.queryByText(/Demo sample on screen/)).toBeNull();
    for (const seen of DEMO_EVIDENCE) expect(document.body.textContent).not.toContain(seen);
    // in the same event: no render of the live page ever carried the demo's evidence or its label
    const afterExit = home.renders.slice(beforeExit);
    expect(afterExit.length).toBeGreaterThan(0);
    for (const r of afterExit) {
      expect(r.demo).toBe(false);
      expect(r.hub.demo, 'a live render still holding the demo hub').toBe(false);
      expect(r.hub.state).not.toBe('demo');
      for (const seen of DEMO_EVIDENCE) expect(JSON.stringify(r)).not.toContain(seen);
    }
    expect(latest()).toEqual({
      demo: false, hub: CHECKING_HUB, messages: [], agents: [], agent: 'jarvis', outcome: null, turns: [],
    });
    // the running head says it is checking: neither the demo sample nor live
    expect(dataSignal()).toBe('unknown');

    await waitFor(() => expect(mocks.loadJarvisData).toHaveBeenCalledWith(false, expect.any(Function)));
    const liveScope = mocks.loadJarvisData.mock.calls.find(([demo]) => demo === false)![1] as () => boolean;
    expect(firstScope()).toBe(false);
    expect(lateScope()).toBe(false);
    expect(liveScope()).toBe(true);

    // the demo refresh that was in flight lands late: nothing of it is drawn
    await act(async () => { staleDemo.resolve(dataSnapshot('STALE DEMO', true)); });
    expect(document.body.textContent).not.toContain('STALE DEMO');
    expect(document.body.textContent).not.toContain('Morning Jarvis');
    expect(latest().hub).toEqual(CHECKING_HUB);
    expect(dataSignal()).toBe('unknown');

    await act(async () => { currentLive.resolve(dataSnapshot('CURRENT LIVE', false)); });
    await waitFor(() => expect(document.body.textContent).toContain('CURRENT LIVE AGENT'));
    expect(document.body.textContent).not.toContain('STALE DEMO');
    expect(latest().demo).toBe(false);
    expect(latest().hub.state).toBe('live');
    expect(latest().hub.agents).toEqual([{ id: 'current live', name: 'CURRENT LIVE AGENT', status: 'active' }]);
    await waitFor(() => expect(dataSignal()).toBe('live'));
  });

  // the old shell's mesh-evidence claim, moved to Cinema (PHASE_B_PLAN.md §8.2 row 31: the mesh lives
  // in Cinema now): leaving the demo with Cinema open hands it no demo evidence, in the same event
  it('clears what Cinema draws from in the click that exits the demo', async () => {
    const seededDemo = deferred<any>();
    mocks.loadJarvisData.mockImplementation((demo: boolean) => (demo ? seededDemo.promise : deferred<any>().promise));
    render(<App />);
    await act(async () => { seededDemo.resolve({ ...dataSnapshot('SEEDED DEMO', true), weather: V2.WEATHER, calendar: V2.CALENDAR }); });
    fireEvent.keyDown(window, { key: 'm' });
    const cinema = () => JSON.parse(screen.getByTestId('cinema-evidence').textContent || '{}');
    expect(cinema().demo).toBe(true);
    expect(JSON.stringify(cinema())).toContain('SEEDED DEMO');
    expect(cinema().localPct).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Exit demo' }));
    const after = cinema();
    expect(after).toMatchObject({
      demo: false, agents: [], tasks: [], llm: UNKNOWN_LLM, localPct: null, localPctSource: null,
      decisions: [], calendar: [], heartbeat: [], serverUp: false,
    });
    for (const seen of [...DEMO_EVIDENCE, 'SEEDED DEMO']) expect(JSON.stringify(after)).not.toContain(seen);
  });
});
