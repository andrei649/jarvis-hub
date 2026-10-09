import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BriefingWall } from '../../mobile/src/screens/BriefingWall';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import type { WallSnapshot } from '../../mobile/src/api/briefingWall';
import { records } from './support/storage';
import { foreground } from './support/native';

const api = vi.hoisted(() => ({ read: vi.fn(), field: null as any }));
vi.mock('../../mobile/src/api/briefingWall', () => ({ readBriefingWall: api.read }));
vi.mock('../../mobile/src/components/BriefingField', () => ({
  BriefingField: (props: any) => { api.field = props; return <div data-testid="field" />; },
}));
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const available = <T,>(value: T) => ({ status: 'available' as const, value, checkedAt: 1_791_515_400_000 });
const missing = { status: 'unavailable' as const, value: null, checkedAt: 1_791_515_400_000 };
function data(): WallSnapshot {
  return { health: available({ up: true }), agents: available([{ id: 'jarvis', tier: 'CNS', status: 'busy' }]),
    tasks: available([{ owner: 'jarvis', state: 'running' }]),
    trust: available({ mic: 'on', strictLocal: true, cloudAvailable: false }),
    locality: available({ local: 3, cloud: 1, unknown: 2, total: 6, percent: 75 }),
    approvals: available({ pending: 2 }), calendar: available({ returned: 3 }),
    model: available({ state: 'ready', residentCount: 1 }),
    voice: available({ stt: true, tts: true, ttsLocal: false, localOnly: false }),
    heartbeat: available({ running: true, scheduled: 4, blocked: 1 }) };
}
let server: ReturnType<typeof useServer>;
function Probe({ context = 'visit-one', transcript = 'Sensitive spoken text' }: { context?: string; transcript?: string }) {
  server = useServer();
  return <BriefingWall contextKey={context} voice={{ status: 'off' }} transcript={transcript} onExit={() => {}} />;
}
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
beforeEach(() => {
  records.clear(); foreground('active'); api.field = null;
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'wall-one' }));
  api.read.mockReset().mockResolvedValue(data());
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('shows source-backed metrics and keeps private transcript absent until explicitly shown', async () => {
  mount();
  expect(await screen.findByLabelText('Served locally: 75%')).toBeTruthy();
  expect(screen.getByLabelText('Running in task feed: 1')).toBeTruthy();
  expect(screen.getByText('Running entries among the latest 30 tasks.')).toBeTruthy();
  expect(screen.getByLabelText('Pending decisions returned: 2')).toBeTruthy();
  expect(screen.getByLabelText('Calendar events in sample: 3')).toBeTruthy();
  expect(screen.getByLabelText('Server model report: ready')).toBeTruthy();
  expect(screen.getByLabelText('Resident models reported: 1')).toBeTruthy();
  expect(screen.getByLabelText('Server STT capability: yes')).toBeTruthy();
  expect(screen.getByLabelText('Server TTS capability: yes')).toBeTruthy();
  expect(screen.getByLabelText('Local TTS capability: no')).toBeTruthy();
  expect(screen.getByLabelText('Local-only voice policy: no')).toBeTruthy();
  expect(screen.getByLabelText('Scheduler reported running: yes')).toBeTruthy();
  expect(screen.getByLabelText('Scheduled jobs: 4')).toBeTruthy();
  expect(screen.getByLabelText('Quarantined schedules: 1')).toBeTruthy();
  expect(screen.getByText('Dictate to draft').compareDocumentPosition(screen.getByText('Cabinet · reported activity'))
    & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByText('Sensitive spoken text')).toBeNull();
  fireEvent.click(screen.getByLabelText('Show room transcript'));
  expect(screen.getByText('Sensitive spoken text')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Hide room transcript'));
  expect(screen.queryByText('Sensitive spoken text')).toBeNull();
});

it('distinguishes unavailable feeds from successful zero and unknown locality', async () => {
  api.read.mockResolvedValue({ ...data(), agents: missing, tasks: missing,
    locality: available({ local: 0, cloud: 0, unknown: 4, total: 4, percent: null }),
    approvals: missing, calendar: missing, model: missing, voice: missing, heartbeat: missing });
  mount(); await screen.findByText('activity unknown');
  expect(screen.getByLabelText('Agents in roster: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Running in task feed: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Served locally: unavailable')).toBeTruthy();
  for (const label of ['Pending decisions returned', 'Calendar events in sample', 'Server model report',
    'Server STT capability', 'Scheduled jobs']) {
    expect(screen.getByLabelText(`${label}: unavailable`)).toBeTruthy();
  }
  expect(api.field).toMatchObject({ agents: [], tasks: [], agentsAvailable: false, tasksAvailable: false });
  api.read.mockResolvedValue({ ...data(), agents: available([]), tasks: available([]),
    approvals: available({ pending: 0 }), calendar: available({ returned: 1 }),
    model: available({ state: 'unknown', residentCount: 0 }),
    voice: available({ stt: false, tts: false, ttsLocal: false, localOnly: false }),
    heartbeat: available({ running: false, scheduled: 0, blocked: 0 }) });
  fireEvent.click(screen.getByLabelText('Refresh briefing'));
  expect(await screen.findByLabelText('Running in task feed: 0')).toBeTruthy();
  expect(screen.getByText('standing by')).toBeTruthy();
  expect(screen.getByLabelText('Pending decisions returned: 0')).toBeTruthy();
  expect(screen.getByLabelText('Calendar events in sample: 1')).toBeTruthy();
  expect(screen.getByLabelText('Server model report: unknown')).toBeTruthy();
  expect(screen.getByLabelText('Resident models reported: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Server STT capability: no')).toBeTruthy();
  expect(screen.getByLabelText('Scheduled jobs: 0')).toBeTruthy();
  expect(screen.getByLabelText('Quarantined schedules: 0')).toBeTruthy();
});

it('removes previous evidence while refreshing and never retains work after a failed source', async () => {
  mount(); await screen.findByText('working');
  let finish!: (value: WallSnapshot) => void;
  api.read.mockImplementationOnce(() => new Promise<WallSnapshot>(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByLabelText('Refresh briefing'));
  expect(screen.queryByText('working')).toBeNull();
  expect(api.field.agents).toEqual([]);
  expect(screen.getByLabelText('Agents in roster: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Pending decisions returned: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Scheduled jobs: unavailable')).toBeTruthy();
  await act(async () => finish({ ...data(), agents: missing, tasks: missing, health: missing, trust: missing,
    approvals: missing, calendar: missing, model: missing, voice: missing, heartbeat: missing }));
  expect(screen.getByText('status unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Mic trust: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Server model report: unavailable')).toBeTruthy();
});

it('hides a shown transcript and cancels source reads in background; foreground refreshes afresh', async () => {
  mount(); await screen.findByText('working');
  fireEvent.click(screen.getByLabelText('Show room transcript'));
  let finish!: (value: WallSnapshot) => void;
  let signal!: AbortSignal;
  api.read.mockImplementationOnce((_config, nextSignal) => { signal = nextSignal; return new Promise(resolve => { finish = resolve; }); });
  fireEvent.click(screen.getByLabelText('Refresh briefing'));
  act(() => foreground('background'));
  expect(signal.aborted).toBe(true);
  expect(screen.getByText('briefing paused')).toBeTruthy();
  expect(screen.getByLabelText('Pending decisions returned: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Calendar events in sample: unavailable')).toBeTruthy();
  expect(screen.queryByText('Sensitive spoken text')).toBeNull();
  await act(async () => finish(data()));
  expect(screen.queryByText('working')).toBeNull();
  act(() => foreground('active'));
  expect(await screen.findByText('working')).toBeTruthy();
  expect(screen.queryByText('Sensitive spoken text')).toBeNull();
});

it('rejects an old hub response and resets transcript visibility on a connection save', async () => {
  mount(); await screen.findByText('working');
  fireEvent.click(screen.getByLabelText('Show room transcript'));
  let finish!: (value: WallSnapshot) => void;
  api.read.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByLabelText('Refresh briefing'));
  api.read.mockResolvedValue({ ...data(), agents: available([]), tasks: available([]),
    approvals: available({ pending: 0 }), calendar: missing,
    model: available({ state: 'offline', residentCount: 0 }),
    voice: available({ stt: false, tts: false, ttsLocal: false, localOnly: false }),
    heartbeat: available({ running: false, scheduled: 0, blocked: 0 }) });
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  await act(async () => finish(data()));
  expect(await screen.findByText('standing by')).toBeTruthy();
  expect(screen.getByLabelText('Agents in roster: 0')).toBeTruthy();
  expect(screen.getByLabelText('Pending decisions returned: 0')).toBeTruthy();
  expect(screen.getByLabelText('Calendar events in sample: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Server model report: offline')).toBeTruthy();
  expect(screen.getByLabelText('Resident models reported: unavailable')).toBeTruthy();
  expect(screen.getByLabelText('Server STT capability: no')).toBeTruthy();
  expect(screen.getByLabelText('Scheduled jobs: 0')).toBeTruthy();
  expect(screen.queryByText('Sensitive spoken text')).toBeNull();
});

it('renders a reported no-model state in plain language with an actual zero inventory', async () => {
  api.read.mockResolvedValue({ ...data(), model: available({ state: 'no_model', residentCount: 0 }) });
  mount();
  expect(await screen.findByLabelText('Server model report: no model')).toBeTruthy();
  expect(screen.getByLabelText('Resident models reported: 0')).toBeTruthy();
});

it('shows only projected count/status fields and source scope, never diagnostic or event copy', async () => {
  api.read.mockResolvedValue({ ...data(), approvals: available({ pending: 1, title: 'Private decision' }),
    calendar: available({ returned: 2, title: 'Secret appointment' }),
    model: available({ state: 'unknown', residentCount: 0, provider: 'Internal endpoint' }),
    heartbeat: available({ running: true, scheduled: 1, blocked: 0, path: '/private/heartbeat' }) });
  mount();
  expect(await screen.findByLabelText('Pending decisions returned: 1')).toBeTruthy();
  expect(screen.getByText(/Returned decisions, up to 100/)).toBeTruthy();
  expect(screen.getByText(/Calendar sample, up to 10/)).toBeTruthy();
  expect(screen.getByText(/not proof of responsiveness/)).toBeTruthy();
  expect(screen.getByText(/not mic permission or consent/)).toBeTruthy();
  expect(screen.getByText(/not past execution/)).toBeTruthy();
  for (const privateText of ['Private decision', 'Secret appointment', 'Internal endpoint', '/private/heartbeat']) {
    expect(screen.queryByText(privateText)).toBeNull();
  }
  for (const source of ['approvals', 'calendar', 'model', 'voice', 'heartbeat']) {
    expect(screen.getByLabelText(`${source}: reported`)).toBeTruthy();
  }
});

it('polls only after a completed refresh and removes polling on unmount', async () => {
  const ui = mount(); await screen.findByText('working');
  vi.useFakeTimers();
  fireEvent.click(screen.getByLabelText('Refresh briefing'));
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  const calls = api.read.mock.calls.length;
  await act(async () => vi.advanceTimersByTimeAsync(14999));
  expect(api.read).toHaveBeenCalledTimes(calls);
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(api.read).toHaveBeenCalledTimes(calls + 1);
  ui.unmount();
  await act(async () => vi.advanceTimersByTimeAsync(60000));
  expect(api.read).toHaveBeenCalledTimes(calls + 1);
});
