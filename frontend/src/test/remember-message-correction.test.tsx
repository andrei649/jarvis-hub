import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { apiGet, apiPatch } from '../api/client';
import { RememberMessageDialog } from '../remember-message';

vi.mock('../api/client', () => ({ apiGet: vi.fn(), apiPatch: vi.fn(), apiPost: vi.fn() }));

const old = { entry_id: 'memory:user:0123456789abcdef', store: 'user', value: 'I live in Cluj.' };
const later = { entry_id: 'memory:user:fedcba9876543210', store: 'user', value: 'I live in Iași.' };
const readOptions = { admin: false, cache: 'no-store', redirect: 'error' };

beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});

function open() {
  const opener = document.createElement('button');
  document.body.append(opener);
  const view = render(<RememberMessageDialog text="I live in Bucharest now." opener={opener} onClose={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Replace a saved fact' }));
  return { ...view, opener };
}

describe('Remember message correction', () => {
  it('reads only the selected curated ring after the explicit action and patches the selected ID', async () => {
    vi.mocked(apiGet).mockResolvedValue({ entries: [old, later] });
    vi.mocked(apiPatch).mockResolvedValue({ ok: true, changed: true, previous_id: old.entry_id,
      entry: { entry_id: 'memory:user:aaaaaaaaaaaaaaaa', store: 'user', value: 'I live in Bucharest now.' } });
    const view = open();
    expect(apiGet).toHaveBeenCalledExactlyOnceWith('/api/memory/core/facts?store=memory', readOptions);
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact store' }), { target: { value: 'user' } });
    await screen.findByRole('option', { name: old.value });
    expect(apiGet).toHaveBeenLastCalledWith('/api/memory/core/facts?store=user', readOptions);
    expect(apiGet).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(true);
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact to replace' }), { target: { value: old.entry_id } });
    expect(screen.getByText(old.value, { selector: 'output' })).toBeTruthy();
    expect((screen.getByRole('textbox', { name: 'Replacement fact' }) as HTMLTextAreaElement).value).toBe('I live in Bucharest now.');
    fireEvent.click(screen.getByRole('button', { name: 'Save replacement' }));
    await screen.findByText(/Replaced saved fact/);
    expect(apiPatch).toHaveBeenCalledExactlyOnceWith('/api/dashboard/today/entries/memory%3Auser%3A0123456789abcdef',
      { value: 'I live in Bucharest now.' }, { admin: false });
    view.unmount(); view.opener.remove();
  });

  it('does not write from an invalid list, a duplicate draft, or a stale ID', async () => {
    vi.mocked(apiGet).mockImplementation(async path => path.endsWith('store=memory') ?
      { entries: [{ ...old, store: 'memory' }] } : { entries: [old] });
    const view = open();
    await screen.findByText(/Saved facts could not be verified/);
    expect(apiPatch).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact store' }), { target: { value: 'user' } });
    await screen.findByRole('option', { name: old.value });
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact to replace' }), { target: { value: old.entry_id } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Replacement fact' }), { target: { value: old.value } });
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(true);
    fireEvent.change(screen.getByRole('textbox', { name: 'Replacement fact' }), { target: { value: 'I live in Bucharest now.' } });
    vi.mocked(apiPatch).mockRejectedValueOnce(Object.assign(new Error('stale'), { status: 404 }));
    fireEvent.click(screen.getByRole('button', { name: 'Save replacement' }));
    await screen.findByText(/Reload saved facts and select the original again/);
    expect((screen.getByRole('textbox', { name: 'Replacement fact' }) as HTMLTextAreaElement).value).toBe('I live in Bucharest now.');
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(true);
    vi.mocked(apiGet).mockResolvedValueOnce({ entries: [later] });
    fireEvent.click(screen.getByRole('button', { name: 'Reload saved facts' }));
    await screen.findByRole('option', { name: later.value });
    expect(screen.queryByRole('option', { name: old.value })).toBeNull();
    expect(apiPatch).toHaveBeenCalledTimes(1);
    view.unmount(); view.opener.remove();
  });

  it('ignores late responses from a previously selected ring', async () => {
    let finish!: (value: unknown) => void;
    vi.mocked(apiGet).mockImplementation(async path => path.endsWith('store=memory')
      ? new Promise(resolve => { finish = resolve; }) : { entries: [old] });
    const view = open();
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact store' }), { target: { value: 'user' } });
    await screen.findByRole('option', { name: old.value });
    finish({ entries: [{ entry_id: 'memory:memory:0123456789abcdef', store: 'memory', value: 'Old note' }] });
    await waitFor(() => expect(screen.queryByRole('option', { name: 'Old note' })).toBeNull());
    expect(screen.getByRole('option', { name: old.value })).toBeTruthy();
    view.unmount(); view.opener.remove();
  });

  it('keeps the edited draft and chosen store when switching from Save to Replace', async () => {
    vi.mocked(apiGet).mockResolvedValue({ entries: [old] });
    const opener = document.createElement('button'); document.body.append(opener);
    const view = render(<RememberMessageDialog text="Old draft" opener={opener} onClose={() => {}} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Fact to save' }), { target: { value: 'Edited draft' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Save in' }), { target: { value: 'user' } });
    fireEvent.click(screen.getByRole('button', { name: 'Replace a saved fact' }));
    expect(apiGet).toHaveBeenCalledExactlyOnceWith('/api/memory/core/facts?store=user', readOptions);
    expect((screen.getByRole('textbox', { name: 'Replacement fact' }) as HTMLTextAreaElement).value).toBe('Edited draft');
    await screen.findByRole('option', { name: old.value });
    fireEvent.click(screen.getByRole('button', { name: 'Save a new fact' }));
    expect((screen.getByRole('textbox', { name: 'Fact to save' }) as HTMLTextAreaElement).value).toBe('Edited draft');
    expect((screen.getByRole('combobox', { name: 'Save in' }) as HTMLSelectElement).value).toBe('user');
    view.unmount(); opener.remove();
  });

  it('accepts hub-normalized whitespace and permits a second correction after success', async () => {
    vi.mocked(apiGet).mockResolvedValue({ entries: [old] });
    vi.mocked(apiPatch).mockResolvedValueOnce({ ok: true, changed: true, previous_id: old.entry_id,
      entry: { entry_id: later.entry_id, store: 'user', value: 'I live in Bucharest now.' } });
    const view = open();
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact store' }), { target: { value: 'user' } });
    await screen.findByRole('option', { name: old.value });
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact to replace' }), { target: { value: old.entry_id } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Replacement fact' }), { target: { value: 'I live in\n  Bucharest now.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save replacement' }));
    await screen.findByText(/Replaced saved fact/);
    expect(apiPatch).toHaveBeenCalledExactlyOnceWith(`/api/dashboard/today/entries/${encodeURIComponent(old.entry_id)}`,
      { value: 'I live in\n  Bucharest now.' }, { admin: false });
    fireEvent.change(screen.getByRole('textbox', { name: 'Replacement fact' }), { target: { value: 'I live elsewhere.' } });
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(false);
    view.unmount(); view.opener.remove();
  });

  it('rejects mismatched PATCH receipts and permits retry after a transient refusal', async () => {
    vi.mocked(apiGet).mockResolvedValue({ entries: [old] });
    vi.mocked(apiPatch).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ ok: true, changed: true,
      previous_id: 'memory:user:aaaaaaaaaaaaaaaa', entry: later });
    const view = open();
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact store' }), { target: { value: 'user' } });
    await screen.findByRole('option', { name: old.value });
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact to replace' }), { target: { value: old.entry_id } });
    fireEvent.click(screen.getByRole('button', { name: 'Save replacement' }));
    await screen.findByText(/Replacement refused/);
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Save replacement' }));
    await screen.findByText(/Replacement could not be verified/);
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(true);
    view.unmount(); view.opener.remove();
  });

  it('shows a legacy long original in full while limiting only its replacement', async () => {
    const legacy = { ...old, value: 'old fact '.repeat(230) };
    vi.mocked(apiGet).mockImplementation(async path => path.endsWith('store=user') ? { entries: [legacy] } : { entries: [] });
    const view = open();
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact store' }), { target: { value: 'user' } });
    await screen.findByRole('option', { name: legacy.value.trim() });
    fireEvent.change(screen.getByRole('combobox', { name: 'Saved fact to replace' }), { target: { value: legacy.entry_id } });
    expect(screen.getByText('Original saved fact').parentElement?.querySelector('output')?.textContent).toBe(legacy.value);
    expect(screen.getByRole('button', { name: 'Save replacement' }).hasAttribute('disabled')).toBe(false);
    view.unmount(); view.opener.remove();
  });
});
