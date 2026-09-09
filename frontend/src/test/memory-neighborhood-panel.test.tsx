import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryNeighborhood } from '../panels/memory-neighborhood';
import * as api from '../api/memory-map';
vi.mock('../api/memory-map', () => ({ memoryNodes: vi.fn(), memoryNeighborhood: vi.fn() }));
const alpha = { name: 'Alpha', type: 'project' };
const beta = { name: 'Beta', type: 'company' };
const detail = (entity = alpha) => ({ entity, relations: [], clipped: false });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.memoryNodes).mockResolvedValue([alpha, beta]);
  vi.mocked(api.memoryNeighborhood).mockResolvedValue(detail());
});
describe('stored memory neighborhood', () => {
  it('loads real nodes but reads details only after an explicit selection', async () => {
    render(<MemoryNeighborhood />);
    await screen.findByRole('button', { name: 'Alpha' });
    expect(api.memoryNeighborhood).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
    await screen.findByText('No stored relationships for this entity.');
    expect(api.memoryNeighborhood).toHaveBeenCalledWith('Alpha', expect.any(AbortSignal));
    expect(screen.getByRole('button', { name: 'Alpha' }).getAttribute('aria-pressed')).toBe('true');
  });
  it('lets a connected entity become the next center without inventing a link direction', async () => {
    vi.mocked(api.memoryNeighborhood).mockResolvedValueOnce({ entity: alpha,
      relations: [{ source: 'Alpha', relation: 'USES', target: 'Gamma' }], clipped: false }).mockResolvedValueOnce(detail({ name: 'Gamma', type: 'tool' }));
    render(<MemoryNeighborhood />);
    fireEvent.click(await screen.findByRole('button', { name: 'Alpha' }));
    await screen.findByText(/— USES —/);
    fireEvent.click(screen.getByRole('button', { name: 'Explore Gamma' }));
    await screen.findByText('No stored relationships for this entity.');
    expect(api.memoryNeighborhood).toHaveBeenLastCalledWith('Gamma', expect.any(AbortSignal));
    expect(screen.queryByText(/— USES —/)).toBeNull();
  });
  it('distinguishes an empty graph from unavailable data without a sample fallback', async () => {
    vi.mocked(api.memoryNodes).mockResolvedValue([]);
    render(<MemoryNeighborhood />);
    await screen.findByText('No stored entities found.');
    expect(api.memoryNeighborhood).not.toHaveBeenCalled();
    expect(screen.queryByText('Digitaholic')).toBeNull();
  });
  it('renders auth refusal without raw error text or retry', async () => {
    vi.mocked(api.memoryNodes).mockRejectedValue({ code: 'auth', message: 'PRIVATE' });
    render(<MemoryNeighborhood />);
    await screen.findByText(/requires your current user credentials/);
    expect(screen.queryByText('PRIVATE')).toBeNull();
    expect(api.memoryNodes).toHaveBeenCalledOnce();
  });
  it('aborts and ignores a stale selected entity response', async () => {
    let resolve: (value: api.MemoryNeighborhoodData) => void;
    vi.mocked(api.memoryNeighborhood).mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockResolvedValueOnce(detail(beta));
    render(<MemoryNeighborhood />);
    fireEvent.click(await screen.findByRole('button', { name: 'Alpha' }));
    fireEvent.click(screen.getByRole('button', { name: 'Beta' }));
    await screen.findByText('No stored relationships for this entity.');
    await act(async () => resolve({ entity: alpha, relations: [{ source: 'Alpha', relation: 'PRIVATE_OLD', target: 'Gamma' }], clipped: false }));
    expect(screen.queryByText(/PRIVATE_OLD/)).toBeNull();
    expect(vi.mocked(api.memoryNeighborhood).mock.calls[0][1].aborted).toBe(true);
    expect(screen.getByRole('button', { name: 'Beta' }).getAttribute('aria-pressed')).toBe('true');
  });
  it('search clears the old selection and ignores old list responses', async () => {
    let resolve: (value: api.MemoryNode[]) => void;
    vi.mocked(api.memoryNodes).mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockResolvedValueOnce([beta]);
    render(<MemoryNeighborhood />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Find memory entities' }), { target: { value: 'Beta' } });
    fireEvent.click(screen.getByRole('button', { name: 'Find' }));
    await screen.findByRole('button', { name: 'Beta' });
    await act(async () => resolve([alpha]));
    expect(screen.queryByRole('button', { name: 'Alpha' })).toBeNull();
    expect(vi.mocked(api.memoryNodes).mock.calls[0][1].aborted).toBe(true);
    expect(api.memoryNodes).toHaveBeenLastCalledWith('Beta', expect.any(AbortSignal));
  });
  it('cancels an active detail read on unmount', async () => {
    vi.mocked(api.memoryNeighborhood).mockImplementation(() => new Promise(() => {}));
    const { unmount } = render(<MemoryNeighborhood />);
    fireEvent.click(await screen.findByRole('button', { name: 'Alpha' }));
    await waitFor(() => expect(api.memoryNeighborhood).toHaveBeenCalledOnce());
    unmount();
    expect(vi.mocked(api.memoryNeighborhood).mock.calls[0][1].aborted).toBe(true);
  });
  it('keeps the selected details when the selected node is clicked again', async () => {
    render(<MemoryNeighborhood />);
    fireEvent.click(await screen.findByRole('button', { name: 'Alpha' }));
    await screen.findByText('No stored relationships for this entity.');
    fireEvent.click(screen.getByRole('button', { name: 'Alpha' }));
    expect(screen.getByText('No stored relationships for this entity.')).toBeTruthy();
    expect(api.memoryNeighborhood).toHaveBeenCalledOnce();
  });
  it('discloses a clipped relationship page', async () => {
    vi.mocked(api.memoryNeighborhood).mockResolvedValue({ ...detail(), clipped: true });
    render(<MemoryNeighborhood />);
    fireEvent.click(await screen.findByRole('button', { name: 'Alpha' }));
    await screen.findByText('Showing the first 100 relationships. More are stored.');
  });
});
