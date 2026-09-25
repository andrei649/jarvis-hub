// @ts-nocheck
/* H441 — the Sessions panel resumes a session and shows the hub's recap: the last
   exchanges, each turn on one line, the tools a reply used as a count. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { RESUME_PATH, SessionsPanel, toolLine } from '../panels/sessions';

let calls;
let resumeReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const RECAP = {
  shown: 2, total: 5,
  exchanges: [
    [{ role: 'user', text: 'is it raining?', agent: '', tool_calls: 0, tools: [] },
     { role: 'assistant', text: 'No, sunny.', agent: 'jarvis', tool_calls: 3, tools: ['web_search', 'web_fetch'] }],
    [{ role: 'user', text: '<b>bold</b>', agent: '', tool_calls: 0, tools: [] },
     { role: 'assistant', text: 'ok', agent: '', tool_calls: 0, tools: [] }],
  ],
  text: 'Previous conversation (the last 2 of 5 exchanges):',
};

beforeEach(() => {
  cleanup();
  calls = [];
  resumeReply = () => reply(200, { ok: true, session: 's-old', turns: [], recap: RECAP });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    if (u.endsWith('/sessions')) return reply(200, { sessions: [{ session_id: 's-old', turns: 10 }, { session_id: 's-new' }] });
    if (u.endsWith(RESUME_PATH)) return resumeReply();
    return reply(404, {});
  });
});

describe('SessionsPanel — H441 recap', () => {
  it('resumes and shows the recap, tools as a count, newest exchanges', async () => {
    const { container } = render(<SessionsPanel />);
    await waitFor(() => expect(screen.getByText('s-old')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('resume s-old'));
    await waitFor(() => expect(screen.getByTestId('session-recap')).toBeTruthy());
    const post = calls.find((c) => c.url.endsWith(RESUME_PATH));
    expect(post.method).toBe('POST');
    expect(post.body).toEqual({ session_id: 's-old' });
    expect(screen.getByText(/RESUMED s-old · LAST 2 OF 5 EXCHANGES/)).toBeTruthy();
    expect(screen.getAllByTestId('recap-exchange')).toHaveLength(2);
    expect(screen.getByText('[3 tool calls: web_search, web_fetch]')).toBeTruthy();
    expect(screen.getByText('<b>bold</b>')).toBeTruthy();          // text, never markup
    expect(container.querySelector('b')).toBeNull();
    expect(screen.getByText(/nerva:/)).toBeTruthy();                // a reply with no agent name
  });

  it('names a refusal and shows no stale recap', async () => {
    render(<SessionsPanel />);
    await waitFor(() => expect(screen.getByText('s-old')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('resume s-old'));
    await waitFor(() => expect(screen.getByTestId('session-recap')).toBeTruthy());
    resumeReply = () => reply(404, { error: "session 's-new' not found" });
    fireEvent.click(screen.getByLabelText('resume s-new'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('not resumed'));
    expect(screen.queryByTestId('session-recap')).toBeNull();
  });

  it('says it resumed when the hub sent no recap, and formats tool lines', async () => {
    resumeReply = () => reply(200, { ok: true, session: 's-old', turns: [] });
    render(<SessionsPanel />);
    await waitFor(() => expect(screen.getByText('s-old')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('resume s-old'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('resumed s-old'));
    expect(toolLine({ tool_calls: 1, tools: ['terminal_run'] })).toBe('[1 tool call: terminal_run]');
    expect(toolLine({ tool_calls: 0 })).toBe('');
  });
});
