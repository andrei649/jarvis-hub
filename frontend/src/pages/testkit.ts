/* Test support for the Phase B pages: a hub fixture and a request router for the mocked apiGet.
   Not imported by the app. */
import { vi } from 'vitest';
import { initialHubSnapshot } from '../frame/types';
import type { HubSnapshot } from '../signals/types';

/** A live hub snapshot, with whatever the test overrides. */
export function hubFixture(over: Partial<HubSnapshot> = {}): HubSnapshot {
  const now = Date.now();
  return {
    ...initialHubSnapshot(false),
    state: 'live', reason: undefined, serverUp: true, checkedAt: now, lastGoodAt: now,
    agents: [
      { id: 'jarvis', name: 'Jarvis', role: 'Chief of staff' }, { id: 'pepper', name: 'Pepper', role: 'Scheduling' },
      { id: 'stark', name: 'Stark', role: 'Research' }, { id: 'athena', name: 'Athena', role: 'Cloud analyst' },
      { id: 'frigga', name: 'Frigga', role: 'Family' },
    ],
    sources: { agents: true, trust: true },
    ...over,
  } as HubSnapshot;
}

export const httpError = (status: number) => Object.assign(new Error(`GET -> ${status}`), { status });

/** Routes a mocked apiGet(path, opts) by path: a value answers, an Error rejects, a function is called;
 *  a path no route names rejects with a 404, so a test never silently gets a made-up answer. */
export function routeGet(get: ReturnType<typeof vi.fn>, routes: Record<string, unknown>) {
  get.mockImplementation((path: string) => {
    const key = Object.keys(routes).find((k) => path === k) ?? Object.keys(routes).find((k) => path.startsWith(k));
    if (!key) return Promise.reject(httpError(404));
    const v = routes[key];
    if (v instanceof Error) return Promise.reject(v);
    return Promise.resolve(typeof v === 'function' ? (v as (p: string) => unknown)(path) : v);
  });
}

/** Epoch seconds N minutes ago, as the hub's audit rows carry them. */
export const secondsAgo = (minutes: number) => (Date.now() - minutes * 60_000) / 1000;
/** An ISO stamp N minutes ago, as the queue's rows carry them. */
export const isoAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
