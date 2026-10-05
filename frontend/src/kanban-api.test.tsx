import { afterEach, describe, expect, it, vi } from 'vitest';
import { boardPath, kanbanEventsUrl, uploadAttachment, downloadAttachment, createKanbanSocket } from './panels/kanban/api';

vi.mock('./api/client', () => ({
  apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(), getAdminToken: () => 'test-admin', getToken: () => 'test-user',
}));
vi.mock('./base-path', () => ({ appUrl: (path: string) => `/v2${path}` }));

describe('Kanban transport', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('scopes board and event URLs to the selected slug and snapshot cursor', () => {
    expect(boardPath('team one')).toBe('/api/kanban/board?board=team+one');
    expect(kanbanEventsUrl('team one', 43)).toBe('ws://localhost:3000/v2/api/kanban/events?board=team+one&since=43');
  });

  it('rejects stale socket frames after a board switch and closes the old socket', () => {
    const sockets: FakeSocket[] = [];
    vi.stubGlobal('WebSocket', class extends FakeSocket { constructor(url: string, protocols: string[]) { super(url, protocols); sockets.push(this); } });
    const onFrame = vi.fn();
    const first = createKanbanSocket('alpha', 7, onFrame);
    first.close();
    const second = createKanbanSocket('beta', 9, onFrame);
    sockets[0].emit({ events: [{ id: 8 }] });
    sockets[1].emit({ events: [{ id: 10 }] });
    expect(sockets[0].closed).toBe(true);
    expect(onFrame).toHaveBeenCalledTimes(1);
    expect(sockets[1].protocols).toEqual(['nerva-kanban', 'nerva-admin.test-admin']);
    second.close();
  });

  it('uploads exactly one multipart file and downloads by integer attachment ID with admin auth', async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ attachment: { id: 3 } }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    vi.stubGlobal('fetch', fetcher);
    await uploadAttachment('alpha', 't_1', new File(['hello'], 'note.txt', { type: 'text/plain' }));
    const [uploadUrl, uploadInit] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(uploadUrl).toBe('/v2/api/kanban/tasks/t_1/attachments?board=alpha');
    expect((uploadInit.body as FormData).getAll('file')).toHaveLength(1);
    expect((uploadInit.headers as Record<string, string>)['X-Admin-Token']).toBe('test-admin');
    await downloadAttachment('alpha', 3);
    expect(fetcher.mock.calls[1][0]).toBe('/v2/api/kanban/attachments/3?board=alpha');
    await expect(downloadAttachment('alpha', '3/../../bad' as unknown as number)).rejects.toThrow('integer attachment ID');
  });
});

class FakeSocket {
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;
  constructor(public url: string, public protocols: string[]) {}
  close() { this.closed = true; this.onclose?.(); }
  emit(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
}
