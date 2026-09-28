// @ts-nocheck
/* H153 fourth review: useApi shows an answer unless a newer one is already shown. Keeping
   only the newest request's answer starved a poller slower than its interval: every
   answer arrived after the next request had started, so none was shown. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import React from 'react';
import { render, screen, cleanup, act, fireEvent } from '@testing-library/react';
import { useApi } from '../panel-kit';
import { ModelSetupPanel } from '../panels/model-setup';

afterEach(() => { vi.useRealTimers(); cleanup(); });

function reply(body) {
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
}

function Probe({ path = '/api/x' }) {
  const { d, loading, reload } = useApi(path, true);
  return (
    <div>
      <span data-testid="d">{d ? d.n : '-'}</span>
      <span data-testid="loading">{loading ? 'loading' : 'idle'}</span>
      <button onClick={reload}>reload</button>
    </div>
  );
}

/** fetch that answers each request only when the test releases it. */
function held() {
  const pending = [];
  global.fetch = vi.fn((url) => new Promise((resolve) => {
    pending.push({ url: String(url), release: (n) => resolve(reply({ n })) });
  }));
  return pending;
}

const shown = () => screen.getByTestId('d').textContent;
const loading = () => screen.getByTestId('loading').textContent;
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

describe('useApi', () => {
  it('keeps a poller slower than its interval up to date', async () => {
    vi.useFakeTimers();
    const t0 = Date.now();
    global.fetch = vi.fn(() => new Promise((resolve) => {
      const status = Date.now() - t0 < 5000 ? 'running' : 'completed';
      const body = { recommendation: { tier: 'mid', model: 'qwen3:8b', approx_gb: 5, reasons: [] },
                     ollama: { present: true, models: [] },
                     pull: { enabled: true, max_gb: 20, job: { model: 'qwen3:8b', status } } };
      setTimeout(() => resolve(reply(body)), 3100);       // slower than the panel's 3 s poll
    }));
    render(<ModelSetupPanel />);
    for (let i = 0; i < 20; i += 1) {
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    }
    expect(screen.getByTestId('pull-job').textContent).toContain('completed');
  });

  it('shows an earlier answer that lands first, and stays loading until the newest lands', async () => {
    const pending = held();
    render(<Probe />);
    await settle();
    fireEvent.click(screen.getByText('reload'));
    await settle();
    expect(pending).toHaveLength(2);
    await act(async () => { pending[0].release(1); });
    expect(shown()).toBe('1');                           // nothing newer is shown yet
    expect(loading()).toBe('loading');                   // the newer read is still out
    await act(async () => { pending[1].release(2); });
    expect(shown()).toBe('2');
    expect(loading()).toBe('idle');
  });

  it('never lets an earlier answer replace a newer one', async () => {
    const pending = held();
    render(<Probe />);
    await settle();
    fireEvent.click(screen.getByText('reload'));
    await settle();
    await act(async () => { pending[1].release(2); });
    expect(shown()).toBe('2');
    expect(loading()).toBe('idle');
    await act(async () => { pending[0].release(1); });
    expect(shown()).toBe('2');
    expect(loading()).toBe('idle');
  });

  it('never shows an answer to a request made for the address it had before', async () => {
    const pending = held();
    const { rerender } = render(<Probe path="/api/old" />);
    await settle();
    rerender(<Probe path="/api/new" />);
    await settle();
    expect(pending.map((p) => p.url.endsWith('/api/new'))).toEqual([false, true]);
    await act(async () => { pending[0].release(1); });  // the old address answers late
    expect(shown()).toBe('-');
    expect(loading()).toBe('loading');
    await act(async () => { pending[1].release(2); });
    expect(shown()).toBe('2');
  });
});
