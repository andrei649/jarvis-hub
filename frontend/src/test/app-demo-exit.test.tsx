import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  loadJarvisData: vi.fn(),
}));

vi.mock('../api/loaders', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/loaders')>();
  return { ...actual, loadJarvisData: mocks.loadJarvisData };
});

vi.mock('../api/client', () => ({
  apiGet: mocks.apiGet,
  postStream: vi.fn(),
}));

vi.mock('../api/live', () => ({
  PREVIEW_MODE_LIVE_KEYS: {},
  useLiveModes: () => ({ live: {} }),
}));

vi.mock('../analytics', () => ({ initAnalytics: vi.fn(), trackPageview: vi.fn() }));
vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: vi.fn() }) }));
vi.mock('../LiveSourceChip', () => ({ LiveSourceChip: () => null, liveSourceState: () => null }));

vi.mock('../primitives', () => ({
  useClock: () => new Date(0),
  fmtTimeShort: () => '00:00',
  Icon: () => null,
  Glyph: () => null,
  ICONS: { brain: '' },
}));

vi.mock('../shell', async () => {
  const { createElement } = await import('react');
  const output = (testId: string, value: unknown) => createElement(
    'output',
    { 'data-testid': testId },
    JSON.stringify(value),
  );
  return {
    TopBar: (props: any) => output('topbar-evidence', {
      agents: props.agents,
      localPct: props.localPct,
      live: props.live,
      trust: props.trust,
      llm: props.llm,
      demo: props.demo,
      serverUp: props.serverUp,
    }),
    Ticker: ({ items }: any) => output('ticker-evidence', items),
    RosterColumn: (props: any) => output('roster-evidence', {
      agents: props.agents,
      sys: props.sys,
      llm: props.llm,
    }),
    ContextColumn: (props: any) => output('context-evidence', {
      decisions: props.decisions,
      weather: props.weather,
      calendar: props.calendar,
      heartbeat: props.heartbeat,
    }),
    Rail: () => null,
    Tabs: () => null,
    Palette: () => null,
    Ambient: () => null,
    CinemaMesh: (props: any) => output('cinema-evidence', props),
  };
});

vi.mock('../cockpit', async () => {
  const { createElement } = await import('react');
  return {
    Conversation: ({ messages }: any) => createElement(
      'output',
      { 'data-testid': 'conversation-evidence' },
      JSON.stringify(messages),
    ),
    CognitionStream: () => null,
    InputBar: () => null,
    buildTrace: () => ({ stages: [], selected: [], conf: 0 }),
    traceFromCognition: () => ({ stages: [], selected: [], conf: 0 }),
  };
});

vi.mock('../mesh', async () => {
  const { createElement } = await import('react');
  return {
    NeuralMesh: (props: any) => createElement(
      'output',
      { 'data-testid': 'mesh-evidence' },
      JSON.stringify({
        agents: props.agents,
        tasks: props.tasks,
        llm: props.llm,
        trust: props.trust,
        sources: props.sources,
        demo: props.demo,
      }),
    ),
  };
});

vi.mock('../modes', () => ({
  AgentsMode: () => null,
  Dossier: () => null,
  TrustMode: () => null,
  MemoryMode: () => null,
}));
vi.mock('../modes2', () => ({
  AutonomyMode: () => null,
  BuildMode: () => null,
  ObserveMode: () => null,
  InteropMode: () => null,
}));
vi.mock('../modes3', () => ({ ChatMode: () => null, CommsMode: () => null, AdminMode: () => null }));
vi.mock('../modes4', () => ({
  FinanceMode: () => null,
  HealthMode: () => null,
  KnowledgeMode: () => null,
  FamilyMode: () => null,
}));
vi.mock('../gap', () => ({
  ConsoleOverlay: () => null,
  FirstRunGate: () => null,
  shouldShowFirstRun: () => false,
  FIRST_RUN_DISMISS_KEY: 'hud.first-run-dismissed',
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
const EMPTY_TRUST = { mic: 'on', strict_local: false };
const EMPTY_SOURCES = { tasks: false, trust: false };

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

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/v2/?demo=1');
  mocks.apiGet.mockReset();
  mocks.apiGet.mockResolvedValue({});
  mocks.loadJarvisData.mockReset();
});

describe('App demo-to-live provenance', () => {
  it('clears seeded evidence with the URL and rejects a late demo refresh', async () => {
    const staleDemo = deferred<any>();
    const currentLive = deferred<any>();
    mocks.loadJarvisData.mockImplementation((demo: boolean) => (
      demo ? staleDemo.promise : currentLive.promise
    ));

    render(<App />);
    await waitFor(() => expect(mocks.loadJarvisData).toHaveBeenCalledWith(true));
    expect(screen.getByText(/DEMO DATA/)).toBeTruthy();
    expect(document.body.textContent).toContain('Morning Jarvis');
    expect(document.body.textContent).toContain('Raiffeisen quarterly review');
    expect(document.body.textContent).toContain('Bucharest');

    fireEvent.click(screen.getByRole('button', { name: 'exit demo' }));

    expect(window.location.search).toBe('');
    expect(screen.queryByText(/DEMO DATA/)).toBeNull();
    expect(document.body.textContent).not.toContain('Morning Jarvis');
    expect(document.body.textContent).not.toContain('Raiffeisen quarterly review');
    expect(document.body.textContent).not.toContain('Bucharest');
    expect(JSON.parse(screen.getByTestId('topbar-evidence').textContent || '{}')).toEqual({
      agents: [],
      localPct: null,
      live: false,
      trust: EMPTY_TRUST,
      llm: UNKNOWN_LLM,
      demo: false,
      serverUp: false,
    });
    expect(JSON.parse(screen.getByTestId('ticker-evidence').textContent || 'null')).toEqual([]);
    expect(JSON.parse(screen.getByTestId('roster-evidence').textContent || '{}')).toEqual({
      agents: [], sys: null, llm: UNKNOWN_LLM,
    });
    expect(JSON.parse(screen.getByTestId('conversation-evidence').textContent || 'null')).toEqual([]);
    expect(JSON.parse(screen.getByTestId('context-evidence').textContent || '{}')).toEqual({
      decisions: [], weather: null, calendar: [], heartbeat: [],
    });
    expect(JSON.parse(screen.getByTestId('mesh-evidence').textContent || '{}')).toEqual({
      agents: [],
      tasks: [],
      llm: UNKNOWN_LLM,
      trust: EMPTY_TRUST,
      sources: EMPTY_SOURCES,
      demo: false,
    });

    await waitFor(() => expect(mocks.loadJarvisData).toHaveBeenCalledWith(false));
    await act(async () => { staleDemo.resolve(dataSnapshot('STALE DEMO', true)); });
    expect(document.body.textContent).not.toContain('STALE DEMO');
    expect(document.body.textContent).not.toContain('Morning Jarvis');

    await act(async () => { currentLive.resolve(dataSnapshot('CURRENT LIVE', false)); });
    await waitFor(() => expect(document.body.textContent).toContain('CURRENT LIVE AGENT'));
    expect(document.body.textContent).not.toContain('STALE DEMO');
  });
});
