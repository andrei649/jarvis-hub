// @ts-nocheck
/* WRITEBACK & DIGEST — the four ways this panel could have lied, each pinned here:

     1. queued:false painted as a queued write. It is the no-enqueue-sink branch of
        WriteBackBroker.request (writeback.py:435-437): validated, previewed, discarded.
        The test asserts the amber wording AND the absence of any task id.
     2. A 422 refusal painted as success — or paraphrased. apiPost throws, so a
        `.then(r => r.ok ? … : …)` branch is dead code; the test asserts the backend's own
        `missing_fields` / `missing` / `required` strings reach the screen and the success
        line does not.
     3. A digest count of 0 painted as "no results". Every source failure is swallowed
        (digest.py DigestSource.fetch), so the test asserts the ambiguity sentence.
     4. A digest 422 painted as an empty digest. The test asserts the detail body is shown
        and that no "0 items" line appears. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { WritebackDigestPanel } from './writeback-digest';

/* The catalog exactly as WriteBackBroker.targets() emits it (writeback.py:_CATALOG,
   insertion order preserved). */
const CATALOG = {
  targets: [
    { target: 'notion', action: 'create_page', label: 'Create Notion page', required: ['title'], optional: ['parent', 'content'], kind: 'writeback.notion.create_page', credential: 'notion_api_key' },
    { target: 'notion', action: 'append_block', label: 'Append to Notion page', required: ['page_id', 'text'], optional: [], kind: 'writeback.notion.append_block', credential: 'notion_api_key' },
    { target: 'github', action: 'create_issue', label: 'Create GitHub issue', required: ['repo', 'title'], optional: ['body', 'labels', 'assignees'], kind: 'writeback.github.create_issue', credential: 'github_token' },
    { target: 'github', action: 'comment_issue', label: 'Comment on GitHub issue', required: ['repo', 'issue', 'body'], optional: [], kind: 'writeback.github.comment_issue', credential: 'github_token' },
    { target: 'google_calendar', action: 'create_event', label: 'Create Calendar event', required: ['summary', 'start', 'end'], optional: ['calendar_id', 'description', 'location', 'attendees'], kind: 'writeback.google_calendar.create_event', credential: 'google_oauth_token' },
  ],
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
const refuse = (status, body) => ({ ok: false, status, json: async () => body });

/* Route by path AND method so a write never answers a read (and vice versa). */
function mockFetch({ wbPost, digestPost } = {}) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = (init && init.method) || 'GET';
    if (u.includes('/api/integrations/writeback')) {
      if (method === 'GET') return ok(CATALOG);
      return typeof wbPost === 'function' ? wbPost(JSON.parse(init.body)) : wbPost;
    }
    if (u.includes('/api/digest/run')) {
      return typeof digestPost === 'function' ? digestPost(JSON.parse(init.body)) : digestPost;
    }
    throw new Error('unexpected fetch ' + u);
  });
  global.fetch = fn;
  return fn;
}

const body = () => document.body.textContent;

beforeEach(() => { vi.restoreAllMocks(); });

