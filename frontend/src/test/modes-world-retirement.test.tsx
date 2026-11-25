import { afterEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { WorldIntelligenceMode } from '../modes_world';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const healthy = {
  '/provider-health/worldmonitor': { status: 'ok', provider: 'worldmonitor', mode: 'replay' },
  '/briefs/world': { title: 'Independent brief', executiveSummary: 'Source-backed summary', recommendations: [], sources: [] },
  '/signals': { signals: [], evidence: [] },
};

function service(available: () => boolean) {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const key = Object.keys(healthy).find((path) => String(input).includes(path));
    return { ok: available() && key !== undefined, status: available() ? 200 : 503,
      json: async () => healthy[key as keyof typeof healthy] } as Response;
  });
  vi.stubGlobal('fetch', fetcher);
  return fetcher;
}

function expectRetired(fetcher: ReturnType<typeof service>) {
  expect(screen.queryByText(/worldview/i)).toBeNull();
  expect(screen.queryByText(/quickstart\.sh/)).toBeNull();
  expect(document.querySelector('a[href="http://localhost:3000"]')).toBeNull();
  expect(fetcher.mock.calls.some(([url]) => /worldview/i.test(String(url)))).toBe(false);
}

describe('World tab after WorldView retirement', () => {
  it('keeps Signal Layer briefs without requesting or offering WorldView', async () => {
    const fetcher = service(() => true);
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('Source-backed summary')).toBeTruthy());
    expectRetired(fetcher);
  });

  it('reports Signal Layer unavailability without a retired-service startup hint', async () => {
    const fetcher = service(() => false);
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('SIGNAL LAYER UNAVAILABLE')).toBeTruthy());
    expectRetired(fetcher);
  });

  it('recovers through retry using only Signal Layer', async () => {
    let available = false;
    const fetcher = service(() => available);
    render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(screen.getByText('SIGNAL LAYER UNAVAILABLE')).toBeTruthy());
    available = true;
    fireEvent.click(screen.getByText('retry'));
    await waitFor(() => expect(screen.getByText('Source-backed summary')).toBeTruthy());
    expectRetired(fetcher);
  });
});

describe('World tab after it is closed', () => {
  it('writes no state when a Signal Layer reply lands after the page and its window are gone', async () => {
    const release: Array<() => void> = [];
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => new Promise<Response>((resolve) => {
      const key = Object.keys(healthy).find((path) => String(input).includes(path));
      release.push(() => resolve({ ok: true, status: 200,
        json: async () => healthy[key as keyof typeof healthy] } as Response));
    })));
    const { unmount } = render(<WorldIntelligenceMode t={(s: string) => s} />);
    await waitFor(() => expect(release.length).toBe(3));
    unmount();
    const late: unknown[] = [];
    const record = (reason: unknown) => { late.push(reason); };
    process.on('unhandledRejection', record);
    // The test environment is torn down the same way once a file finishes.
    vi.stubGlobal('window', undefined);
    try {
      release.forEach((go) => go());
      await new Promise((done) => setTimeout(done, 30));
    } finally {
      vi.unstubAllGlobals();
      process.off('unhandledRejection', record);
    }
    expect(late).toEqual([]);
  });
});
