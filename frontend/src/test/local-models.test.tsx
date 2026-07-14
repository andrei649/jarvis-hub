// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { mapLocalModelsForAdmin, localModelStatus } from '../api/live';
import { LMStudioPanel } from '../gap';

const controls = (can_configure = false, can_load = false, can_unload = false) => ({
  can_configure, can_load, can_unload,
});

const INVENTORY = {
  models: [
    { id: 'resident', provider: 'lm-studio', available: true, configured: false, resident: true, controls: controls(true, false, true) },
    { id: 'unknown', provider: 'lm-studio', available: true, configured: true, resident: null, controls: controls(false, false, false) },
    { id: 'loadable', provider: 'lm-studio', available: true, configured: false, resident: false, controls: controls(true, true, false) },
    { id: 'catalog-unknown', provider: 'lm-studio', available: null, configured: false, resident: false, controls: controls(false, false, false) },
    { id: 'missing', provider: 'lm-studio', available: false, configured: false, active: true, resident: false, controls: controls(false, false, false) },
    { id: 'ollama-ready', provider: 'ollama', available: true, configured: false, resident: false, controls: controls(true, false, false) },
  ],
};

function mockInventory() {
  const fetchMock = vi.fn((url: string) => Promise.resolve({
    ok: true,
    status: 200,
    json: async () => url === '/api/models/local' ? INVENTORY : { ok: true, status: 'ok' },
  }));
  global.fetch = fetchMock as any;
  return fetchMock;
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('local model truth adapter', () => {
  it('uses resident/available precedence and preserves configured plus controls', () => {
    expect(INVENTORY.models.map(localModelStatus)).toEqual([
      'loaded',
      'residency unknown',
      'ready',
      'availability unknown',
      'unavailable',
      'ready',
    ]);

    const mapped = mapLocalModelsForAdmin(INVENTORY.models);
    expect(mapped.map((row) => row.status)).toEqual([
      'loaded',
      'residency unknown',
      'ready',
      'availability unknown',
      'unavailable',
      'ready',
    ]);
    expect(mapped[1]).toMatchObject({
      id: 'unknown', provider: 'lm-studio', configured: true, resident: null,
      controls: controls(false, false, false),
    });
  });
});

describe('LMStudioPanel truthful controls', () => {
  it('renders residency independently from configured state and removes free-form lifecycle', async () => {
    mockInventory();
    render(<LMStudioPanel />);

    await waitFor(() => expect(screen.getByText('resident')).toBeTruthy());
    expect(screen.getByText('loaded')).toBeTruthy();
    expect(screen.getByText('residency unknown')).toBeTruthy();
    expect(screen.getAllByText('ready').length).toBe(2);
    expect(screen.getByText('availability unknown')).toBeTruthy();
    expect(screen.getByText('unavailable')).toBeTruthy();
    expect(screen.getByText('configured')).toBeTruthy();
    expect(screen.queryByPlaceholderText('model id')).toBeNull();
  });

  it('offers only capability-declared actions and never sends Ollama to LM Studio lifecycle', async () => {
    const fetchMock = mockInventory();
    render(<LMStudioPanel />);
    await waitFor(() => expect(screen.getByText('resident')).toBeTruthy());

    expect(screen.getByTitle('unload lm-studio:resident')).toBeTruthy();
    expect(screen.getByTitle('load lm-studio:loadable')).toBeTruthy();
    expect(screen.getByTitle('configure ollama:ollama-ready')).toBeTruthy();
    expect(screen.queryByTitle('load ollama:ollama-ready')).toBeNull();
    expect(screen.queryByTitle('unload ollama:ollama-ready')).toBeNull();

    fireEvent.click(screen.getByTitle('configure ollama:ollama-ready'));
    fireEvent.click(screen.getByTitle('load lm-studio:loadable'));
    fireEvent.click(screen.getByTitle('unload lm-studio:resident'));

    await waitFor(() => {
      const posts = fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST');
      expect(posts.some(([url, init]) => url === '/api/models/local/switch'
        && JSON.parse(init.body).model === 'ollama-ready')).toBe(true);
      expect(posts.some(([url, init]) => url === '/api/llm/load'
        && JSON.parse(init.body).model === 'loadable')).toBe(true);
      expect(posts.some(([url, init]) => url === '/api/llm/unload'
        && JSON.parse(init.body).model === 'resident')).toBe(true);
      expect(posts.some(([url, init]) => String(url).startsWith('/api/llm/')
        && JSON.parse(init.body || '{}').model === 'ollama-ready')).toBe(false);
    });
  });
});