describe('WRITEBACK & DIGEST · catalog', () => {
  it('renders every shipped action with its kind, credential NAME and required fields', async () => {
    mockFetch({});
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(body()).toContain('Create Notion page'));

    for (const label of ['Create Notion page', 'Append to Notion page', 'Create GitHub issue',
      'Comment on GitHub issue', 'Create Calendar event']) {
      expect(body()).toContain(label);
    }
    expect(body()).toContain('needs notion_api_key');
    expect(body()).toContain('needs github_token');
    expect(body()).toContain('needs google_oauth_token');
    expect(body()).toContain('writeback.github.comment_issue');
    // …and the standing limit: a NAME is not a configured secret.
    expect(body()).toContain('cannot see whether it is configured');
  });

  it('generates the form from the selected entry own required/optional arrays', async () => {
    mockFetch({});
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByPlaceholderText('title · required')).toBeTruthy());
    expect(screen.getByPlaceholderText('parent · optional')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('write-back action'), { target: { value: 'github:create_issue' } });
    expect(screen.getByPlaceholderText('repo · required')).toBeTruthy();
    expect(screen.getByPlaceholderText('title · required')).toBeTruthy();
    expect(screen.getByPlaceholderText('labels · optional · comma-separated list')).toBeTruthy();
    expect(screen.queryByPlaceholderText('parent · optional')).toBeNull();
  });

  it('keeps the submit disabled until every required field is filled — and fires no POST', async () => {
    const fetchMock = mockFetch({});
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByText('queue write-back')).toBeTruthy());

    const btn = screen.getByText('queue write-back');
    expect(btn.disabled).toBe(true);
    fireEvent.click(btn);
    fireEvent.change(screen.getByPlaceholderText('title · required'), { target: { value: '   ' } });
    expect(screen.getByText('queue write-back').disabled).toBe(true);

    // only the catalog GET ever left the browser
    expect(fetchMock.mock.calls.filter((c) => (c[1] && c[1].method) === 'POST')).toHaveLength(0);

    fireEvent.change(screen.getByPlaceholderText('title · required'), { target: { value: 'Q3 notes' } });
    expect(screen.getByText('queue write-back').disabled).toBe(false);
  });
});

describe('WRITEBACK & DIGEST · write-back outcomes', () => {
  it('renders queued:true as held-for-approval, never as a completed write', async () => {
    let sent = null;
    mockFetch({
      wbPost: (b) => { sent = b; return ok({
        ok: true, queued: true, task_id: 41, kind: 'writeback.notion.create_page',
        title: 'Create Notion page: Q3 notes',
        preview: { kind: 'writeback.notion.create_page', title: 'Create Notion page: Q3 notes', target: 'Q3 notes', effects: [{ field: 'target', value: 'Q3 notes' }], irreversible: true, risk_tier: 2, requires_approval: true, summary: "Would run 'writeback.notion.create_page' → Q3 notes; IRREVERSIBLE; approval required.", would_execute: false },
      }); },
    });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByPlaceholderText('title · required')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('title · required'), { target: { value: 'Q3 notes' } });
    fireEvent.click(screen.getByText('queue write-back'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('queued for approval · task #41'));
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('NOTHING has been written to notion');
    expect(alert).toContain("Would run 'writeback.notion.create_page'");   // preview.summary verbatim
    expect(body()).not.toContain('validation-only preview');
    // the body the panel actually sent: fields from the generated inputs, nothing invented
    expect(sent).toEqual({ target: 'notion', action: 'create_page', fields: { title: 'Q3 notes' }, agent: 'pepper', source: 'hud.writeback_panel' });
  });

  it('renders queued:false as an amber validation-only preview with no task id', async () => {
    mockFetch({
      wbPost: ok({
        ok: true, queued: false, kind: 'writeback.notion.create_page',
        title: 'Create Notion page: Q3 notes',
        payload: { system: 'notion', action: 'create_page', fields: { title: 'Q3 notes' }, credential_ref: '{{secret:notion_api_key}}', source: 'hud.writeback_panel', target: 'Q3 notes' },
        preview: { kind: 'writeback.notion.create_page', summary: "Would run 'writeback.notion.create_page' → Q3 notes; IRREVERSIBLE; approval required.", would_execute: false },
      }),
    });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByPlaceholderText('title · required')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('title · required'), { target: { value: 'Q3 notes' } });
    fireEvent.click(screen.getByText('queue write-back'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('validation-only preview'));
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('nothing was queued');
    expect(alert).toContain('nothing will ever run');
    expect(body()).not.toContain('queued for approval');
    expect(body()).not.toContain('task #');
    // the sanitized payload, including the secret HANDLE, shown verbatim
    expect(alert).toContain('{{secret:notion_api_key}}');
  });

  it('renders a 422 refusal in the backend own words and no success line', async () => {
    mockFetch({
      wbPost: refuse(422, { ok: false, reason: 'missing_fields', missing: ['title'], required: ['repo', 'title'] }),
    });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByPlaceholderText('title · required')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('title · required'), { target: { value: 'Q3 notes' } });
    fireEvent.click(screen.getByText('queue write-back'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('refused (422)'));
    const alert = screen.getByRole('alert').textContent;
    expect(alert).toContain('missing_fields');     // the reason, verbatim
    expect(alert).toContain('missing: title');
    expect(alert).toContain('required: repo, title');
    expect(body()).not.toContain('queued for approval');
    expect(body()).not.toContain('validation-only preview');
    // never the client-side message stand-in the sibling panel prints
    expect(body()).not.toContain('POST /api/integrations/writeback -> 422');
  });

  it('renders a free-form Action-Kernel deny reason verbatim rather than a canned sentence', async () => {
    mockFetch({ wbPost: refuse(422, { ok: false, reason: 'kernel: origin untrusted (tainted:hn)', kind: 'writeback.notion.create_page' }) });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByPlaceholderText('title · required')).toBeTruthy());
    fireEvent.change(screen.getByPlaceholderText('title · required'), { target: { value: 'Q3 notes' } });
    fireEvent.click(screen.getByText('queue write-back'));

    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('kernel: origin untrusted (tainted:hn)'));
  });
});

