// @ts-nocheck
/* 0.46 — the Console MediaGalleryPanel reads the generated-media catalog
   (GET /api/media/catalog) and renders items + per-kind stats. fetch is mocked
   (like skill-history-panel.test.tsx). Asserts the wiring, item rows, and the
   honesty banner when the catalog is disabled (flag off). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MediaGalleryPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('MediaGalleryPanel — the media catalog read surface is live', () => {
  it('GETs /api/media/catalog and renders items + per-kind stats', async () => {
    const fn = mockFetch({
      enabled: true,
      stats: { total: 2, cloud: 0, by_kind: { image: 1, video: 1 } },
      items: [
        { id: 'md-1', kind: 'image', prompt: 'a red bicycle' },
        { id: 'md-2', kind: 'video', prompt: 'a sunset timelapse' },
      ],
    });
    render(<MediaGalleryPanel />);
    await waitFor(() => expect(screen.getByText('a red bicycle')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/media/catalog'))).toBe(true);
    expect(screen.getByText('1 image')).toBeTruthy();
  });

  it('shows the honesty banner when the catalog is disabled (flag off)', async () => {
    mockFetch({ enabled: false, items: [], stats: { total: 0, cloud: 0, by_kind: {} } });
    render(<MediaGalleryPanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_MEDIA_CATALOG is on/)).toBeTruthy());
  });
});
