import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { MemoryMode } from '../modes';
import { V2 } from '../data';
import { memorySearch } from '../api/actions';

vi.mock('../api/actions', async importOriginal => ({
  ...await importOriginal<any>(), memorySearch: vi.fn().mockResolvedValue({ results: [] }),
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(memorySearch).mockResolvedValue({ results: [] });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ entities: [], total: 0 }), { headers: { 'Content-Type': 'application/json' } })));
});
describe('Memory mode data boundary', () => {
  it('never shows sample graph nodes or made-up historical dates in live mode', () => {
    render(<MemoryMode t={V2.I18N.en} demo={false} />);
    expect(screen.queryAllByText('Digitaholic')).toHaveLength(0);
    expect(screen.queryByText('2026-05-31')).toBeNull();
    expect(screen.queryByRole('slider')).toBeNull();
    expect(screen.queryByText('qdrant · 768d')).toBeNull();
  });
  it('keeps sample graph/time travel only in explicit demo and sends no memory requests', () => {
    render(<MemoryMode t={V2.I18N.en} demo />);
    expect(screen.getAllByText('Digitaholic').length).toBeGreaterThan(0);
    expect(screen.getByRole('slider')).toBeTruthy();
    expect(memorySearch).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });
  it('shows recall failure without sample recall or freshness claims', async () => {
    vi.mocked(memorySearch).mockRejectedValue(new Error('PRIVATE'));
    render(<MemoryMode t={V2.I18N.en} />);
    await screen.findByText('Memory recall unavailable.');
    expect(screen.queryAllByText(/fresh$/)).toHaveLength(0);
    expect(screen.queryAllByText('Digitaholic')).toHaveLength(0);
    expect(screen.queryByText('PRIVATE')).toBeNull();
  });
  it.each([{ results: [], error: 'PRIVATE' }, {}, { results: 'malformed' }])('shows recall unavailable for a refused or malformed successful response', async response => {
    vi.mocked(memorySearch).mockResolvedValue(response as any); // Deliberately malformed wire payload.
    render(<MemoryMode t={V2.I18N.en} />);
    await screen.findByText('Memory recall unavailable.');
    expect(screen.queryByText('No matching memories.')).toBeNull();
    expect(screen.queryByText('PRIVATE')).toBeNull();
  });
  it('ignores a late live recall after switching to explicit demo', async () => {
    let resolve: (value: any) => void;
    vi.mocked(memorySearch).mockImplementation(() => new Promise(r => { resolve = r; }));
    const { rerender } = render(<MemoryMode t={V2.I18N.en} />);
    rerender(<MemoryMode t={V2.I18N.en} demo />);
    await act(async () => resolve({ results: [{ payload: { text: 'late live content' } }] }));
    expect(screen.queryByText('late live content')).toBeNull();
    expect(screen.getByText('DEMO · sample memory')).toBeTruthy();
    expect(screen.getByRole('slider')).toBeTruthy();
  });
});
