import React from 'react';
import { act, render } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useLiveModes } from '../api/live';
import { V2 } from '../data';

function Harness() { useLiveModes(); return null; }

it('does not start later live-mode requests after the owning page unmounts', async () => {
  let finishMemory!: (value: Response) => void;
  const memory = new Promise<Response>((resolve) => { finishMemory = resolve; });
  const paths: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string) => {
    paths.push(url);
    if (url === '/memory/stats') return memory;
    return Promise.resolve(new Response('{}', { status: 200 }));
  }) as typeof fetch;
  try {
    const view = render(<Harness />);
    expect(paths).toEqual(['/memory/stats']);
    view.unmount();
    await act(async () => {
      finishMemory(new Response('{}', { status: 200 }));
      await memory;
      await Promise.resolve();
    });
    expect(paths).toEqual(['/memory/stats']);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

it('does not start later live-mode requests after browser pagehide', async () => {
  let finishMemory!: (value: Response) => void;
  const memory = new Promise<Response>((resolve) => { finishMemory = resolve; });
  const paths: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string) => {
    paths.push(url);
    if (url === '/memory/stats') return memory;
    return Promise.resolve(new Response('{}', { status: 200 }));
  }) as typeof fetch;
  try {
    const view = render(<Harness />);
    expect(paths).toEqual(['/memory/stats']);
    window.dispatchEvent(new Event('pagehide'));
    await act(async () => {
      finishMemory(new Response('{}', { status: 200 }));
      await memory;
      await Promise.resolve();
    });
    expect(paths).toEqual(['/memory/stats']);
    view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

it('does not advance the request waterfall between beforeunload and pagehide', async () => {
  let finishMemory!: (value: Response) => void;
  const memory = new Promise<Response>((resolve) => { finishMemory = resolve; });
  const paths: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string) => {
    paths.push(url);
    if (url === '/memory/stats') return memory;
    return Promise.resolve(new Response('{}', { status: 200 }));
  }) as typeof fetch;
  try {
    const view = render(<Harness />);
    window.dispatchEvent(new Event('beforeunload'));
    await act(async () => {
      finishMemory(new Response('{}', { status: 200 }));
      await memory;
      await Promise.resolve();
    });
    expect(paths).toEqual(['/memory/stats']);
    view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
  }
});

it('keeps periodic refresh usable when a beforeunload navigation is canceled', async () => {
  vi.useFakeTimers();
  let finishMemory!: (value: Response) => void;
  const memory = new Promise<Response>((resolve) => { finishMemory = resolve; });
  const paths: string[] = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn((url: string) => {
    paths.push(url);
    if (url === '/memory/stats' && paths.length === 1) return memory;
    return Promise.resolve(new Response('{}', { status: 200 }));
  }) as typeof fetch;
  try {
    const view = render(<Harness />);
    window.dispatchEvent(new Event('beforeunload'));
    await act(async () => {
      finishMemory(new Response('{}', { status: 200 }));
      await memory;
      await Promise.resolve();
    });
    expect(paths).toEqual(['/memory/stats']);
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
    expect(paths.filter((path) => path === '/memory/stats')).toHaveLength(2);
    view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
  }
});

it('resumes after persisted pageshow without publishing the previous generation', async () => {
  let finishOld!: (value: Response) => void;
  let finishNew!: (value: Response) => void;
  const oldMemory = new Promise<Response>((resolve) => { finishOld = resolve; });
  const newMemory = new Promise<Response>((resolve) => { finishNew = resolve; });
  const originalFetch = globalThis.fetch;
  const originalStats = V2.MEMORY_STATS;
  const paths: string[] = [];
  globalThis.fetch = vi.fn((url: string) => {
    paths.push(url);
    if (url === '/memory/stats') return paths.filter((path) => path === url).length === 1 ? oldMemory : newMemory;
    return Promise.resolve(new Response('{}', { status: 200 }));
  }) as typeof fetch;
  try {
    const view = render(<Harness />);
    window.dispatchEvent(new Event('pagehide'));
    const show = new Event('pageshow');
    Object.defineProperty(show, 'persisted', { value: true });
    window.dispatchEvent(show);
    expect(paths).toEqual(['/memory/stats', '/memory/stats']);
    await act(async () => {
      finishOld(new Response(JSON.stringify({ sessions: { total: 999 } }), { status: 200 }));
      await oldMemory;
      await Promise.resolve();
    });
    expect(V2.MEMORY_STATS).toBe(originalStats);
    await act(async () => {
      finishNew(new Response(JSON.stringify({ sessions: { total: 2 } }), { status: 200 }));
      await newMemory;
      await Promise.resolve();
    });
    expect(V2.MEMORY_STATS.sessions).toBe(2);
    view.unmount();
  } finally {
    globalThis.fetch = originalFetch;
    V2.MEMORY_STATS = originalStats;
  }
});