describe('WRITEBACK & DIGEST · digest', () => {
  it('does not run on mount, learns the source chips from the first response, and never sends sources:[]', async () => {
    const seen = [];
    const fetchMock = mockFetch({
      digestPost: (b) => { seen.push(b); return ok({ topic: 'agents', count: 1, sources: ['hn', 'reddit', 'arxiv', 'youtube', 'news'], items: [{ title: 'A release with numbers', link: 'https://example.org/a', source: 'hn', reality: 0.833, score: 1.333, tainted: true, taint_source: 'hn' }] }); },
    });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(body()).toContain('Create Notion page'));
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/digest/run'))).toHaveLength(0);
    expect(body()).toContain('not run yet');

    fireEvent.change(screen.getByPlaceholderText('topic (optional, max 200)'), { target: { value: 'agents' } });
    fireEvent.click(screen.getByText('run digest'));

    await waitFor(() => expect(body()).toContain('A release with numbers'));
    expect(seen[0]).toEqual({ topic: 'agents', limit: 10 });    // `sources` omitted = all built-ins
    expect(body()).toContain('external · hn');                   // taint surfaced
    const link = screen.getByText('A release with numbers');
    expect(link.getAttribute('rel')).toBe('noreferrer noopener');

    // chips learned from the echo; deselecting all disables the run rather than sending []
    for (const n of ['hn', 'reddit', 'arxiv', 'youtube', 'news']) fireEvent.click(screen.getByText(n));
    expect(screen.getByText('run digest').disabled).toBe(true);
    expect(body()).toContain('an empty list would silently run all of them');
    expect(seen).toHaveLength(1);
  });

  it('states the ambiguity of a zero-item run instead of calling it "no results"', async () => {
    mockFetch({ digestPost: ok({ topic: 'agents', count: 0, sources: ['hn', 'reddit', 'arxiv', 'youtube', 'news'], items: [] }) });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByText('run digest')).toBeTruthy());
    fireEvent.click(screen.getByText('run digest'));

    await waitFor(() => expect(body()).toContain('0 items'));
    expect(body()).toContain('returns silently empty');
    expect(body()).toContain('nothing matched');
    expect(body()).toContain('a fetch failed');
    expect(body()).not.toContain('no results');
  });

  it('renders a digest 422 as a refusal body, never as an empty digest', async () => {
    mockFetch({
      digestPost: refuse(422, { detail: [{ type: 'less_than_equal', loc: ['body', 'limit'], msg: 'Input should be less than or equal to 50', input: 500 }] }),
    });
    render(<WritebackDigestPanel />);
    await waitFor(() => expect(screen.getByText('run digest')).toBeTruthy());
    fireEvent.click(screen.getByText('run digest'));

    await waitFor(() => expect(body()).toContain('request failed (422)'));
    expect(body()).toContain('Input should be less than or equal to 50');
    expect(body()).toContain('this is a refusal, not an empty digest');
    expect(body()).not.toContain('0 items');
  });
});
