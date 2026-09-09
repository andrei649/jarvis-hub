// @ts-nocheck
/* Safe Comms v0 — live channel inbox rows can queue governed replies through
   /api/channels/inbox/{thread_id}/reply. Seed-only rows remain covered by
   disabled-controls.test.tsx. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { CommsMode } from '../modes3';
import { V2 } from '../data';

const t = V2.I18N.en;

describe('CommsMode — live channel inbox reply transport', () => {
  let original;

  beforeEach(() => {
    original = V2.COMMS;
    V2.COMMS = {
      ...original,
      threads: [{
        id: 'telegram:abc',
        thread_id: 'telegram:abc',
        channel: 'telegram',
        from: 'Andrei',
        agent: 'veronica',
        subj: 'Telegram thread',
        preview: 'ping',
        ts: 'live',
        unread: true,
        dir: 'in',
        replyable: true,
      }],
      channels: [{ id: 'telegram', label: 'Telegram', count: 1 }],
    };
    global.fetch = vi.fn((url, init) => {
      const path = String(url);
      if (/^\/api\/channels\/inbox\/(telegram|slack|discord)%3Aabc\/reply$/.test(path) && init?.method === 'POST') {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, queued: true, task_id: 7 }) });
      }
      return Promise.reject(new Error('unexpected fetch: ' + path));
    }) as any;
  });

  afterEach(() => {
    V2.COMMS = original;
  });

  it.each(['telegram', 'slack', 'discord'])('posts a governed reply draft for a live %s thread', async (channel) => {
    Object.assign(V2.COMMS.threads[0], { id: `${channel}:abc`, thread_id: `${channel}:abc`, channel });
    V2.COMMS.channels = [{ id: channel, label: channel, count: 1 }];
    render(<CommsMode t={t} />);
    fireEvent.change(screen.getByPlaceholderText(/write a governed reply/i), {
      target: { value: 'pong' },
    });
    fireEvent.click(screen.getByText('Queue reply'));

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      `/api/channels/inbox/${channel}%3Aabc/reply`,
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ text: 'pong', agent: 'veronica', source: 'hud.comms' }),
      }),
    ));
    expect(await screen.findByText(/queued for approval/i)).toBeTruthy();
  });
});
