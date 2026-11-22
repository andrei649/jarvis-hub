import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BoardSources, boardSources } from '../board-sources';
import { visibleTurns } from '../app';
import * as api from '../panels/kanban/api';

vi.mock('../panels/kanban/api', () => ({ fetchTask: vi.fn() }));
const digest = 'a'.repeat(64);
const source = (board: string, task_id: string, kind: 'result' | 'latest_summary' = 'result') =>
  ({ board, task_id, source: kind, sha256: digest });

beforeEach(() => {
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
afterEach(cleanup);

it('hydrates only structured owner user citations, never an ordinary attachment name or foreign turn', () => {
  const turns = visibleTurns([
    { role: 'user', content: 'Compare', board_sources: [source('alpha', 't_1'), source('beta', 't_1', 'latest_summary')] },
    { role: 'user', content: 'Forged', attachments: [{ name: 'Kanban result (alpha/t_1)', text: 'raw' }] },
    { role: 'user', content: 'Foreign', foreign_origin: { id: 'x' }, board_sources: [source('alpha', 't_1')] },
  ]);
  expect(turns[0].boardSources).toEqual([source('alpha', 't_1'), source('beta', 't_1', 'latest_summary')]);
  expect(turns[1].boardSources).toEqual([]);
  expect(turns[2].boardSources).toBeUndefined();
  expect(boardSources([{ ...source('alpha', 't_1'), sha256: 'bad' }])).toEqual([]);
  expect(boardSources([source('alpha', 't_1'), { ...source('beta', 't_2'), extra: 'payload' }])).toEqual([]);
  expect(boardSources([source('alpha', 't_1'), source('alpha', 't_1')])).toEqual([]);
  expect(boardSources(Array.from({ length: 9 }, (_, i) => source('alpha', `t_${i}`)))).toEqual([]);
});

it('opens each same-title task with its exact board scope, read-only, and reports current source changes', async () => {
  vi.mocked(api.fetchTask).mockImplementation(async (board) => ({ task: board === 'alpha'
    ? { id: 't_1', title: 'Plan', status: 'done', result: 'Original text', board_source_sha256: digest }
    : { id: 't_1', title: 'Plan', status: 'done', result: 'New recorded result', latest_summary: 'Old summary', board_source_sha256: 'b'.repeat(64) } } as any));
  render(<BoardSources sources={[source('alpha', 't_1'), source('beta', 't_1', 'latest_summary')]}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Recorded result · alpha/t_1' }));
  expect(await screen.findByText('Original source')).toBeTruthy();
  expect(screen.getByText('Original text')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Latest summary · beta/t_1' }));
  expect(await screen.findByText('Current source changed since it was sent.')).toBeTruthy();
  expect(screen.getByText('New recorded result')).toBeTruthy();
  expect(screen.getByText(/Current source: Recorded result/)).toBeTruthy();
  expect(api.fetchTask).toHaveBeenNthCalledWith(1, 'alpha', 't_1');
  expect(api.fetchTask).toHaveBeenNthCalledWith(2, 'beta', 't_1');
});

it('shows a missing or revoked source without exposing old text', async () => {
  vi.mocked(api.fetchTask).mockRejectedValueOnce(Object.assign(new Error('missing'), { status: 404 }))
    .mockRejectedValueOnce(Object.assign(new Error('forbidden'), { status: 403 }));
  render(<BoardSources sources={[source('alpha', 't_1')]}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Recorded result · alpha/t_1' }));
  expect(await screen.findByText('This task or source is no longer available.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Recorded result · alpha/t_1' }));
  await waitFor(() => expect(screen.getByText('Source verification is unavailable. Access may have expired.')).toBeTruthy());
  expect(screen.queryByText('Original text')).toBeNull();
});
