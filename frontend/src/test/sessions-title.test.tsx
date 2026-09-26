// @ts-nocheck
/* H413 — the Sessions panel shows a session's title (with a short id beside it), and the
   bare id when a session has no title yet. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import { SessionsPanel } from '../panels/sessions';

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

beforeEach(() => {
  cleanup();
  global.fetch = vi.fn(async (url) => {
    if (String(url).endsWith('/sessions')) {
      return reply(200, { sessions: [
        { id: 'abcdef1234567890', title: 'Weekend trip to Brașov', title_source: 'model', turn_count: 4 },
        { id: 'untitled-session-id', title: '', title_source: '' },
      ] });
    }
    return reply(404, {});
  });
});

describe('SessionsPanel — H413 titles', () => {
  it('shows the title with a short id, and the id when there is no title', async () => {
    render(<SessionsPanel />);
    await waitFor(() => expect(screen.getByText('Weekend trip to Brașov')).toBeTruthy());
    expect(screen.getByText('abcdef12')).toBeTruthy();
    expect(screen.getByTitle('abcdef1234567890')).toBeTruthy();
    expect(screen.getByText('untitled-session-id')).toBeTruthy();
    expect(screen.getByLabelText('resume abcdef1234567890')).toBeTruthy();
  });
});
