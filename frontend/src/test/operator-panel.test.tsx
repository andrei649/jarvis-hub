import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { apiPost } from '../api/client';
import { OperatorPanel } from '../operator-panel';

vi.mock('../api/client', () => ({ apiPost: vi.fn() }));

const post = vi.mocked(apiPost);

beforeEach(() => {
  post.mockReset();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function desktopPreviewResponse(actions: Array<'read' | 'locate' | 'click' | 'type' | 'launch'>) {
  return {
    steps: actions.map((action) => {
      const mutating = action === 'click' || action === 'type' || action === 'launch';
      return { action, mutating, requires_approval: mutating, would_run: !mutating };
    }),
  };
}

function addDomain(domain = 'example.com') {
  fireEvent.change(screen.getByLabelText('Allowlisted domain'), { target: { value: domain } });
  fireEvent.click(screen.getByRole('button', { name: 'add domain' }));
}

function addBrowserStep(action: 'navigate' | 'extract' | 'click' | 'type' | 'submit', value: string, text = '') {
  fireEvent.change(screen.getByLabelText('Browser action'), { target: { value: action } });
  const label = action === 'navigate' ? 'Browser step URL' : 'Browser selector';
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  if (action === 'type') {
    fireEvent.change(screen.getByLabelText('Browser type text'), { target: { value: text } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'add browser step' }));
}

function addDesktopStep(action: 'read' | 'locate' | 'click' | 'type' | 'launch', value: string, text = '') {
  fireEvent.change(screen.getByLabelText('Desktop action'), { target: { value: action } });
  const labels = {
    read: 'Desktop query',
    locate: 'Desktop query',
    click: 'Desktop element name',
    type: 'Desktop element name',
    launch: 'Desktop app id',
  } as const;
  fireEvent.change(screen.getByLabelText(labels[action]), { target: { value } });
  if (action === 'type') {
    fireEvent.change(screen.getByLabelText('Desktop type text'), { target: { value: text } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'add desktop step' }));
}

async function previewDesktop(steps = 1) {
  post.mockResolvedValueOnce(desktopPreviewResponse(
    Array.from({ length: steps }, (_, index) => index ? 'click' : 'read'),
  ));
  fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
  await waitFor(() => expect(screen.getByText('Preview only · nothing executed')).toBeTruthy());
}

describe('OperatorPanel browser policy dry run', () => {
  it('makes zero API calls on mount and explains the fail-closed boundary', () => {
    render(<OperatorPanel />);
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByText(/empty allowlist is fail-closed/i)).toBeTruthy();
    expect(screen.getByText(/policy dry run/i)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /browser run/i })).toBeNull();
  });

  it('offers only the structured safe browser actions', () => {
    render(<OperatorPanel />);
    const options = within(screen.getByLabelText('Browser action')).getAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['navigate', 'extract', 'click', 'type', 'submit']);
  });

  it('posts the exact browser check and preview payloads with the user-token client', async () => {
    post
      .mockResolvedValueOnce({ allowed: true, reason: 'allowlisted' })
      .mockResolvedValueOnce({ steps: [
        { index: 0, action: 'navigate', kind: 'read', decision: 'run', reason: 'allowlisted' },
        { index: 1, action: 'extract', kind: 'read', decision: 'run', reason: 'allowlisted' },
        { index: 2, action: 'click', kind: 'write', decision: 'approve', reason: 'approval_required' },
        { index: 3, action: 'type', kind: 'write', decision: 'approve', reason: 'approval_required' },
        { index: 4, action: 'submit', kind: 'write', decision: 'approve', reason: 'approval_required' },
      ] });
    render(<OperatorPanel />);
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'https://example.com/home' } });
    addDomain('example.com');
    addBrowserStep('navigate', 'https://example.com/login');
    addBrowserStep('extract', '.title');
    addBrowserStep('click', '#save');
    addBrowserStep('type', '#password', 'do-not-render');
    addBrowserStep('submit', 'form');

    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/allowed · allowlisted/i));
    expect(post).toHaveBeenNthCalledWith(1, '/api/browser/check', {
      url: 'https://example.com/home',
      allowlist: ['example.com'],
    });

    fireEvent.click(screen.getByRole('button', { name: 'preview browser plan' }));
    await waitFor(() => expect(screen.getAllByText(/approval_required/).length).toBeGreaterThan(0));
    expect(post).toHaveBeenNthCalledWith(2, '/api/browser/plan/preview', {
      allowlist: ['example.com'],
      plan: [
        { action: 'navigate', url: 'https://example.com/login' },
        { action: 'extract', selector: '.title' },
        { action: 'click', selector: '#save' },
        { action: 'type', selector: '#password', text: 'do-not-render' },
        { action: 'submit', selector: 'form' },
      ],
    });
    expect(document.body.textContent).not.toContain('do-not-render');
    expect(screen.getAllByText('13 characters').length).toBeGreaterThan(0);
    expect(post.mock.calls.every((call) => call.length === 2)).toBe(true);
  });

  it('enforces allowlist count and domain caps in the handler', () => {
    render(<OperatorPanel />);
    addDomain('a'.repeat(253));
    expect(within(screen.getByLabelText('browser allowlist')).getAllByRole('listitem')).toHaveLength(1);

    fireEvent.change(screen.getByLabelText('Allowlisted domain'), { target: { value: 'b'.repeat(254) } });
    fireEvent.click(screen.getByRole('button', { name: 'add domain' }));
    expect(screen.getByRole('alert').textContent).toMatch(/253/);
    expect(within(screen.getByLabelText('browser allowlist')).getAllByRole('listitem')).toHaveLength(1);

    fireEvent.click(screen.getByRole('button', { name: 'remove domain ' + 'a'.repeat(253) }));
    for (let index = 0; index < 20; index += 1) addDomain(`host${index}.example`);
    expect(within(screen.getByLabelText('browser allowlist')).getAllByRole('listitem')).toHaveLength(20);
    addDomain('overflow.example');
    expect(screen.getByRole('alert').textContent).toMatch(/20/);
  });

  it('enforces URL, selector, type-text, and plan count caps in handlers', async () => {
    render(<OperatorPanel />);
    addDomain();
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'u'.repeat(2000) } });
    post.mockResolvedValueOnce({ allowed: false, reason: 'invalid_url' });
    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'u'.repeat(2001) } });
    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    expect(post).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert').textContent).toMatch(/2,000/);

    addBrowserStep('click', 's'.repeat(512));
    expect(within(screen.getByLabelText('browser plan')).getAllByRole('listitem')).toHaveLength(1);
    addBrowserStep('click', 's'.repeat(513));
    expect(screen.getByRole('alert').textContent).toMatch(/512/);

    addBrowserStep('type', '#field', 'x'.repeat(4000));
    expect(screen.getByText('4000 characters')).toBeTruthy();
    addBrowserStep('type', '#field', 'x'.repeat(4001));
    expect(screen.getByRole('alert').textContent).toMatch(/4,000/);

    fireEvent.click(screen.getAllByRole('button', { name: /remove browser step/i })[0]);
    fireEvent.click(screen.getAllByRole('button', { name: /remove browser step/i })[0]);
    for (let index = 0; index < 20; index += 1) addBrowserStep('click', `#item-${index}`);
    expect(within(screen.getByLabelText('browser plan')).getAllByRole('listitem')).toHaveLength(20);
    addBrowserStep('click', '#overflow');
    expect(screen.getByRole('alert').textContent).toMatch(/20/);
  });

  it('caps backend browser reasons to 240 characters', async () => {
    const reason = 'r'.repeat(300);
    post
      .mockResolvedValueOnce({ allowed: false, reason })
      .mockResolvedValueOnce({ steps: [{ index: 0, action: 'click', decision: 'block', reason }] });
    render(<OperatorPanel />);
    addDomain();
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'https://example.com' } });
    addBrowserStep('click', '#save');

    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    await waitFor(() => expect(screen.getByText('r'.repeat(240))).toBeTruthy());
    expect(document.body.textContent).not.toContain(reason);
    fireEvent.click(screen.getByRole('button', { name: 'preview browser plan' }));
    await waitFor(() => expect(screen.getAllByText('r'.repeat(240))).toHaveLength(2));
    expect(document.body.textContent).not.toContain(reason);
  });

  it('invalidates policy-check evidence on URL or allowlist edits and ignores a late response', async () => {
    post.mockResolvedValue({ allowed: true, reason: 'allowlisted' });
    render(<OperatorPanel />);
    addDomain();
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'https://example.com' } });

    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    await waitFor(() => expect(screen.getByLabelText('browser check result')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'https://evil.example' } });
    expect(screen.queryByLabelText('browser check result')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    await waitFor(() => expect(screen.getByLabelText('browser check result')).toBeTruthy());
    addDomain('other.example');
    expect(screen.queryByLabelText('browser check result')).toBeNull();

    const late = deferred<unknown>();
    post.mockReset();
    post.mockReturnValueOnce(late.promise);
    fireEvent.click(screen.getByRole('button', { name: 'check policy' }));
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'https://changed.example' } });
    late.resolve({ allowed: true, reason: 'stale-allow' });
    await waitFor(() => expect((screen.getByRole('button', { name: 'check policy' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByLabelText('browser check result')).toBeNull();
  });

  it('invalidates browser preview evidence on allowlist or plan edits and ignores a late response', async () => {
    post.mockResolvedValue({ steps: [{ index: 0, action: 'click', kind: 'risky', decision: 'approve', reason: 'approval_required' }] });
    render(<OperatorPanel />);
    addDomain();
    addBrowserStep('click', '#save');

    fireEvent.click(screen.getByRole('button', { name: 'preview browser plan' }));
    await waitFor(() => expect(screen.getByLabelText('browser preview result')).toBeTruthy());
    addDomain('other.example');
    expect(screen.queryByLabelText('browser preview result')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'preview browser plan' }));
    await waitFor(() => expect(screen.getByLabelText('browser preview result')).toBeTruthy());
    addBrowserStep('extract', '.title');
    expect(screen.queryByLabelText('browser preview result')).toBeNull();

    const late = deferred<unknown>();
    post.mockReset();
    post.mockReturnValueOnce(late.promise);
    fireEvent.click(screen.getByRole('button', { name: 'preview browser plan' }));
    fireEvent.click(screen.getByRole('button', { name: 'remove browser step 2' }));
    late.resolve({ steps: [
      { index: 0, action: 'click', kind: 'risky', decision: 'approve', reason: 'approval_required' },
      { index: 1, action: 'extract', kind: 'read', decision: 'run', reason: '' },
    ] });
    await waitFor(() => expect((screen.getByRole('button', { name: 'preview browser plan' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByLabelText('browser preview result')).toBeNull();
  });

  it.each([
    ['empty', { steps: [] }],
    ['wrong index', { steps: [{ index: 1, action: 'click', kind: 'risky', decision: 'approve', reason: '' }] }],
    ['wrong action', { steps: [{ index: 0, action: 'extract', kind: 'read', decision: 'run', reason: '' }] }],
    ['unknown decision', { steps: [{ index: 0, action: 'click', kind: 'risky', decision: 'maybe', reason: '' }] }],
  ])('rejects an %s browser preview response as unverified', async (_label, response) => {
    post.mockResolvedValueOnce(response);
    render(<OperatorPanel />);
    addDomain();
    addBrowserStep('click', '#save');
    fireEvent.click(screen.getByRole('button', { name: 'preview browser plan' }));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/invalid browser preview/i));
    expect(screen.queryByLabelText('browser preview result')).toBeNull();
  });
});

