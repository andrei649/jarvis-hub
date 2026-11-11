import { expect, it, vi } from 'vitest';
import { loadJarvisData } from '../api/loaders';

it('stops the sequential boot waterfall when its document becomes inactive', async () => {
  let finishAgents!: (value: Response) => void;
  const agents = new Promise<Response>((resolve) => { finishAgents = resolve; });
  const paths: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string) => {
    paths.push(url);
    if (url === '/api/agents') return agents;
    return Promise.resolve(new Response('{}', { status: 200 }));
  }) as typeof fetch;
  let active = true;
  try {
    const pending = loadJarvisData(false, () => active);
    expect(paths).toEqual(['/api/agents']);
    active = false;
    finishAgents(new Response('{"agents":[]}', { status: 200 }));
    await pending;
    expect(paths).toEqual(['/api/agents']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
