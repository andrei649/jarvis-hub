// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserBrokerPanel } from './browser-broker';

const baseSnapshot = {
  principal_id: 'owner-1',
  sessions: [
    {
      session_id: 'bsess_alpha1234',
      principal_id: 'owner-1',
      label: 'remote-chromium',
      capabilities: ['navigate', 'snapshot'],
      allow_private_urls: false,
      transport: 'queue',
      live: true,
      expires_at: 9999999999,
    },
  ],
  artifacts: [
    {
      artifact_id: 'bart_img1',
      session_id: 'bsess_alpha1234',
      filename: 'page.png',
      mime_type: 'image/png',
      uploaded: true,
      size_bytes: 2048,
      sha256: 'abc123',
    },
  ],
  recent_commands: [
    {
      command_id: 'bcmd_1',
      session_id: 'bsess_alpha1234',
      action: 'navigate',
      status: 'completed',
    },
  ],
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('BrowserBrokerPanel (H086)', () => {
  it('renders identity-scoped sessions, dispatches steps, and mints one-shot tickets', async () => {
    const calls = [];
    global.fetch = vi.fn(async (url, init = {}) => {
      const path = String(url);
      calls.push([path, init]);
      if (path.endsWith('/steps')) {
        return { ok: true, status: 200, json: async () => ({ command_id: 'bcmd_2', status: 'queued' }) };
      }
      if (path.endsWith('/upload-ticket')) {
        return { ok: true, status: 200, json: async () => ({ artifact_id: 'bart_new', upload_ticket: 'utok_1' }) };
      }
      if (path.endsWith('/download-ticket')) {
        return { ok: true, status: 200, json: async () => ({ artifact_id: 'bart_img1', download_ticket: 'dtok_1' }) };
      }
      if (path.includes('/commands/')) {
        return { ok: true, status: 200, json: async () => ({ command_id: 'bcmd_1', status: 'completed' }) };
      }
      return { ok: true, status: 200, json: async () => baseSnapshot };
    });

    render(<BrowserBrokerPanel />);
    await screen.findByText(/remote-chromium/);

    fireEvent.click(screen.getByText('dispatch step'));
    await waitFor(() => expect(calls.some(([u]) => u.includes('/steps'))).toBe(true));

    fireEvent.click(screen.getByText('mint upload ticket'));
    await waitFor(() => expect(calls.some(([u]) => u.includes('/upload-ticket'))).toBe(true));

    fireEvent.click(screen.getByText('mint download ticket'));
    await waitFor(() => expect(calls.some(([u]) => u.includes('/download-ticket'))).toBe(true));

    fireEvent.click(screen.getByText('inspect'));
    await waitFor(() => expect(calls.some(([u]) => u.includes('/commands/bcmd_1'))).toBe(true));
  });
});
