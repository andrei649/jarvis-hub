import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BinaryCard } from '../panels/binary-artifacts';

const item = { id: 'ba-' + 'a'.repeat(32), mime: 'image/png', size: 4, agent: 'owner', pinned: false };
const createURL = vi.fn(() => 'blob:attachment-preview');
const revokeURL = vi.fn();
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function response(blob: () => Promise<Blob>) {
  return { ok: true, headers: new Headers(), blob } as Response;
}
beforeEach(() => {
  createURL.mockClear(); revokeURL.mockClear();
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = createURL;
    static revokeObjectURL = revokeURL;
  });
});
afterEach(() => vi.unstubAllGlobals());

it('ignores a fetch response that arrives after the card unmounts', async () => {
  const pending = deferred<Response>();
  const fetcher = vi.fn(() => pending.promise);
  vi.stubGlobal('fetch', fetcher);
  const card = render(<BinaryCard item={item} refresh={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Load attachment' }));
  card.unmount();
  await act(async () => pending.resolve(response(async () => new Blob(['data'], { type: item.mime }))));
  expect(createURL).not.toHaveBeenCalled();
  expect((fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].signal?.aborted).toBe(true);
});

it('ignores a body that completes after the card unmounts', async () => {
  const pending = deferred<Blob>();
  const readBody = vi.fn(() => pending.promise);
  vi.stubGlobal('fetch', vi.fn(async () => response(readBody)));
  const card = render(<BinaryCard item={item} refresh={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Load attachment' }));
  await waitFor(() => expect(readBody).toHaveBeenCalledOnce());
  card.unmount();
  await act(async () => pending.resolve(new Blob(['data'], { type: item.mime })));
  expect(createURL).not.toHaveBeenCalled();
});

it('keeps successful previews downloadable and revokes them on unmount', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => response(async () => new Blob(['data'], { type: item.mime }))));
  const card = render(<BinaryCard item={item} refresh={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Load attachment' }));
  expect((await screen.findByRole('link', { name: 'Download attachment' })).getAttribute('href')).toBe('blob:attachment-preview');
  card.unmount();
  expect(revokeURL).toHaveBeenCalledExactlyOnceWith('blob:attachment-preview');
});

it('allows retry after a failed preview request', async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValueOnce(response(async () => new Blob(['data'], { type: item.mime })));
  vi.stubGlobal('fetch', fetcher);
  render(<BinaryCard item={item} refresh={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Load attachment' }));
  expect((await screen.findByRole('alert')).textContent).toContain('offline');
  fireEvent.click(screen.getByRole('button', { name: 'Load attachment' }));
  expect(await screen.findByRole('link', { name: 'Download attachment' })).toBeTruthy();
  expect(fetcher).toHaveBeenCalledTimes(2);
});
