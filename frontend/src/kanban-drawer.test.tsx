import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { TaskDrawer } from './panels/kanban/drawer';
import * as api from './panels/kanban/api';
import type { KanbanTaskDetail } from './panels/kanban/types';

vi.mock('./panels/kanban/api', () => ({ fetchTask: vi.fn(), fetchLog: vi.fn(), patchTask: vi.fn(), addComment: vi.fn(), uploadAttachment: vi.fn(), downloadAttachment: vi.fn(), deleteTask: vi.fn() }));
const detail: KanbanTaskDetail = {
  task: { id: 't_1', title: 'Inspect queue', status: 'triage', body: '**Goal:** diagnose', priority: 2, workspace_kind: 'dir', workspace_path: '/repo' },
  comments: [{ id: 2, author: 'owner', body: 'Existing note', created_at: 1 }], events: [{ id: 4, kind: 'status', payload: {status:'triage'}, created_at: 1 }],
  attachments: [{ id: 3, filename: 'proof.txt', size: 4 }], links: { parents: [], children: [] }, runs: [],
};
beforeEach(() => {
  vi.mocked(api.fetchTask).mockResolvedValue(detail);
  vi.mocked(api.fetchLog).mockRejectedValue(new Error('503 log adapter unavailable'));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
const props = { slug: 'alpha', id: 't_1', columns: ['triage','ready','running'], profiles: [], onOpen: vi.fn(), onClose: vi.fn(), onChanged: vi.fn() };

describe('Kanban task drawer', () => {
  it('renders task markdown through the shared safe renderer', async () => {
    render(<TaskDrawer {...props} />);
    expect(await screen.findByText('Goal:')).toBeTruthy();
    expect(screen.queryByText('**Goal:** diagnose')).toBeNull();
  });

  it('posts a body-only comment and refreshes the detail', async () => {
    vi.mocked(api.addComment).mockResolvedValue({ok:true});
    render(<TaskDrawer {...props} />);
    const dialog = await screen.findByRole('dialog', { name: 'Task details' });
    expect(within(dialog).getByText('Existing note')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('Comment'), { target: { value: 'New note' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Post comment' }));
    await waitFor(() => expect(api.addComment).toHaveBeenCalledWith('alpha', 't_1', 'New note'));
    await waitFor(() => expect(api.fetchTask).toHaveBeenCalledTimes(2));
  });

  it('uploads a file and downloads by attachment ID, never stored_path', async () => {
    vi.mocked(api.uploadAttachment).mockResolvedValue({attachment:{id:5}});
    vi.mocked(api.downloadAttachment).mockResolvedValue(new Blob(['proof']));
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<TaskDrawer {...props} />);
    await screen.findByText('proof.txt');
    fireEvent.change(screen.getByLabelText('Upload attachment'), { target: { files: [new File(['new'], 'new.txt')] } });
    await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalledWith('alpha', 't_1', expect.any(File)));
    fireEvent.click(screen.getByRole('button', { name: 'Download proof.txt' }));
    await waitFor(() => expect(api.downloadAttachment).toHaveBeenCalledWith('alpha', 3));
  });

  it('rolls back a refused status edit and shows the server refusal', async () => {
    vi.mocked(api.patchTask).mockRejectedValue(new Error('workflow refused'));
    render(<TaskDrawer {...props} />);
    const status = await screen.findByLabelText('Status');
    fireEvent.change(status, { target: { value: 'ready' } });
    expect((await screen.findByRole('alert')).textContent).toContain('workflow refused');
    expect((screen.getByLabelText('Status') as HTMLSelectElement).value).toBe('triage');
  });

  it('labels unavailable worker controls instead of claiming success', async () => {
    render(<TaskDrawer {...props} />);
    expect(await screen.findByText('Inspect queue')).toBeTruthy();
    expect((screen.getByRole('button', { name: /reclaim.*unavailable/i }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('tab', { name: 'Log' }));
    expect(screen.getByText(/log adapter unavailable/i)).toBeTruthy();
  });
});
