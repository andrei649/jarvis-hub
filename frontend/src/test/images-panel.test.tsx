import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ImagesPanel } from '../panels/images';
import * as api from '../api/images';
vi.mock('../api/images', () => ({ imageStatus: vi.fn(), proposeImage: vi.fn(), imageTask: vi.fn(), imageBlob: vi.fn() }));
const artifact = { id: 'a'.repeat(32), bytes: 8, width: 512, height: 512 };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.imageStatus).mockResolvedValue({ configured: true });
  vi.mocked(api.proposeImage).mockResolvedValue(17);
  vi.mocked(api.imageTask).mockResolvedValue({ task_id: 17, state: 'awaiting_approval', artifact: null });
  vi.mocked(api.imageBlob).mockResolvedValue(new Blob(['png'], { type: 'image/png' }));
  URL.createObjectURL = vi.fn().mockReturnValue('blob:owned-image');
  URL.revokeObjectURL = vi.fn();
});
async function propose() {
  await waitFor(() => expect(screen.getByText(/configured · connection untested/i)).toBeTruthy());
  fireEvent.change(screen.getByRole('textbox', { name: 'Image prompt' }), { target: { value: 'A rain-soaked tree' } });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Propose image' })); });
}
describe('Images panel', () => {
  it('separates exact prompt proposal from existing inbox approval', async () => {
    render(<ImagesPanel />); await propose();
    await screen.findByText(/Awaiting approval/);
    expect(api.proposeImage).toHaveBeenCalledWith('A rain-soaked tree', expect.any(AbortSignal));
    expect(screen.getByRole('link', { name: 'Open Decision Inbox' }).getAttribute('href')).toBe('#decision-inbox');
    expect(screen.queryByRole('button', { name: /approve/i })).toBeNull();
    expect(screen.getByText('A rain-soaked tree')).toBeTruthy();
    expect(api.imageBlob).not.toHaveBeenCalled();
  });
  it('does not offer generation when configuration is disabled', async () => {
    vi.mocked(api.imageStatus).mockResolvedValue({ configured: false });
    render(<ImagesPanel />);
    await screen.findByText(/Local image generation is disabled/);
    expect((screen.getByRole('button', { name: 'Propose image' }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.proposeImage).not.toHaveBeenCalled();
  });
  it('leaves a lost POST response uncertain with no automatic resubmit', async () => {
    vi.mocked(api.proposeImage).mockRejectedValue({ code: 'uncertain', message: 'PRIVATE' });
    render(<ImagesPanel />); await propose();
    await screen.findByText(/Proposal response lost or unclear/);
    expect(screen.queryByText('PRIVATE')).toBeNull();
    expect(api.proposeImage).toHaveBeenCalledTimes(1);
    expect(api.imageTask).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Propose image' })).toBeNull();
  });
  it('uses a validated artifact blob for preview and download, and revokes on unmount', async () => {
    vi.mocked(api.imageTask).mockResolvedValue({ task_id: 17, state: 'ready', artifact });
    const { unmount } = render(<ImagesPanel />); await propose();
    await screen.findByRole('img', { name: 'Generated image' });
    expect(screen.getByRole('img').getAttribute('src')).toBe('blob:owned-image');
    expect(screen.getByRole('link', { name: 'Download PNG' }).getAttribute('href')).toBe('blob:owned-image');
    expect(api.imageBlob).toHaveBeenCalledWith(artifact, expect.any(AbortSignal));
    unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:owned-image');
  });
  it('stops watching without cancelling or resubmitting the server task', async () => {
    render(<ImagesPanel />); await propose(); await screen.findByText(/Awaiting approval/);
    fireEvent.click(screen.getByRole('button', { name: 'Stop watching' }));
    expect(screen.getByText(/Watching stopped; the server task may continue/)).toBeTruthy();
    expect(api.imageTask).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.imageTask).mock.calls[0][1].aborted).toBe(true);
    expect(api.proposeImage).toHaveBeenCalledTimes(1);
  });
  it('ignores late task responses after choosing a new proposal', async () => {
    let resolve: (value: api.ImageTask) => void;
    vi.mocked(api.imageTask).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    render(<ImagesPanel />); await propose();
    await waitFor(() => expect(api.imageTask).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole('button', { name: 'New proposal' }));
    await act(async () => resolve({ task_id: 17, state: 'ready', artifact }));
    expect(api.imageBlob).not.toHaveBeenCalled();
    expect(screen.queryByRole('img')).toBeNull();
  });
  it('ignores late image bytes and creates no URL after unmount', async () => {
    vi.mocked(api.imageTask).mockResolvedValue({ task_id: 17, state: 'ready', artifact });
    let resolve: (value: Blob) => void;
    vi.mocked(api.imageBlob).mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const { unmount } = render(<ImagesPanel />); await propose();
    await waitFor(() => expect(api.imageBlob).toHaveBeenCalledOnce()); unmount();
    await act(async () => resolve(new Blob(['late'])));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
  it('shows auth failure without raw server text or automatic read retry', async () => {
    vi.mocked(api.imageTask).mockRejectedValue({ code: 'auth', message: 'PRIVATE' });
    render(<ImagesPanel />); await propose();
    await screen.findByText(/Owner authentication required/);
    expect(screen.queryByText('PRIVATE')).toBeNull();
    expect(api.imageTask).toHaveBeenCalledOnce();
    expect(api.proposeImage).toHaveBeenCalledOnce();
  });
  it('can resume an existing task after reopening without making another proposal', async () => {
    render(<ImagesPanel />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Existing image task ID' }), { target: { value: '17' } });
    fireEvent.click(screen.getByRole('button', { name: 'Watch existing task' }));
    await screen.findByText(/Awaiting approval/);
    expect(api.imageTask).toHaveBeenCalledWith(17, expect.any(AbortSignal));
    expect(api.proposeImage).not.toHaveBeenCalled();
  });
  it.each(['0', '9007199254740992'])('does not read invalid existing task ID %s', async value => {
    render(<ImagesPanel />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Existing image task ID' }), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'Watch existing task' }));
    expect(api.imageTask).not.toHaveBeenCalled();
    expect(api.proposeImage).not.toHaveBeenCalled();
  });
});
