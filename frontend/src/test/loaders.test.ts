// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { loadJarvisData } from '../api/loaders';
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
    global.fetch = fetchMock as any;

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
    global.fetch = fetchMock as any;

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
});
