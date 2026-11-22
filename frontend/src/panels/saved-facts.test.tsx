import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { apiDelete, apiGet, apiPatch, apiPost } from '../api/client';
import { SavedFacts } from './saved-facts';

vi.mock('../api/client', () => ({ apiDelete: vi.fn(), apiGet: vi.fn(), apiPatch: vi.fn(), apiPost: vi.fn() }));

const entry = { entry_id: 'user:abc', store: 'user', value: 'Prefers tea' };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(apiGet).mockImplementation(async path => path === '/api/memory'
    ? { available: true, enabled: true, injected: true }
    : { entries: path.endsWith('store=user') ? [entry] : [] });
});

describe('SavedFacts', () => {
  it('reads only the two curated stores and explicitly saves an agent note', async () => {
    vi.mocked(apiPost).mockResolvedValue({ ok: true, changed: true, entry: { entry_id: 'memory:new', store: 'memory', value: 'Use short answers' } });
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    expect(vi.mocked(apiGet).mock.calls.map(c => c[0])).toEqual([
      '/api/memory', '/api/dashboard/today/entries?store=memory', '/api/dashboard/today/entries?store=user',
    ]);
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'Use short answers' } });
    expect(apiPost).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/dashboard/today/entries',
      { store: 'memory', value: 'Use short answers' }, { admin: true }));
    await screen.findByText(/Saved fact in Agent notes/);
    expect((screen.getByLabelText('Fact to save') as HTMLTextAreaElement).value).toBe('');
  });

  it('corrects the selected canonical fact and names its store as the source', async () => {
    vi.mocked(apiPatch).mockResolvedValue({ ok: true, changed: true, entry: { ...entry, value: 'Prefers coffee' } });
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    expect(screen.getByText('Source: saved fact · User profile')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Correct fact: Prefers tea' }));
    fireEvent.change(screen.getByLabelText('Corrected fact'), { target: { value: 'Prefers coffee' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    await waitFor(() => expect(apiPatch).toHaveBeenCalledWith('/api/dashboard/today/entries/user%3Aabc',
      { value: 'Prefers coffee' }, { admin: true }));
    await screen.findByText(/Corrected fact in User profile/);
  });

  it('keeps draft text on authorization refusal and stale correction, without claiming success', async () => {
    vi.mocked(apiPost).mockRejectedValueOnce(Object.assign(new Error('denied'), { status: 403, body: { reason: 'denied' } }));
    vi.mocked(apiPatch).mockRejectedValueOnce(Object.assign(new Error('stale'), { status: 409 }));
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'Keep me' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await screen.findByText(/Save refused \(403\)/);
    expect((screen.getByLabelText('Fact to save') as HTMLTextAreaElement).value).toBe('Keep me');
    fireEvent.click(screen.getByRole('button', { name: 'Correct fact: Prefers tea' }));
    fireEvent.change(screen.getByLabelText('Corrected fact'), { target: { value: 'New value' } });
    vi.mocked(apiGet).mockImplementation(async path => path === '/api/memory'
      ? { available: true, enabled: true, injected: true } : { entries: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));
    await screen.findByText(/Correction refused \(409\)/);
    await screen.findByText(/This fact is no longer in the saved list/);
    expect((screen.getByLabelText('Corrected fact') as HTMLInputElement).value).toBe('New value');
    expect(screen.queryByRole('button', { name: 'Save correction' })).toBeNull();
  });

  it('can choose the user profile and keeps controls usable in a narrow container', async () => {
    vi.mocked(apiPost).mockResolvedValue({ ok: true, changed: true, entry });
    const { container } = render(<div style={{ width: 320 }}><SavedFacts /></div>);
    await screen.findByText('Prefers tea');
    fireEvent.change(screen.getByLabelText('Save in'), { target: { value: 'user' } });
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'Prefers tea' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/dashboard/today/entries',
      { store: 'user', value: 'Prefers tea' }, { admin: true }));
    expect(container.querySelector('section')?.getAttribute('aria-label')).toBe('Saved facts');
    fireEvent.click(screen.getByRole('button', { name: 'Correct fact: Prefers tea' }));
    expect(screen.getByLabelText('Corrected fact')).toBeTruthy();
  });

  it('states that switching off automatic injection does not erase saved facts', async () => {
    vi.mocked(apiGet).mockImplementation(async path => path === '/api/memory'
      ? { available: true, enabled: false, injected: false }
      : { entries: path.endsWith('store=user') ? [entry] : [] });
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    expect(screen.getByText(/Automatic memory is off; new saves are unavailable. Existing facts remain stored/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'A new fact' } });
    expect((screen.getByRole('button', { name: 'Save fact' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Correct fact: Prefers tea' }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: 'Forget fact: Prefers tea' }) as HTMLButtonElement).disabled).toBe(false);
    expect(apiPost).not.toHaveBeenCalled();
  });

  it('uses the HUD field colors and focus treatment for narrow layouts', async () => {
    render(<div style={{ width: 390 }}><SavedFacts /></div>);
    await screen.findByText('Prefers tea');
    const select = screen.getByLabelText('Save in') as HTMLSelectElement;
    const draft = screen.getByLabelText('Fact to save') as HTMLTextAreaElement;
    expect(select.style.background).toBe('var(--surface)');
    expect(draft.style.background).toBe('var(--surface)');
    expect(select.tabIndex).toBe(0);
    expect(draft.tabIndex).toBe(0);
  });

  it('holds the selected store and draft while a save is in flight', async () => {
    let finish!: (result: any) => void;
    vi.mocked(apiPost).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'Selected fact' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    expect((screen.getByLabelText('Fact to save') as HTMLTextAreaElement).disabled).toBe(true);
    expect((screen.getByLabelText('Save in') as HTMLSelectElement).disabled).toBe(true);
    finish({ ok: true, changed: true, entry: { entry_id: 'memory:new', store: 'memory', value: 'Selected fact' } });
    await screen.findByText(/Saved fact in Agent notes/);
  });

  it('refreshes a duplicate without erasing the draft', async () => {
    vi.mocked(apiPost).mockResolvedValue({ ok: true, changed: false, entry });
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: 'Prefers tea' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await screen.findByText(/Fact already saved/);
    await waitFor(() => expect(vi.mocked(apiGet).mock.calls).toHaveLength(6));
    expect((screen.getByLabelText('Fact to save') as HTMLTextAreaElement).value).toBe('Prefers tea');
  });

  it('forgets only after reversible confirmation, then offers and performs the returned undo', async () => {
    let saved = true;
    vi.mocked(apiGet).mockImplementation(async path => path === '/api/memory'
      ? { available: true, enabled: true, injected: true }
      : { entries: path.endsWith('store=user') && saved ? [entry] : [] });
    vi.mocked(apiDelete).mockImplementation(async () => { saved = false; return { ok: true, deleted: entry.entry_id, undo_ref: 'undo-1' }; });
    vi.mocked(apiPost).mockImplementation(async () => { saved = true; return { ok: true, ref: 'undo-1' }; });
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.click(screen.getByRole('button', { name: 'Forget fact: Prefers tea' }));
    expect(apiDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm forget' }));
    await waitFor(() => expect(apiDelete).toHaveBeenCalledWith('/api/dashboard/today/entries/user%3Aabc', { admin: true }));
    await screen.findByRole('button', { name: 'Undo forgotten fact' });
    await waitFor(() => expect(screen.queryByText('Prefers tea')).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Undo forgotten fact' }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/memory/core/undo', { ref: 'undo-1' }, { admin: true }));
    await screen.findByText('Prefers tea');
  });

  it('keeps a refused delete honest and refreshes after a stale id', async () => {
    vi.mocked(apiDelete).mockRejectedValueOnce(Object.assign(new Error('denied'), { status: 403, body: { reason: 'kernel_denied' } }))
      .mockRejectedValueOnce(Object.assign(new Error('gone'), { status: 404, body: { reason: 'memory_no_match' } }));
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.click(screen.getByRole('button', { name: 'Forget fact: Prefers tea' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm forget' }));
    await screen.findByText(/Forget refused \(403\).*kernel_denied/);
    expect(screen.getByText('Prefers tea')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Undo forgotten fact' })).toBeNull();
    vi.mocked(apiGet).mockImplementation(async path => path === '/api/memory'
      ? { available: true, enabled: true, injected: true } : { entries: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm forget' }));
    await screen.findByText(/Forget refused \(404\).*memory_no_match/);
    await waitFor(() => expect(screen.queryByText('Prefers tea')).toBeNull());
    expect(screen.queryByRole('button', { name: 'Undo forgotten fact' })).toBeNull();
  });

  it('keeps an undo reference on refusal and blocks repeated clicks while undo is pending', async () => {
    vi.mocked(apiDelete).mockResolvedValue({ ok: true, deleted: entry.entry_id, undo_ref: 'undo-1' });
    let rejectUndo!: (error: unknown) => void;
    vi.mocked(apiPost).mockImplementation(() => new Promise((_resolve, reject) => { rejectUndo = reject; }));
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.click(screen.getByRole('button', { name: 'Forget fact: Prefers tea' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm forget' }));
    const undo = await screen.findByRole('button', { name: 'Undo forgotten fact' });
    fireEvent.click(undo);
    expect((undo as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(undo);
    expect(apiPost).toHaveBeenCalledTimes(1);
    rejectUndo(Object.assign(new Error('stale'), { status: 409, body: { reason: 'memory_changed_meanwhile' } }));
    await screen.findByText(/Undo refused \(409\).*memory_changed_meanwhile/);
    expect(screen.getByRole('button', { name: 'Undo forgotten fact' })).toBeTruthy();
  });

  it('accepts 300 Unicode characters and blocks a 301st for both save and correction', async () => {
    vi.mocked(apiPost).mockResolvedValue({ ok: true, changed: true, entry: { entry_id: 'memory:new', store: 'memory', value: '😀'.repeat(300) } });
    render(<SavedFacts />);
    await screen.findByText('Prefers tea');
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: '😀'.repeat(300) } });
    expect((screen.getByRole('button', { name: 'Save fact' }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText('Fact to save'), { target: { value: '😀'.repeat(301) } });
    expect((screen.getByRole('button', { name: 'Save fact' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/301\/300 characters/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Correct fact: Prefers tea' }));
    fireEvent.change(screen.getByLabelText('Corrected fact'), { target: { value: '😀'.repeat(300) } });
    expect((screen.getByRole('button', { name: 'Save correction' }) as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText('Corrected fact'), { target: { value: '😀'.repeat(301) } });
    expect((screen.getByRole('button', { name: 'Save correction' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
