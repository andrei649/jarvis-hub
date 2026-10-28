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
