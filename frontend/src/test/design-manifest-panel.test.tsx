// @ts-nocheck
/* T-0.53 — the Console DesignManifestPanel reads the design-system manifest
   (GET /api/design-manifest, open) and renders token/component counts + the
   variant chips. fetch is mocked (like model-info-panel.test.tsx). Asserts the
   wiring, the summary counts, and the honest offline state when the stylesheet
   is missing (mirrors the core module's own honest-error contract). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { DesignManifestPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('DesignManifestPanel — the design-token read surface is live', () => {
  it('GETs /api/design-manifest and renders source + counts + variant chips', async () => {
    const fn = mockFetch({
      source: 'styles.css',
      tokens: {
        base: { '--accent': '#2bb8f0', '--font-ui': 'X' },
        variants: { 'data-accent=amber': { '--accent': '#ffb23f' }, 'data-look=graphite': {} },
      },
      components: ['panel', 'topbar', 'bubble'],
      counts: { base_tokens: 2, variants: 2, components: 3 },
    });
    render(<DesignManifestPanel />);
    await waitFor(() => expect(screen.getByText('styles.css')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/design-manifest'))).toBe(true);
    expect(screen.getByText('2 tokens · 3 components')).toBeTruthy();
    expect(screen.getByText('data-accent=amber')).toBeTruthy();
    expect(screen.getByText('data-look=graphite')).toBeTruthy();
  });

  it('shows an honest offline state when the stylesheet is missing', async () => {
    mockFetch({ error: 'stylesheet not found: /nope/styles.css' });
    render(<DesignManifestPanel />);
    await waitFor(() => expect(screen.getByText(/stylesheet not found/)).toBeTruthy());
  });
});