describe('OperatorPanel governed desktop', () => {
  it('states the default-off isolated-host and ToolRPC approval boundary', () => {
    render(<OperatorPanel />);
    expect(screen.getByText(/desktop actuation is default-off/i)).toBeTruthy();
    expect(screen.getByText(/explicitly enabled, isolated host/i)).toBeTruthy();
    expect(screen.getByText(/ToolRPC.*Decision Inbox/i)).toBeTruthy();
    expect(screen.getByText(/panel cannot approve/i)).toBeTruthy();
  });

  it('offers only the safe desktop subset and never renders typed text', () => {
    render(<OperatorPanel />);
    const options = within(screen.getByLabelText('Desktop action')).getAllByRole('option');
    expect(options.map((option) => option.textContent)).toEqual(['read', 'locate', 'click', 'type', 'launch']);
    addDesktopStep('type', 'Password', 'desktop-secret');
    expect(screen.getByText('14 characters')).toBeTruthy();
    expect(document.body.textContent).not.toContain('desktop-secret');
    expect(screen.queryByText(/observe/i)).toBeNull();
    expect(screen.queryByText(/screenshot/i)).toBeNull();
  });

  it('enforces desktop argument and 20-step caps in handlers', () => {
    render(<OperatorPanel />);
    addDesktopStep('read', 'q'.repeat(512));
    addDesktopStep('read', 'q'.repeat(513));
    expect(screen.getByRole('alert').textContent).toMatch(/512/);
    addDesktopStep('type', 'Name', 'x'.repeat(4000));
    expect(screen.getByText('4000 characters')).toBeTruthy();
    addDesktopStep('type', 'Name', 'x'.repeat(4001));
    expect(screen.getByRole('alert').textContent).toMatch(/4,000/);

    for (const button of screen.getAllByRole('button', { name: /remove desktop step/i })) {
      fireEvent.click(button);
    }
    for (let index = 0; index < 20; index += 1) addDesktopStep('click', `Button ${index}`);
    expect(within(screen.getByLabelText('desktop plan')).getAllByRole('listitem')).toHaveLength(20);
    addDesktopStep('click', 'Overflow');
    expect(screen.getByRole('alert').textContent).toMatch(/20/);
  });

  it('stores a deep canonical preview snapshot and runs that snapshot without approval fields', async () => {
    post
      .mockResolvedValueOnce(desktopPreviewResponse(['read']))
      .mockResolvedValueOnce({ ok: true, ran: [{ action: 'read', status: 'ran', result: { text: 'safe result' } }] });
    render(<OperatorPanel />);
    addDesktopStep('read', '  Account total  ');
    fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(false));

    const previewBody = post.mock.calls[0][1] as { steps: Array<{ args: { query: string } }> };
    expect(previewBody).toEqual({ steps: [{ action: 'read', args: { query: 'Account total' } }] });
    previewBody.steps[0].args.query = 'tampered-after-request';
    fireEvent.change(screen.getByLabelText('Desktop query'), { target: { value: 'builder-only change' } });
    fireEvent.click(screen.getByRole('button', { name: 'submit governed plan' }));

    await waitFor(() => expect(screen.getByText('Executed')).toBeTruthy());
    expect(post).toHaveBeenNthCalledWith(2, '/api/desktop/run', {
      steps: [{ action: 'read', args: { query: 'Account total' } }],
    });
    const serialized = JSON.stringify(post.mock.calls[1][1]);
    expect(serialized).not.toMatch(/approved|caller_approved|admin/i);
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('invalidates Run on plan edits and ignores a late preview response', async () => {
    const late = deferred<unknown>();
    post.mockReturnValueOnce(late.promise);
    render(<OperatorPanel />);
    addDesktopStep('read', 'summary');
    fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
    expect((screen.getByRole('button', { name: 'preview desktop plan' }) as HTMLButtonElement).disabled).toBe(true);

    addDesktopStep('click', 'Save');
    late.resolve({ steps: [{ action: 'read' }] });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText('Preview only · nothing executed')).toBeNull();

    post.mockResolvedValueOnce(desktopPreviewResponse(['read', 'click']));
    fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
    await waitFor(() => expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: 'remove desktop step 2' }));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText('Preview only · nothing executed')).toBeNull();
  });

  it('rejects malformed and ok:false previews without unlocking Run', async () => {
    post
      .mockResolvedValueOnce({ raw: true })
      .mockResolvedValueOnce({ ok: false, reason: 'desktop_host_disabled', steps: [] })
      .mockResolvedValueOnce({ steps: [{ action: 'read', mutating: false }] });
    render(<OperatorPanel />);
    addDesktopStep('read', 'summary');

    fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/invalid desktop preview/i));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/desktop_host_disabled/));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'preview desktop plan' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/invalid desktop preview/i));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it.each([
    ['queued', { ok: false, reason: 'approval_required', task_id: 'task-9' }, /Queued.*task-9.*Decision Inbox/i],
    ['blocked', { ok: false, reason: 'desktop_host_disabled', ran: [] }, /Blocked.*desktop_host_disabled/i],
    ['failed', { ok: false, reason: 'host_crashed', ran: [] }, /Failed.*host_crashed/i],
    ['executed', { ok: true, ran: [{ action: 'read', status: 'ran', result: { text: 'safe result' } }] }, /Executed/i],
  ] as const)('renders the %s outcome distinctly', async (_label, response, expected) => {
    post
      .mockResolvedValueOnce(desktopPreviewResponse(['read']))
      .mockResolvedValueOnce(response);
    render(<OperatorPanel />);
    addDesktopStep('read', 'summary');
    await previewDesktop();
    fireEvent.click(screen.getByRole('button', { name: 'submit governed plan' }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(expected));
  });

  it.each([
    [
      'a normalized-looking status',
      { ok: true, ran: [{ action: 'read', status: ' RAN ' }] },
      /Failed/i,
    ],
    [
      'a malformed extra returned entry',
      { ok: true, ran: [{ action: 'read', status: 'ran' }, null] },
      /Partial/i,
    ],
    [
      'a raw governance marker',
      { ok: false, blocked: true, ran: [] },
      /Blocked/i,
    ],
  ] as const)('classifies raw run evidence before rendering sanitization: %s', async (_label, response, expected) => {
    post
      .mockResolvedValueOnce(desktopPreviewResponse(['read']))
      .mockResolvedValueOnce(response);
    render(<OperatorPanel />);
    addDesktopStep('read', 'summary');
    await previewDesktop();
    fireEvent.click(screen.getByRole('button', { name: 'submit governed plan' }));

    await waitFor(() => expect(screen.getByLabelText('desktop outcome').textContent).toMatch(expected));
  });

  it('renders partial per-step state with the exact no-retry warning and no typed result', async () => {
    post
      .mockResolvedValueOnce(desktopPreviewResponse(['read', 'type']))
      .mockResolvedValueOnce({
        ok: false,
        reason: 'kernel_refused',
        ran: [
          { action: 'read', status: 'ran', result: { text: 'safe observation', elements: [{ role: 'text', name: 'Total' }] } },
          { action: 'type', status: 'blocked', reason: 'approval_required', args: { text: 'typed-secret' }, result: { text: 'typed-secret' } },
        ],
      });
    render(<OperatorPanel />);
    addDesktopStep('read', 'summary');
    addDesktopStep('type', 'Password', 'draft-secret');
    await previewDesktop(2);
    fireEvent.click(screen.getByRole('button', { name: 'submit governed plan' }));

    await waitFor(() => expect(screen.getByText('Do not retry the whole plan: some steps already ran')).toBeTruthy());
    expect(screen.getByText(/read · ran/)).toBeTruthy();
    expect(screen.getByText(/type · blocked · approval_required/)).toBeTruthy();
    expect(screen.getByText('safe observation')).toBeTruthy();
    expect(document.body.textContent).not.toContain('typed-secret');
    expect(document.body.textContent).not.toContain('draft-secret');
  });

  it('disables submit while Run is in flight and consumes preview after rejection', async () => {
    const running = deferred<unknown>();
    post
      .mockResolvedValueOnce(desktopPreviewResponse(['read']))
      .mockReturnValueOnce(running.promise);
    render(<OperatorPanel />);
    addDesktopStep('read', 'summary');
    await previewDesktop();
    fireEvent.click(screen.getByRole('button', { name: 'submit governed plan' }));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'preview desktop plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'add desktop step' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'remove desktop step 1' }) as HTMLButtonElement).disabled).toBe(true);
    running.reject(new Error('POST /api/desktop/run -> 503'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/503/));
    expect((screen.getByRole('button', { name: 'submit governed plan' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText('Preview only · nothing executed')).toBeNull();
  });
});

describe('OperatorPanel request errors', () => {
  it.each([
    ['browser check', 'check policy'],
    ['browser preview', 'preview browser plan'],
    ['desktop preview', 'preview desktop plan'],
    ['desktop run', 'submit governed plan'],
  ] as const)('shows a bounded alert and clears stale success for %s rejection', async (_label, buttonName) => {
    render(<OperatorPanel />);
    addDomain();
    fireEvent.change(screen.getByLabelText('Browser URL'), { target: { value: 'https://example.com' } });
    addBrowserStep('click', '#save');
    addDesktopStep('read', 'summary');

    if (buttonName === 'check policy') {
      post.mockResolvedValueOnce({ allowed: true, reason: 'allowlisted' });
      fireEvent.click(screen.getByRole('button', { name: buttonName }));
      await waitFor(() => expect(screen.getByLabelText('browser check result')).toBeTruthy());
    } else if (buttonName === 'preview browser plan') {
      post.mockResolvedValueOnce({ steps: [{ index: 0, action: 'click', decision: 'block', reason: 'test' }] });
      fireEvent.click(screen.getByRole('button', { name: buttonName }));
      await waitFor(() => expect(screen.getByLabelText('browser preview result')).toBeTruthy());
    } else if (buttonName === 'preview desktop plan' || buttonName === 'submit governed plan') {
      await previewDesktop();
    }
    post.mockRejectedValueOnce(new Error('E'.repeat(400)));
    fireEvent.click(screen.getByRole('button', { name: buttonName }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
    const alert = screen.getByRole('alert');
    expect(alert.textContent?.length).toBeLessThanOrEqual(240);
    expect(alert.textContent).not.toContain('E'.repeat(241));
    if (buttonName === 'check policy') expect(screen.queryByLabelText('browser check result')).toBeNull();
    if (buttonName === 'preview browser plan') expect(screen.queryByLabelText('browser preview result')).toBeNull();
    if (buttonName.startsWith('preview desktop') || buttonName.startsWith('submit governed')) {
      expect(screen.queryByText('Preview only · nothing executed')).toBeNull();
    }
  });
});
