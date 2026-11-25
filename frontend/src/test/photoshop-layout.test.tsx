import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest';
import { PhotoshopLayoutButton } from '../photoshop-layout';
import { encodePhotoshopLayout, renderPhotoshopLayout, PhotoshopLayoutError } from '../photoshop-document';

const sessionListeners = vi.hoisted(() => new Set<() => void>());
vi.mock('../api/owner-session', () => ({
  ownerSession: () => null,
  onOwnerSession: (listener: () => void) => { sessionListeners.add(listener); return () => sessionListeners.delete(listener); },
}));
vi.mock(import('../photoshop-document'), async importOriginal => ({
  ...await importOriginal(),
  renderPhotoshopLayout: vi.fn(() => document.createElement('canvas')),
  encodePhotoshopLayout: vi.fn(async () => new Blob(['PSD'], { type: 'image/vnd.adobe.photoshop' })),
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
beforeEach(() => {
  vi.mocked(renderPhotoshopLayout).mockReset().mockImplementation(() => document.createElement('canvas'));
  vi.mocked(encodePhotoshopLayout).mockReset().mockImplementation(async () => new Blob(['PSD'], { type: 'image/vnd.adobe.photoshop' }));
  vi.stubGlobal('URL', Object.assign(class extends URL {}, {
    createObjectURL: vi.fn(() => 'blob:layout'), revokeObjectURL: vi.fn(),
  }));
  vi.stubGlobal('Image', class {
    src = ''; naturalWidth = 900; naturalHeight = 600; complete = true;
    decode() { return Promise.resolve(); }
  });
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.clearAllTimers(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); localStorage.clear(); sessionListeners.clear(); });

function png(width = 900, height = 600): File {
  const bytes = new Uint8Array(24);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10], 0);
  bytes.set([0, 0, 0, 13, 73, 72, 68, 82], 8);
  const view = new DataView(bytes.buffer);
  view.setUint32(16, width); view.setUint32(20, height);
  const file = new File([bytes], 'selected.png', { type: 'image/png' });
  Object.defineProperty(file, 'arrayBuffer', { value: () => Promise.resolve(bytes.buffer) });
  return file;
}

function jpeg(): File {
  const bytes = new Uint8Array(21);
  bytes.set([0xff, 0xd8, 0xff, 0xc0, 0, 17, 8, 2, 88, 3, 132], 0); // 900 × 600 SOF
  const file = new File([bytes], 'photo.jpg', { type: 'image/jpeg' });
  Object.defineProperty(file, 'arrayBuffer', { value: () => Promise.resolve(bytes.buffer) });
  return file;
}

it('opens locally with the full reply, previews it, and downloads only on the explicit click', async () => {
  const { unmount } = render(<PhotoshopLayoutButton text={'First line\nSecond line'} lang="en" />);
  const opener = screen.getByRole('button', { name: 'Photoshop' });
  opener.focus();
  fireEvent.click(opener);
  expect(screen.getByRole('dialog', { name: 'Photoshop layout' })).toBeTruthy();
  expect((screen.getByRole('textbox', { name: 'Reply text' }) as HTMLTextAreaElement).value).toBe('First line\nSecond line');
  expect((screen.getByRole('textbox', { name: 'Artwork title' }) as HTMLInputElement).value).toBe('Chat reply');
  expect(encodePhotoshopLayout).not.toHaveBeenCalled();
  expect(renderPhotoshopLayout).toHaveBeenCalledWith({ title: 'Chat reply', body: 'First line\nSecond line' });
  fireEvent.change(screen.getByRole('textbox', { name: 'Artwork title' }), { target: { value: 'Spring poster' } });
  fireEvent.click(screen.getByRole('button', { name: 'Download PSD' }));
  await waitFor(() => expect(encodePhotoshopLayout).toHaveBeenCalledOnce());
  expect(encodePhotoshopLayout).toHaveBeenCalledWith({ title: 'Spring poster', body: 'First line\nSecond line' });
  expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce();
  const download = (HTMLAnchorElement.prototype.click as ReturnType<typeof vi.fn>).mock.instances[0] as HTMLAnchorElement;
  expect(download.download).toBe('nerva-Spring-poster.psd');
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(opener);
  unmount();
});

it('blocks download for invalid image bytes or oversized dimensions until explicit removal', async () => {
  render(<PhotoshopLayoutButton text="Reply" lang="ro" />);
  fireEvent.click(screen.getByRole('button', { name: 'Photoshop' }));
  const picker = screen.getByLabelText('Imagine locală opțională') as HTMLInputElement;
  const fake = new File(['not png'], 'fake.png', { type: 'image/png' });
  Object.defineProperty(fake, 'arrayBuffer', { value: () => Promise.resolve(new TextEncoder().encode('not png').buffer) });
  fireEvent.change(picker, { target: { files: [fake] } });
  await screen.findByText('Alege o imagine PNG sau JPEG validă.');
  expect((screen.getByRole('button', { name: 'Descarcă PSD' }) as HTMLButtonElement).disabled).toBe(true);
  expect(encodePhotoshopLayout).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Elimină imaginea' }));
  expect((screen.getByRole('button', { name: 'Descarcă PSD' }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.change(picker, { target: { files: [png(5000, 500)] } });
  await screen.findByText(/Dimensiunile depășesc/);
  expect((screen.getByRole('button', { name: 'Descarcă PSD' }) as HTMLButtonElement).disabled).toBe(true);
});

it('accepts a bounded JPEG as a separate image layer and removes its object URL on close', async () => {
  render(<PhotoshopLayoutButton text="Caption" lang="en" />);
  fireEvent.click(screen.getByRole('button', { name: 'Photoshop' }));
  fireEvent.change(screen.getByLabelText('Optional local image'), { target: { files: [jpeg()] } });
  await waitFor(() => expect(renderPhotoshopLayout).toHaveBeenLastCalledWith(expect.objectContaining({ image: expect.anything() })));
  expect(screen.getByText('photo.jpg')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:layout');
});

it('keeps pending image selection from downloading text-only and ignores a stale decode after replacement', async () => {
  let finish!: () => void;
  let calls = 0;
  vi.stubGlobal('Image', class {
    src = ''; naturalWidth = 900; naturalHeight = 600; complete = true;
    decode() { return ++calls === 1 ? new Promise<void>(resolve => { finish = resolve; }) : Promise.resolve(); }
  });
  render(<PhotoshopLayoutButton text="Reply" lang="en" />);
  fireEvent.click(screen.getByRole('button', { name: 'Photoshop' }));
  const picker = screen.getByLabelText('Optional local image');
  fireEvent.change(picker, { target: { files: [png()] } });
  fireEvent.click(screen.getByRole('button', { name: 'Download PSD' }));
  expect(encodePhotoshopLayout).not.toHaveBeenCalled();
  await waitFor(() => expect(calls).toBe(1));
  expect((screen.getByRole('button', { name: 'Download PSD' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(picker, { target: { files: [png()] } });
  await waitFor(() => expect(renderPhotoshopLayout).toHaveBeenLastCalledWith(expect.objectContaining({ image: expect.anything() })));
  await act(async () => finish());
  expect(renderPhotoshopLayout).toHaveBeenLastCalledWith(expect.objectContaining({ image: expect.anything() }));
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:layout');
  expect((screen.getByRole('button', { name: 'Download PSD' }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Remove image' }));
  expect(renderPhotoshopLayout).toHaveBeenLastCalledWith({ title: 'Chat reply', body: 'Reply' });
});

it('keeps oversized reply text visible for editing and permits a title-only document', async () => {
  vi.mocked(renderPhotoshopLayout).mockImplementation(input => {
    if (input.body) throw new PhotoshopLayoutError('Body does not fit in the Photoshop layout. Shorten it before exporting.', 'Scurtează textul răspunsului ca să încapă în machetă.');
    return document.createElement('canvas');
  });
  render(<PhotoshopLayoutButton text="Long reply" lang="ro" />);
  fireEvent.click(screen.getByRole('button', { name: 'Photoshop' }));
  expect((screen.getByRole('textbox', { name: 'Textul răspunsului' }) as HTMLTextAreaElement).value).toBe('Long reply');
  expect(screen.getByRole('alert').textContent).toContain('Scurtează textul răspunsului');
  expect((screen.getByRole('button', { name: 'Descarcă PSD' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByRole('textbox', { name: 'Textul răspunsului' }), { target: { value: '' } });
  expect(screen.queryByRole('alert')).toBeNull();
  expect((screen.getByRole('button', { name: 'Descarcă PSD' }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Descarcă PSD' }));
  await waitFor(() => expect(encodePhotoshopLayout).toHaveBeenCalledWith({ title: 'Răspuns din chat', body: '' }));
});

it('drops an in-flight PSD when credentials rotate, restoring focus without a download', async () => {
  let finish!: (blob: Blob) => void;
  vi.mocked(encodePhotoshopLayout).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const { unmount } = render(<PhotoshopLayoutButton text="Reply" lang="en" />);
  const opener = screen.getByRole('button', { name: 'Photoshop' });
  fireEvent.click(opener);
  fireEvent.click(screen.getByRole('button', { name: 'Download PSD' }));
  expect(encodePhotoshopLayout).toHaveBeenCalledOnce();
  localStorage.setItem('hud.admin_token', 'rotated');
  await act(async () => { sessionListeners.forEach(listener => listener()); });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(opener);
  await act(async () => finish(new Blob(['PSD'])));
  expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled();
  unmount();
});
