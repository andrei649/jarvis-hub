import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ApiError, type ApprovalTask } from '../../api/client';
import { ApprovalDecisionController } from '../approvalDecision';

const config = { baseUrl: 'http://jarvis.lan', token: 'synthetic-user', adminToken: 'synthetic-admin' };
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const revision = 'a'.repeat(64);
const task = (): ApprovalTask => ({ id: 42, kind: 'toolrpc.terminal_run', consent_offer: {
  revision, count: 2, choices: ['session', 'always', 'deny'],
  categories: [{ description: 'Destructive Git operation', permanent: true }],
} });
function response(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as Response;
}
beforeEach(() => { mockFetch.mockReset(); (globalThis as any).fetch = mockFetch; });

describe('native approval decision controller', () => {
  it.each(['session', 'always', 'deny'] as const)('dispatches exact displayed %s offer and refreshes after confirmation', async choice => {
    const status = choice === 'deny' ? 'rejected' : 'approved';
    mockFetch.mockResolvedValueOnce(response({ ok: true, tasks: [{ id: 42, status }, { id: 43, status }] }));
    const onApplied = jest.fn(async () => undefined);
    const controller = new ApprovalDecisionController();
    expect(await controller.submit({ config, task: task(), selection: { choice }, reason: 'Synthetic owner reason', onApplied })).toBe(true);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe('http://jarvis.lan/autonomy/tasks/42/consent');
    expect(JSON.parse(String(init?.body))).toEqual({ choice, revision, reason: 'Synthetic owner reason' });
    expect(onApplied).toHaveBeenCalledTimes(1);
    expect(controller.busy).toBeNull();
  });

  it('passes ordinary reasons and retains the omitted-reason contract', async () => {
    mockFetch.mockResolvedValue(response({ ok: true, task: { id: 42, status: 'rejected' } }));
    const controller = new ApprovalDecisionController();
    await controller.submit({ config, task: task(), selection: { action: 'reject' }, reason: 'No longer needed' });
    await controller.submit({ config, task: task(), selection: { action: 'defer' } });
    expect(JSON.parse(String(mockFetch.mock.calls[0][1]?.body))).toEqual({ action: 'reject', reason: 'No longer needed' });
    expect(JSON.parse(String(mockFetch.mock.calls[1][1]?.body))).toEqual({ action: 'defer' });
  });

  it.each([{ ok: false, task: { id: 42 } }, { ok: true }, { ok: true, task: { id: 99, status: 'approved' } }])('does not refresh on false or malformed ordinary confirmation', async body => {
    mockFetch.mockResolvedValueOnce(response(body));
    const onApplied = jest.fn(async () => undefined);
    await expect(new ApprovalDecisionController().submit({ config, task: task(), selection: { action: 'accept' }, onApplied })).rejects.toThrow(/confirmed/);
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('surfaces stale 409 without replacing revision or refreshing', async () => {
    mockFetch.mockResolvedValueOnce(response({ error: 'consent offer changed' }, 409));
    const onApplied = jest.fn(async () => undefined);
    const displayed = task();
    await expect(new ApprovalDecisionController().submit({ config, task: displayed, selection: { choice: 'session' }, onApplied })).rejects.toBeInstanceOf(ApiError);
    expect(onApplied).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect((displayed.consent_offer as any).revision).toBe(revision);
  });

  it('holds a synchronous lock through confirmation and refresh across all cards', async () => {
    let finish!: (value: Response) => void;
    mockFetch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    let finishRefresh!: () => void;
    const controller = new ApprovalDecisionController();
    const pending = controller.submit({ config, task: task(), selection: { choice: 'session' },
      onApplied: () => new Promise<void>(resolve => { finishRefresh = resolve; }) });
    expect(controller.busy).toEqual({ id: 42, action: 'session' });
    expect(await controller.submit({ config, task: { id: 43 }, selection: { action: 'reject' } })).toBe(false);
    finish(response({ ok: true, tasks: [{ id: 42, status: 'approved' }] }));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(controller.busy).not.toBeNull();
    expect(await controller.submit({ config, task: task(), selection: { choice: 'always' } })).toBe(false);
    finishRefresh(); await pending;
    expect(controller.busy).toBeNull(); expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('keeps desktop approval unavailable even with a forged consent offer', async () => {
    const desktop = { ...task(), kind: 'toolrpc.desktop_run' };
    for (const selection of [{ action: 'accept' }, { choice: 'session' }, { choice: 'always' }, { choice: 'deny' }] as const) {
      await expect(new ApprovalDecisionController().submit({ config, task: desktop, selection })).rejects.toThrow(/unavailable/);
    }
    expect(mockFetch).not.toHaveBeenCalled();
    mockFetch.mockResolvedValue(response({ ok: true, task: { id: 42, status: 'rejected' } }));
    expect(await new ApprovalDecisionController().submit({ config, task: desktop, selection: { action: 'reject' } })).toBe(true);
  });

  it('refuses malformed offers and permanence unsupported by any category before dispatch', async () => {
    const controller = new ApprovalDecisionController();
    await expect(controller.submit({ config, task: { id: 42, consent_offer: { revision } }, selection: { choice: 'session' } })).rejects.toThrow(/offer/);
    const nonPermanent = task(); (nonPermanent.consent_offer as any).categories[0].permanent = false;
    await expect(controller.submit({ config, task: nonPermanent, selection: { choice: 'always' } })).rejects.toThrow(/permanent/i);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('counts reason Unicode codepoints and refuses oversize input before dispatch', async () => {
    const controller = new ApprovalDecisionController();
    await expect(controller.submit({ config, task: task(), selection: { action: 'reject' }, reason: '😀'.repeat(281) })).rejects.toThrow(/280/);
    expect(mockFetch).not.toHaveBeenCalled();
    mockFetch.mockResolvedValueOnce(response({ ok: true, tasks: [{ id: 42, status: 'rejected' }] }));
    expect(await controller.submit({ config, task: task(), selection: { choice: 'deny' }, reason: '😀'.repeat(280) })).toBe(true);
  });

  it('does not apply old connection results after an epoch changes', async () => {
    let finish!: (value: Response) => void;
    mockFetch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    let current = true;
    const onApplied = jest.fn(async () => undefined);
    const controller = new ApprovalDecisionController();
    const pending = controller.submit({ config, task: task(), selection: { choice: 'session' }, isCurrent: () => current, onApplied });
    current = false; finish(response({ ok: true, tasks: [{ id: 42, status: 'approved' }] }));
    expect(await pending).toBe(false); expect(onApplied).not.toHaveBeenCalled(); expect(controller.busy).toBeNull();
  });
});
