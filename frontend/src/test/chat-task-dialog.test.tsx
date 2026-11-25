import React from 'react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ChatTaskDialog } from '../chat-task-dialog';
import * as api from '../panels/kanban/api';

vi.mock('../panels/kanban/api', () => ({ fetchBoards: vi.fn(), createTask: vi.fn() }));
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const boards = { current: 'main', boards: [{ slug: 'main', name: 'Main' }, { slug: 'other', name: 'Other' }] };
const text = '  First line  \nSecond line\n';

it('prefills the complete message, requires a listed board, and creates triage only on submit', async () => {
  const longText = text + 'x'.repeat(20_000);
  vi.mocked(api.fetchBoards).mockResolvedValue(boards);
  vi.mocked(api.createTask).mockResolvedValue({ task: { id: 'task-7', title: 'Edited', status: 'triage' } });
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();
  const onClose = vi.fn();
  render(<ChatTaskDialog text={longText} opener={opener} onClose={onClose} lang="en" />);
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'Board' }) as HTMLSelectElement).value).toBe('main'));
  expect((screen.getByRole('dialog') as HTMLDialogElement).style.width).toContain('100vw');
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).value).toBe('First line');
  expect((screen.getByRole('textbox', { name: 'Description' }) as HTMLTextAreaElement).value).toBe(longText);
  expect(api.createTask).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Board' }), { target: { value: 'other' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'Edited' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create task' }));
  await waitFor(() => expect(api.createTask).toHaveBeenCalledWith('other', expect.objectContaining({ title: 'Edited', body: longText, triage: true,
    idempotency_key: expect.stringMatching(/^[0-9a-f]{32}$/) })));
  expect(screen.getByRole('status').textContent).toContain('Other: Edited (task-7)');
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(onClose).toHaveBeenCalledOnce();
  cleanup();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});

it('shows load and save failures, retries, and blocks duplicate submissions', async () => {
  vi.mocked(api.fetchBoards).mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ current: 'missing', boards: [{ slug: 'main', name: 'Main' }] });
  let finish!: (value: { task: { id: string; title: string; status: string } }) => void;
  vi.mocked(api.createTask).mockRejectedValueOnce(new Error('denied')).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const opener = document.createElement('button');
  document.body.append(opener);
  const onClose = vi.fn();
  render(<ChatTaskDialog text={text} opener={opener} onClose={onClose} lang="ro" />);
  await screen.findByText(/offline/);
  expect(screen.getByRole('button', { name: 'Creează sarcina' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Reîncearcă' }));
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'Tablou' }) as HTMLSelectElement).value).toBe('main'));
  fireEvent.click(screen.getByRole('button', { name: 'Creează sarcina' }));
  await screen.findByText(/denied/);
  expect(screen.getByRole('alert').textContent).toContain('Crearea sarcinii nu a putut fi confirmată.');
  expect(screen.getByRole('textbox', { name: 'Titlu' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Reîncearcă' }));
  expect(screen.getByRole('button', { name: 'Se creează…' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: 'Anulează' }).hasAttribute('disabled')).toBe(true);
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.submit(screen.getByRole('textbox', { name: 'Titlu' }).closest('form')!);
  expect(api.createTask).toHaveBeenCalledTimes(2);
  expect(vi.mocked(api.createTask).mock.calls[1][1]).toEqual(vi.mocked(api.createTask).mock.calls[0][1]);
  finish({ task: { id: 'task-8', title: 'Server title', status: 'triage' } });
  await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Main: Server title (task-8)'));
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }));
  expect(onClose).toHaveBeenCalledOnce();
  cleanup();
  opener.remove();
});

it('cannot submit without a listed board and restores focus on Escape', async () => {
  vi.mocked(api.fetchBoards).mockResolvedValue({ current: 'ghost', boards: [] });
  const opener = document.createElement('button');
  document.body.append(opener);
  opener.focus();
  const onClose = vi.fn();
  render(<ChatTaskDialog text={text} opener={opener} onClose={onClose} lang="en" />);
  await screen.findByText('No boards available.');
  expect(screen.getByRole('button', { name: 'Create task' }).hasAttribute('disabled')).toBe(true);
  fireEvent.submit(screen.getByRole('textbox', { name: 'Title' }).closest('form')!);
  expect(api.createTask).not.toHaveBeenCalled();
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(onClose).toHaveBeenCalledOnce();
  cleanup();
  expect(document.activeElement).toBe(opener);
  opener.remove();
});
