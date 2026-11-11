// @ts-nocheck
/* H443 — the APM card reads one conversation's usage by purpose from
   GET /api/analytics/session-usage as the admin: the background review's calls are a line
   of their own, and a call that was never measured is a count, not invented tokens. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { SESSION_USAGE_PATH, SessionUsage, usageLine } from '../panels/session-usage';

let calls;
let answer;

function reply(code, data) {
  return { ok: code < 400, status: code, json: async () => data, text: async () => JSON.stringify(data) };
}

beforeEach(() => {
  cleanup();
  localStorage.setItem('hud.admin_token', 'adm');
  calls = [];
  answer = () => reply(200, {
    session_id: 'web 1', found: true,
    usage: {
      calls: 3, input_tokens: 1400, output_tokens: 300, cost_usd: 0, unmeasured_calls: 1, updated_at: 1,
      purposes: {
        turn: { calls: 2, input_tokens: 1200, output_tokens: 260, cost_usd: 0 },
        background_review: { calls: 1, input_tokens: 200, output_tokens: 40, cost_usd: 0, unmeasured_calls: 1 },
      },
    },
  });
  global.fetch = vi.fn(async (url, init = {}) => {
    const headers = init.headers || {};
    calls.push({ url: String(url), method: init.method || 'GET', admin: headers['X-Admin-Token'] });
    return answer();
  });
});

describe('SessionUsage — H443 one conversation by purpose', () => {
  it('reads the named conversation as the admin and gives the review its own line', async () => {
    render(<SessionUsage />);
    expect(calls.length).toBe(0);                                   // nothing is read until asked
    fireEvent.change(screen.getByLabelText('conversation id'), { target: { value: 'web 1' } });
    fireEvent.click(screen.getByText('usage'));
    await waitFor(() => expect(screen.getByLabelText('background review usage')).toBeTruthy());
    expect(calls[0].url.endsWith(`${SESSION_USAGE_PATH}?session_id=web%201`)).toBe(true);
    expect(calls[0].admin).toBe('adm');
    expect(screen.getByLabelText('background review usage').textContent).toBe('1 calls · 200 in · 40 out · 1 unmeasured');
    expect(screen.getByLabelText('turns usage').textContent).toBe('2 calls · 1,200 in · 260 out');
  });

  it('says a conversation has no usage rather than showing zeros, and shows a refusal', async () => {
    answer = () => reply(200, { session_id: 'nobody', found: false, usage: null });
    render(<SessionUsage />);
    fireEvent.click(screen.getByText('usage'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('no usage recorded for nobody'));

    answer = () => reply(403, { error: 'admin required' });
    fireEvent.click(screen.getByText('usage'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('not read · admin required'));
  });

  it('words a row from what the ledger holds', () => {
    expect(usageLine({ calls: 0, input_tokens: 0, output_tokens: 0, unmeasured_calls: 2 }))
      .toBe('0 calls · 0 in · 0 out · 2 unmeasured');
    expect(usageLine(undefined)).toBe('0 calls · 0 in · 0 out');
  });
});
