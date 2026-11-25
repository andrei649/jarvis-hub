/* Tests only: a stand-in hub behind window.fetch, so the frame's tests run the real API client
   (credential headers, the failed-mutation sink, refusal bodies) and the real shared poller.
   `answer(method, path, body)` returns the hub's answer, or 'down' for no answer at all. */

export type HubAnswer = { status: number; body?: unknown } | 'down';
export type HubCall = { method: string; path: string; body: unknown };

/** Replace window.fetch with `answer`; returns every call made, in order. Undo with
 *  vi.unstubAllGlobals() (or restore `globalThis.fetch` yourself). */
export function stubHub(answer: (method: string, path: string, body: unknown) => HubAnswer,
  stub: (name: string, value: unknown) => void): HubCall[] {
  const calls: HubCall[] = [];
  stub('fetch', async (url: string, init: { method?: string; body?: unknown } = {}) => {
    const method = init.method || 'GET';
    let body: unknown;
    try { body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined; } catch { body = init.body; }
    calls.push({ method, path: String(url), body });
    const reply = answer(method, String(url), body);
    if (reply === 'down') throw new TypeError('Failed to fetch');
    const payload = reply.body ?? {};
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: async () => payload,
      clone() { return this; },
      headers: { get: () => 'application/json' },
    };
  });
  return calls;
}

/** The kill switch's public status, as the hub answers it. */
export const ARMED = Object.freeze({ global: false, any_halted: false, halted_count: 0 });
export const HALTED = Object.freeze({ global: true, any_halted: true, halted_count: 3 });
