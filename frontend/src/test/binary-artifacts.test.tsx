import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BinaryArtifacts } from '../panels/binary-artifacts';

const row = { id: 'ba-' + 'a'.repeat(32), mime: 'application/pdf', size: 20, agent: 'owner', pinned: false };
afterEach(() => vi.restoreAllMocks());
it('uploads multipart and deletes the attachment card', async () => {
  let items: any[] = [];
  const fetcher = vi.fn(async (_url: any, init: any = {}) => {
    if (init.method === 'POST') { expect(init.body).toBeInstanceOf(FormData); items = [row]; }
    if (init.method === 'DELETE') items = [];
    return { ok: true, json: async () => init.method === 'POST' ? row : { enabled: true, items } } as Response;
  });
  vi.stubGlobal('fetch', fetcher);
  render(<BinaryArtifacts />);
  const input = await screen.findByLabelText('Attach file');
  fireEvent.change(input, { target: { files: [new File(['%PDF-'], 'report.pdf')] } });
  expect(await screen.findByText('application/pdf · 20 bytes')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Delete attachment' }));
  await waitFor(() => expect(screen.queryByText('application/pdf · 20 bytes')).toBeNull());
});
