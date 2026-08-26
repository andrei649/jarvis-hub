import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createLatestRefreshRunner, loadJarvisData } from '../api/loaders';
import { deriveMeshModels } from '../mesh';
import { effectiveTaskState, runningTasks } from '../task-state';

const ok = (payload: unknown) => Promise.resolve({
  ok: true,
  status: 200,
  json: async () => payload,
});

const unavailable = () => Promise.resolve({
  ok: false,
  status: 503,
  json: async () => ({}),
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('task-state normalization', () => {
  it('uses the first non-empty state before status and normalizes exact running', () => {
    expect(effectiveTaskState({ state: ' DONE ', status: 'running' })).toBe('done');
    expect(effectiveTaskState({ state: '   ', status: ' RUNNING ' })).toBe('running');
    expect(effectiveTaskState({ state: null, status: 42 })).toBe('');
    expect(runningTasks([
      { id: 'state-wins', state: 'done', status: 'running' },
      { id: 'status-fallback', state: '', status: ' RUNNING ' },
      { id: 'exact', state: 'running' },
      { id: 'active-is-not-running', state: 'active' },
    ]).map((task) => task.id)).toEqual(['status-fallback', 'exact']);
  });
});

describe('loadJarvisData current-evidence adapters', () => {
  it('retains all resident provider/id pairs and defensively filters the running view', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/status') return ok({
        model_state: 'ready',
        loaded_model: 'alpha',
        resident_models: [
          { provider: 'lm-studio', id: 'alpha' },
          { provider: 'ollama', id: 'alpha' },
          { provider: 'ollama', id: 'beta' },
        ],
      });
      if (url === '/tasks?view=running') return ok({
        tasks: [
          { id: 'running-state', owner: 'jarvis', state: 'running' },
          { id: 'terminal', owner: 'jarvis', state: 'done' },
          { id: 'fallback-status', agent: 'howard', state: ' ', status: ' RUNNING ' },
          { id: 'state-precedence', agent: 'frigga', state: 'blocked', status: 'running' },
        ],
      });
      if (url === '/api/trust/status') return ok({
        mic: 'off', strict_local: false, cloud_available: true, claude_available: true,
      });
      return unavailable();
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const data = await loadJarvisData(false);

    expect(data.llm).toEqual({
      state: 'ready',
      model: 'alpha',
      residents: [
        { provider: 'lm-studio', id: 'alpha' },
        { provider: 'ollama', id: 'alpha' },
        { provider: 'ollama', id: 'beta' },
      ],
    });
    expect(data.tasks.map((task) => task.id)).toEqual(['running-state', 'fallback-status']);
    expect(data.sources.tasks).toBe(true);
    expect(data.sources.trust).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => url === '/tasks')).toBe(false);
  });

  it('starts each cycle with fresh task/trust source evidence, including successful empty tasks', async () => {
    let trustCalls = 0;
    const fetchMock = vi.fn((url: string) => {
      if (url === '/status') return ok({ model_state: 'no_model', loaded_model: null, resident_models: [] });
      if (url === '/tasks?view=running') return ok({ tasks: [] });
      if (url === '/api/trust/status') {
        trustCalls += 1;
        return trustCalls === 1
          ? ok({ mic: 'on', strict_local: false, cloud_available: true, claude_available: true })
          : unavailable();
      }
      return unavailable();
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const first = await loadJarvisData(false);
    const second = await loadJarvisData(false);

    expect(first.sources.tasks).toBe(true);
    expect(first.sources.trust).toBe(true);
    expect(first.trust.claude_available).toBe(true);
    expect(second.sources).not.toBe(first.sources);
    expect(second.sources.tasks).toBe(true);
    expect(second.sources.trust).toBe(false);
    expect(second.trust.claude_available).toBeUndefined();
    expect(second.trust.cloud_available).toBeUndefined();
  });

  it('requires literal trust booleans before the Mesh can create a cloud lane', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/status') return ok({ model_state: 'no_model', loaded_model: null, resident_models: [] });
      if (url === '/tasks?view=running') return ok({ tasks: [] });
      if (url === '/api/trust/status') return ok({
        mic: 'on', strict_local: false, cloud_available: 'true', claude_available: 1,
      });
      return unavailable();
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const data = await loadJarvisData(false);
    const models = deriveMeshModels({
      demo: false,
      residents: data.llm.residents,
      trustEvidence: data.sources.trust,
      trust: data.trust,
    });

    expect(data.trust.cloud_available).toBe(false);
    expect(data.trust.claude_available).toBe(false);
    expect(models).toEqual([]);
  });
});

describe('loadJarvisData degraded roster parity', () => {
  it('keeps registry-only agents in the /status fallback instead of the stale 15-seed roster', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url === '/status') return ok({
        model_state: 'no_model',
        agents: [
          { id: 'jarvis', status: 'ready' },
          { id: 'howard', status: 'idle' },
          { id: 'hestia', status: 'idle' },
        ],
      });
      return unavailable(); // /api/agents and everything else down
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const data = await loadJarvisData(false);

    const ids = data.agents.map((a) => a.id);
    expect(ids).toContain('howard');
    expect(ids).toContain('hestia');
    expect(ids).toContain('jarvis');
  });
});

describe('latest refresh runner', () => {
  it('does not let an older data cycle overwrite a newer snapshot', async () => {
    const oldData = deferred<{ id: string }>();
    const newData = deferred<{ id: string }>();
    const committed: string[] = [];
    const loadData = vi.fn()
      .mockImplementationOnce(() => oldData.promise)
      .mockImplementationOnce(() => newData.promise);
    const runner = createLatestRefreshRunner<{ id: string }, { local_pct: number }>({
      loadData,
      loadLocality: async () => ({ local_pct: 50 }),
      commitData: (data) => committed.push(data.id),
      commitLocality: () => {},
    });

    const first = runner.refresh();
    const second = runner.refresh();
    newData.resolve({ id: 'new' });
    await second;
    oldData.resolve({ id: 'old' });
    await first;

    expect(committed).toEqual(['new']);
  });

  it('ignores an older locality completion and clears locality on a current failure', async () => {
    const oldLocality = deferred<{ local_pct: number }>();
    const newLocality = deferred<{ local_pct: number }>();
    const committed: Array<number | null> = [];
    const loadLocality = vi.fn()
      .mockImplementationOnce(() => oldLocality.promise)
      .mockImplementationOnce(() => newLocality.promise)
      .mockRejectedValueOnce(new Error('offline'));
    const runner = createLatestRefreshRunner<{ ok: boolean }, { local_pct: number }>({
      loadData: async () => ({ ok: true }),
      loadLocality,
      commitData: () => {},
      commitLocality: (value) => committed.push(value?.local_pct ?? null),
    });

    const first = runner.refresh();
    await vi.waitFor(() => expect(loadLocality).toHaveBeenCalledTimes(1));
    const second = runner.refresh();
    await vi.waitFor(() => expect(loadLocality).toHaveBeenCalledTimes(2));
    newLocality.resolve({ local_pct: 91 });
    await second;
    oldLocality.resolve({ local_pct: 12 });
    await first;

    expect(committed).toEqual([91]);

    await runner.refresh();
    expect(committed).toEqual([91, null]);
  });
});
