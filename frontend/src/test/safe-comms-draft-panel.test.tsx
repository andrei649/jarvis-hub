// @ts-nocheck
/* 0.44 — Safe Comms draft-before-send UI. The Console panel must use the
   already-governed social endpoint: load the catalog, collect a draft, and POST
   it into the approval path. It must not imply a direct send or channel inbox
   transport. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SafeCommsDraftPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch() {
  const fn = vi.fn().mockImplementation((url, opts = {}) => {
    if (String(url).includes('/api/integrations/social') && opts.method === 'POST') {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          status: 'queued',
          task_id: 42,
          kind: 'social.x.reply',
        }),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        targets: [
          {
            platform: 'x',
            action: 'post',
            label: 'Post to X',
            required: ['text'],
            kind: 'social.x.post',
          },
          {
            platform: 'x',
            action: 'reply',
            label: 'Reply on X',
            required: ['text', 'reply_to'],
            kind: 'social.x.reply',
          },
        ],
      }),
    });
  });
  global.fetch = fn;
  return fn;
}

describe('SafeCommsDraftPanel — social drafts go through approval, not direct send', () => {
  it('loads governed social actions and queues a reply draft for approval', async () => {
    const fn = mockFetch();
    render(<SafeCommsDraftPanel />);

    await waitFor(() => expect(screen.getAllByText('Reply on X').length).toBeGreaterThan(0));
    expect(screen.getByText(/approval queue/i)).toBeTruthy();

    fireEvent.change(screen.getByLabelText('social action'), { target: { value: 'x:reply' } });
    fireEvent.change(screen.getByPlaceholderText('draft text'), { target: { value: 'Thanks, I will review this tonight.' } });
    fireEvent.change(screen.getByPlaceholderText('reply_to / recipient'), { target: { value: 'tweet-123' } });
    fireEvent.change(screen.getByPlaceholderText('agent'), { target: { value: 'pepper' } });
    fireEvent.click(screen.getByText('queue draft'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/integrations/social') && c[1]?.method === 'POST');
      expect(post).toBeTruthy();
      expect(JSON.parse(post[1].body)).toEqual({
        platform: 'x',
        action: 'reply',
        fields: {
          text: 'Thanks, I will review this tonight.',
          reply_to: 'tweet-123',
        },
        agent: 'pepper',
        source: 'hud.safe_comms_draft',
      });
      expect(screen.getByText(/queued.*42/i)).toBeTruthy();
    });
  });
});
