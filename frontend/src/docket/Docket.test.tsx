/* The docket register (PHASE_B_PLAN.md §5.4, §9.4 E4): every state; the friction of each tier
   (0 one click, 1 two steps, 2–3 a typed phrase); Enter in the signature line and keys anywhere
   on the page never sign or reject, nor a held key or a double-click's second click; "Reject all
   N" in two steps with partial results; refresh before signing when stale; real verbs, never
   "Dismiss". After a decision the outcome is kept by request: tests here make the re-read after
   the POST drop or re-key the entry, and the outcome (a refusal above all) must still be drawn.
   The floating window's line never turns an unknown into "nothing waits". `fetch` is mocked, so
   the real client, the shared poller and api/decisions.ts run. */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/owner-session', async (importOriginal) => {
  const real = await importOriginal<typeof import('../api/owner-session')>();
  return { ...real, isNetworkedOrigin: vi.fn(() => false), requireSignIn: vi.fn() };
});
import { isNetworkedOrigin, requireSignIn } from '../api/owner-session';
import { refreshPolled, resetPolling } from '../signals/poll';
import { Docket, DocketLine } from './Docket';
import { openDocketEntry } from './links';
import { DOCKET_FEED_PATH } from './types';

type Answer = { status?: number; body?: unknown; hang?: boolean; fail?: boolean; after?: Promise<unknown> };
const T0 = Date.now() - 3 * 3_600_000;
const t = (id: number, more: Record<string, unknown> = {}) => ({
  id, title: `Task ${id}`, kind: 'k', agent: 'jarvis', risk_tier: 1, status: 'blocked', created_at: new Date(T0 + id * 60_000).toISOString(), ...more,
});
const hub = {
  feed: (): Answer => ({ body: { tasks: [] } }),
  post: (_url: string, _body: unknown): Answer => ({ body: { ok: true } }),
  preview: (_id: number): Answer => ({ body: { effects: [], would_execute: false } }),
  payments: (): Answer => ({ body: { payments: [] } }),
  skills: (): Answer => ({ body: { proposals: [], count: 0, more: 0 } }),
};
let fetchMock: ReturnType<typeof vi.fn>;
let visibility: DocumentVisibilityState = 'visible';

beforeEach(() => {
  resetPolling();
  history.replaceState(null, '', '/v2/cockpit');
  visibility = 'visible';
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
  hub.feed = () => ({ body: { tasks: [] } });
  hub.post = () => ({ body: { ok: true } });
  hub.preview = () => ({ body: { effects: [], would_execute: false } });
  hub.payments = () => ({ body: { payments: [] } });
  hub.skills = () => ({ body: { proposals: [], count: 0, more: 0 } });
  vi.mocked(isNetworkedOrigin).mockReturnValue(false);
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    const answer: Answer = init?.method === 'POST' ? hub.post(u, JSON.parse(String(init.body)))
      : u.startsWith('/autonomy/tasks?') ? hub.feed()
      : u.startsWith('/api/autonomy/tasks/') ? hub.preview(Number(u.split('/')[4]))
      : u.startsWith('/api/payments') ? hub.payments()
      : u.startsWith('/api/skills/proposals') ? hub.skills()
      : { status: 404, body: {} };
    if (answer.hang) return new Promise(() => {});
    if (answer.after) await answer.after;
    if (answer.fail) throw new TypeError('Failed to fetch');
    const status = answer.status ?? 200;
    return { ok: status >= 200 && status < 300, status, json: async () => answer.body } as unknown as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => {
  resetPolling();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (document as { visibilityState?: unknown }).visibilityState;
  history.replaceState(null, '', '/');
});

const posts = () => fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')
  .map(([url, init]) => ({ url: String(url), body: JSON.parse(String(init.body)) }));
const docketEl = () => document.querySelector('[data-register="docket"]') as HTMLElement;
const sourceState = () => docketEl().querySelector('.n-register__meta [data-source-state]')?.getAttribute('data-source-state');
const entryEl = (id: number) => document.querySelector(`[data-docket-entry="${id}"]`) as HTMLElement;
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });
const feedOf = (tasks: unknown[], groups?: unknown[]) => () => ({ body: { tasks, ...(groups ? { groups } : {}) } });

async function mount(props: Partial<React.ComponentProps<typeof Docket>> = {}) {
  const navigate = vi.fn();
  render(<Docket lang="en" demo={false} navigate={navigate} {...props} />);
  await waitFor(() => expect(['live', 'empty']).toContain(sourceState()));
  return navigate;
}

describe('states', () => {
  it('checking: says so, with no figure and no "nothing waits"', () => {
    hub.feed = () => ({ hang: true });
    render(<Docket lang="en" demo={false} navigate={vi.fn()} />);
    expect(docketEl().querySelector('[data-docket-state="checking"]')?.textContent).toContain('Checking the decisions feed…');
    expect(docketEl().querySelector('h2')?.textContent).toBe('Docket');
    expect(docketEl().querySelector('.n-docket__figure')).toBeNull();
    expect(docketEl().textContent).not.toMatch(/Nothing is waiting|0 entries/);
  });

  it('live: the figure of entries in the owner\'s hand, ordered entries, the first one open, and a total', async () => {
    hub.feed = feedOf([t(1, { risk_tier: 1 }), t(2, { risk_tier: 3, kind: 'restart_service' }), t(3, { risk_tier: 0 })]);
    await mount();
    const figure = docketEl().querySelector('.n-docket__figure') as HTMLElement;
    expect(figure.textContent).toBe('3');
    expect(figure.getAttribute('data-figure-state')).toBe('live');
    expect(docketEl().querySelector('h2')?.textContent).toBe('3 await your signature');
    const order = Array.from(docketEl().querySelectorAll('[data-docket-entry]')).map((el) => el.getAttribute('data-docket-entry'));
    expect(order).toEqual(['2', '1', '3']);
    expect(entryEl(2).getAttribute('data-entry-state')).toBe('open');
    expect(entryEl(2).id).toBe('docket-entry-2');
    expect(entryEl(1).getAttribute('data-entry-state')).toBe('closed');
    const total = docketEl().querySelector('.n-docket__total') as HTMLElement;
    expect(total.textContent).toContain('3 entries · 3 requests');
    expect(total.textContent).toContain('1 typed');
    expect(total.textContent).toContain('1 two-step');
    expect(total.textContent).toContain('1 one click');
  });

  it('empty: a sentence over a double rule reading "0 entries", and no figure', async () => {
    await mount();
    expect(sourceState()).toBe('empty');
    expect(screen.getByText('Nothing is waiting for you.')).toBeTruthy();
    expect((docketEl().querySelector('.n-docket__total') as HTMLElement).textContent).toBe('0 entries');
    expect(docketEl().querySelector('.n-docket__figure')).toBeNull();
  });

  it('refused, on loopback: unknown — no "0", no "nothing waits" — and where to set the credential', async () => {
    hub.feed = () => ({ status: 401, body: {} });
    const navigate = vi.fn();
    render(<Docket lang="en" demo={false} navigate={navigate} />);
    await waitFor(() => expect(sourceState()).toBe('refused'));
    const state = docketEl().querySelector('[data-docket-state="refused"]') as HTMLElement;
    expect(state.textContent).toContain('Unknown — sign in as the owner to see what is waiting.');
    expect(docketEl().textContent).not.toMatch(/Nothing is waiting|0 entries/);
    expect(docketEl().querySelector('.n-docket__figure')).toBeNull();
    const link = within(state).getByRole('link', { name: 'Trust › Trust operations' });
    expect(link.getAttribute('href')).toBe('/v2/console/trust-ops');
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith('/v2/console/trust-ops');
  });

  it('refused, on a networked origin: a Sign in button that asks for the owner\'s sign-in', async () => {
    vi.mocked(isNetworkedOrigin).mockReturnValue(true);
    hub.feed = () => ({ status: 403, body: {} });
    render(<Docket lang="en" demo={false} navigate={vi.fn()} />);
    await waitFor(() => expect(sourceState()).toBe('refused'));
    vi.mocked(requireSignIn).mockClear();
    fireEvent.click(within(docketEl()).getByRole('button', { name: 'Sign in' }));
    expect(requireSignIn).toHaveBeenCalledTimes(1);
  });

  it('offline: the last entries stay, in the stale style, and nothing can be signed until a refresh', async () => {
    hub.feed = feedOf([t(4, { risk_tier: 0, title: 'Read the logs' })]);
    await mount();
    hub.feed = () => ({ fail: true });
    await act(async () => { await refreshPolled(DOCKET_FEED_PATH, { admin: true }); });
    expect(sourceState()).toBe('offline');
    const state = docketEl().querySelector('[data-docket-state="offline"]') as HTMLElement;
    expect(state.textContent).toMatch(/Unknown — the decisions feed did not answer · last good \d\d:\d\d\./);
    expect(state.textContent).toContain('Refresh before signing.');
    expect(docketEl().querySelector('.n-docket__list')?.getAttribute('data-mode')).toBe('stale');
    expect((within(entryEl(4)).getByRole('button', { name: 'Sign: Read the logs' }) as HTMLButtonElement).disabled).toBe(true);
    hub.feed = feedOf([t(4, { risk_tier: 0, title: 'Read the logs' })]);
    fireEvent.click(within(state).getByRole('button', { name: 'Refresh' }));
    await waitFor(() => expect(sourceState()).toBe('live'));
    expect((within(entryEl(4)).getByRole('button', { name: 'Sign: Read the logs' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('unknown: the reason in words (a switched-off feed is not "empty")', async () => {
    hub.feed = () => ({ status: 503, body: {} });
    render(<Docket lang="en" demo={false} navigate={vi.fn()} />);
    await waitFor(() => expect(sourceState()).toBe('unknown'));
    expect(docketEl().querySelector('[data-docket-state="unknown"]')?.textContent).toContain('Unknown — switched off on the hub.');
    expect(docketEl().textContent).not.toContain('Nothing is waiting');
  });

  it('stale: signing waits for a refresh, and the refresh brings it back', async () => {
    vi.useFakeTimers();
    hub.feed = feedOf([t(5, { risk_tier: 0, title: 'Read the logs' })]);
    render(<Docket lang="en" demo={false} navigate={vi.fn()} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(sourceState()).toBe('live');
    visibility = 'hidden';                               // answers stop arriving (polling pauses)
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await act(async () => { await vi.advanceTimersByTimeAsync(80_000); });
    expect(sourceState()).toBe('stale');
    const sign = within(entryEl(5)).getByRole('button', { name: 'Sign: Read the logs' }) as HTMLButtonElement;
    expect(sign.disabled).toBe(true);
    const state = docketEl().querySelector('[data-docket-state="stale"]') as HTMLElement;
    expect(state.textContent).toMatch(/Stale — last checked \d\d:\d\d\./);
    expect(state.textContent).toContain('Refresh before signing.');
    fireEvent.click(within(state).getByRole('button', { name: 'Refresh' }));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(sourceState()).toBe('live');
    expect((within(entryEl(5)).getByRole('button', { name: 'Sign: Read the logs' }) as HTMLButtonElement).disabled).toBe(false);
    expect(posts()).toEqual([]);
  });

  it('demo: the labelled sample, every decision control disabled, and not one request', () => {
    render(<Docket lang="en" demo navigate={vi.fn()} />);
    expect(sourceState()).toBe('demo');
    expect(screen.getByText('Demo sample — signing is disabled.')).toBeTruthy();
    expect(docketEl().querySelectorAll('[data-docket-entry]')).toHaveLength(6);
    const open = docketEl().querySelector('[data-entry-state="open"]') as HTMLElement;
    const box = within(open).getByRole('textbox', { name: /^Type restart to sign/ });
    fireEvent.change(box, { target: { value: 'restart' } });
    expect((within(open).getByRole('button', { name: /^Sign: / }) as HTMLButtonElement).disabled).toBe(true);
    for (const verb of ['edit', 'defer', 'reject']) {
      expect((open.querySelector(`[data-verb="${verb}"]`) as HTMLButtonElement).disabled, verb).toBe(true);
    }
    for (const sign of docketEl().querySelectorAll('[data-entry-state="closed"] [data-verb="sign"] button, [data-entry-state="closed"] button[data-verb="sign"]')) {
      expect((sign as HTMLButtonElement).disabled).toBe(true);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('friction by tier', () => {
  it('tier 0: one click signs — once, however fast the clicks come', async () => {
    hub.feed = feedOf([t(5, { risk_tier: 0, title: 'Read the logs' })]);
    await mount();
    const sign = within(entryEl(5)).getByRole('button', { name: 'Sign: Read the logs' });
    fireEvent.click(sign);
    fireEvent.click(sign);
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/5/decision', body: { action: 'accept' } }]));
    await settle();
    expect(posts()).toHaveLength(1);
  });

  it('tier 1: two steps, the second shows what it does; Cancel sends nothing', async () => {
    hub.feed = feedOf([t(6, { risk_tier: 1, kind: 'draft_email', title: 'Draft a reply' })]);
    await mount();
    const entry = entryEl(6);
    fireEvent.click(within(entry).getByRole('button', { name: 'Sign: Draft a reply' }));
    const group = within(entry).getByRole('group', { name: 'Confirm the signature: Draft a reply' });
    expect(group.textContent).toContain('Drafts an email.');
    expect(document.activeElement?.textContent).toContain('Confirm signature');
    fireEvent.click(within(group).getByRole('button', { name: 'Cancel' }));
    expect(posts()).toEqual([]);
    fireEvent.click(within(entry).getByRole('button', { name: 'Sign: Draft a reply' }));
    fireEvent.click(within(entry).getByRole('button', { name: 'Confirm signature' }));
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/6/decision', body: { action: 'accept' } }]));
  });

  it('tier 1 from a closed line: "Sign" opens the entry already on its second step', async () => {
    hub.feed = feedOf([t(7, { risk_tier: 3 }), t(8, { risk_tier: 1, title: 'Move the sync' })]);
    await mount();
    expect(entryEl(8).getAttribute('data-entry-state')).toBe('closed');
    fireEvent.click(within(entryEl(8)).getByRole('button', { name: 'Sign: Move the sync' }));
    expect(entryEl(8).getAttribute('data-entry-state')).toBe('open');
    expect(within(entryEl(8)).getByRole('group', { name: 'Confirm the signature: Move the sync' })).toBeTruthy();
    expect(posts()).toEqual([]);
  });

  it.each([
    [2, 'comms.send', 'send'], [3, 'restart_service', 'restart'], [3, 'delete_file', 'delete'], [undefined, 'k', 'sign'],
  ])('tier %s (%s): typed "%s" on the signature line, exactly; the button fills only then', async (risk_tier, kind, phrase) => {
    hub.feed = feedOf([t(9, { risk_tier, kind, title: 'Typed one' })]);
    await mount();
    const entry = entryEl(9);
    expect(entry.querySelectorAll('.n-signline')).toHaveLength(1);
    const box = within(entry).getByRole('textbox', { name: `Type ${phrase} to sign: Typed one` });
    const sign = within(entry).getByRole('button', { name: 'Sign: Typed one' }) as HTMLButtonElement;
    expect(box.getAttribute('placeholder')).toBe(phrase);
    expect(sign.disabled).toBe(true);
    fireEvent.change(box, { target: { value: phrase.toUpperCase() } });
    expect(sign.disabled).toBe(true);
    fireEvent.change(box, { target: { value: ` ${phrase}` } });
    expect(sign.disabled).toBe(true);
    fireEvent.change(box, { target: { value: phrase } });
    expect(sign.disabled).toBe(false);
    fireEvent.click(sign);
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/9/decision', body: { action: 'accept' } }]));
  });

  it('a closed typed entry opens to sign and puts the cursor on the signature line', async () => {
    hub.feed = feedOf([t(10, { risk_tier: 3, kind: 'restart_service' }), t(11, { risk_tier: 3, kind: 'delete_file', title: 'Delete logs' })]);
    await mount();
    const closed = entryEl(11);
    expect(within(closed).getByText('typed: delete')).toBeTruthy();
    fireEvent.click(within(closed).getByRole('button', { name: 'Open to sign: Delete logs' }));
    expect(entryEl(11).getAttribute('data-entry-state')).toBe('open');
    expect(document.activeElement).toBe(within(entryEl(11)).getByRole('textbox', { name: 'Type delete to sign: Delete logs' }));
  });
});

describe('no key signs or rejects', () => {
  it('Enter in the signature line, and Enter, Space, a, r, d anywhere on the page, never post', async () => {
    hub.feed = feedOf([t(12, { risk_tier: 3, kind: 'restart_service', title: 'Restart it' }), t(13, { risk_tier: 0 }), t(14, { risk_tier: 1 })]);
    await mount();
    const entry = entryEl(12);
    const box = within(entry).getByRole('textbox', { name: 'Type restart to sign: Restart it' }) as HTMLInputElement;
    fireEvent.change(box, { target: { value: 'restart' } });
    box.focus();
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    box.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);           // held: it neither signs nor submits anything
    for (const target of [document, document.body, docketEl(), entry, box]) {
      for (const key of ['Enter', ' ', 'a', 'r', 'd', 'A', 'R', 'D']) {
        fireEvent.keyDown(target, { key });
        fireEvent.keyUp(target, { key });
      }
    }
    await settle();
    expect(posts()).toEqual([]);
    expect(entry.textContent).toContain('No keyboard shortcut signs or rejects');
  });
});

describe('the other verbs', () => {
  it('reject and defer in one click, each with the reason typed before the verbs', async () => {
    hub.feed = feedOf([t(15, { risk_tier: 1, title: 'Reconsider' })]);
    await mount();
    const entry = entryEl(15);
    const toggle = within(entry).getByRole('button', { name: 'Add a reason' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    const reason = within(entry).getByRole('textbox', { name: /^Your reason/ }) as HTMLTextAreaElement;
    expect(reason.maxLength).toBe(280);
    const focusable = Array.from(entry.querySelectorAll('button, textarea, input, a'));
    expect(focusable.indexOf(reason)).toBeLessThan(focusable.indexOf(within(entry).getByRole('button', { name: 'Reject' })));
    fireEvent.change(reason, { target: { value: '  Use staging  ' } });
    fireEvent.click(within(entry).getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/15/decision', body: { action: 'reject', reason: 'Use staging' } }]));
    await waitFor(() => expect((within(entryEl(15)).getByRole('button', { name: 'Defer' }) as HTMLButtonElement).disabled).toBe(false));
    const defer = within(entryEl(15)).getByRole('button', { name: 'Defer' });
    expect(defer.getAttribute('title')).toMatch(/^Leaves the docket; it does not expire/);
    fireEvent.click(defer);
    await waitFor(() => expect(posts()[1]).toEqual({ url: '/autonomy/tasks/15/decision', body: { action: 'defer', reason: 'Use staging' } }));
  });

  it('offers the real verbs, never "Dismiss"', async () => {
    hub.feed = feedOf([t(16, { risk_tier: 1 })]);
    await mount();
    const entry = entryEl(16);
    for (const name of ['Sign: Task 16', 'Preview', 'Edit, then sign', 'Defer', 'Reject']) expect(within(entry).getByRole('button', { name })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /dismiss/i })).toBeNull();
    expect(docketEl().textContent).not.toMatch(/dismiss/i);
  });

  it('rejects a hub group in two steps, sending its snapshot and members back unchanged', async () => {
    const same = (id: number) => t(id, { risk_tier: 3, kind: 'delete_file', title: 'Delete tmp' });
    const group = { id: 'grp-1', leader_id: 41, member_ids: [41, 42], count: 2, snapshot: 'q'.repeat(32) };
    hub.feed = feedOf([same(41), same(42)], [group]);
    await mount();
    const entry = entryEl(41);
    expect(entry.getAttribute('data-entry-kind')).toBe('group');
    expect(entry.textContent).toContain('Applies to request 41; 1 identical request stays waiting.');
    fireEvent.click(within(entry).getByRole('button', { name: 'Reject group' }));
    expect(posts()).toEqual([]);
    fireEvent.click(within(entry).getByRole('button', { name: 'Reject all 2' }));
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/groups/grp-1/reject',
      body: { snapshot: 'q'.repeat(32), member_ids: [41, 42] } }]));
  });

  it('rejects all N identical in two steps, one request at a time, and reports partial results', async () => {
    const same = (id: number) => t(id, { risk_tier: 3, kind: 'restart_service', agent: 'steve', title: 'Restart endpoint_test', payload: { service: 'endpoint_test' } });
    hub.feed = feedOf([same(21), same(22), same(23)]);
    hub.post = (url) => (url.includes('/22/') ? { status: 409, body: { error: 'task is not waiting' } } : { body: { ok: true } });
    await mount();
    const entry = entryEl(21);
    expect(entry.getAttribute('data-entry-kind')).toBe('identical');
    expect(within(entry).getByRole('list', { name: 'The 3 requests in this entry' }).textContent).toContain('endpoint_test');
    fireEvent.click(within(entry).getByRole('button', { name: 'Reject all 3 identical' }));
    expect(posts()).toEqual([]);
    expect(within(entry).getByRole('group', { name: 'Rejects the 3 identical requests one by one.' })).toBeTruthy();
    fireEvent.click(within(entry).getByRole('button', { name: 'Reject 3' }));
    await waitFor(() => expect(within(entryEl(21)).getByRole('alert').textContent).toBe('Rejected 2 of 3; 1 refused: task is not waiting'));
    expect(posts().map((p) => [p.url, p.body])).toEqual([21, 22, 23].map((id) => [`/autonomy/tasks/${id}/decision`, { action: 'reject' }]));
  });

  it('edits, then signs with the same friction — the edited amount, typed, for money', async () => {
    hub.feed = feedOf([t(24, { risk_tier: 3, kind: 'payment', title: 'Pay ACME', payload: { amount: 200, to: 'ACME' } })]);
    await mount();
    const entry = entryEl(24);
    expect(entry.getAttribute('data-tier')).toBe('money');
    fireEvent.click(within(entry).getByRole('button', { name: 'Edit, then sign' }));
    expect(entry.querySelectorAll('.n-signline')).toHaveLength(1);     // still the page's one signature line
    const field = within(entry).getByRole('textbox', { name: 'The request’s payload, as JSON' });
    fireEvent.change(field, { target: { value: '{not json' } });
    expect(within(entry).getByText('This is not a JSON object yet.')).toBeTruthy();
    const sign = within(entry).getByRole('button', { name: 'Save and sign: Pay ACME' }) as HTMLButtonElement;
    fireEvent.change(field, { target: { value: '{"amount": 50, "to": "ACME"}' } });
    const box = within(entry).getByRole('textbox', { name: 'Type 50 to sign: Pay ACME' });
    fireEvent.change(box, { target: { value: '200' } });
    expect(sign.disabled).toBe(true);
    fireEvent.change(box, { target: { value: '50' } });
    expect(sign.disabled).toBe(false);
    fireEvent.click(sign);
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/24/decision', body: { action: 'edit', payload: { amount: 50, to: 'ACME' } } }]));
  });

  it('opens the special kinds in Decisions instead of signing them here', async () => {
    hub.feed = feedOf([t(25, { risk_tier: 3, kind: 'settings.retention', title: 'Keep chats 30 days' })]);
    await mount();
    const entry = entryEl(25);
    expect(entry.getAttribute('data-special')).toBe('retention');
    expect(within(entry).queryByRole('button', { name: /^Sign/ })).toBeNull();
    expect(entry.querySelector('.n-signline')).toBeNull();
    expect(within(entry).getByText('This kind is decided in Decisions, where its whole card is shown.')).toBeTruthy();
    const link = within(entry).getByRole('link', { name: 'Open in Decisions: Keep chats 30 days' });
    expect(link.getAttribute('href')).toBe('/v2/console/decision-inbox?card=25');
    fireEvent.click(link);
    expect(location.pathname).toBe('/v2/console/decision-inbox');
    expect(location.search).toBe('?card=25');
  });
});

describe('after a decision', () => {
  const outcomesEl = () => docketEl().querySelector('[data-docket-outcomes]') as HTMLElement | null;

  it('reads the feed again instead of removing anything itself, and says in the register what was signed', async () => {
    let decided = false;
    hub.feed = () => ({ body: { tasks: decided ? [] : [t(26, { risk_tier: 0, title: 'Read it' })] } });
    hub.post = () => { decided = true; return { body: { ok: true } }; };
    await mount();
    fireEvent.click(within(entryEl(26)).getByRole('button', { name: 'Sign: Read it' }));
    await waitFor(() => expect(screen.getByText('Nothing is waiting for you.')).toBeTruthy());
    const feedReads = fetchMock.mock.calls.filter(([url]) => String(url) === DOCKET_FEED_PATH).length;
    expect(feedReads).toBe(2);
    const line = within(outcomesEl()!).getByRole('status');
    expect(line.textContent).toBe('Signed. Read it · request 26');
    expect(line.getAttribute('data-outcome')).toBe('done');
    expect(line.querySelector('[data-mark="seal"]')).toBeTruthy();       // signed by you: a mark and its word
  });

  it('keeps the entry and shows the hub\'s own words when it refuses', async () => {
    hub.feed = feedOf([t(27, { risk_tier: 1 })]);
    hub.post = () => ({ status: 409, body: { error: 'decision could not be applied' } });
    await mount();
    fireEvent.click(within(entryEl(27)).getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(within(entryEl(27)).getByRole('alert').textContent).toBe('Refused — decision could not be applied'));
    expect(outcomesEl()).toBeNull();                                      // drawn once: in the entry
  });

  it('a refusal arrives as a new alert (announced), not as the "Sending…" line changed in place', async () => {
    hub.feed = feedOf([t(29, { risk_tier: 1 })]);
    let answer!: () => void;
    const after = new Promise<void>((resolve) => { answer = resolve; });
    hub.post = () => ({ status: 409, body: { error: 'approval expired' }, after });
    await mount();
    fireEvent.click(within(entryEl(29)).getByRole('button', { name: 'Reject' }));
    const sending = within(entryEl(29)).getByRole('status');
    expect(sending.textContent).toBe('Sending your decision…');
    expect(entryEl(29).getAttribute('aria-busy')).toBe('true');
    await act(async () => { answer(); });
    const alert = await within(entryEl(29)).findByRole('alert');
    expect(alert.textContent).toBe('Refused — approval expired');
    expect(alert).not.toBe(sending);
    expect(sending.isConnected).toBe(false);
  });

  it('keeps a refusal in the register when the re-read removes the request (it expired): never a silent success', async () => {
    let expired = false;
    hub.feed = () => ({ body: { tasks: expired ? [t(28, { risk_tier: 0, title: 'Other' })] : [t(27, { risk_tier: 1, title: 'Move the sync' }), t(28, { risk_tier: 0, title: 'Other' })] } });
    hub.post = () => { expired = true; return { status: 409, body: { error: 'approval expired' } }; };
    await mount();
    fireEvent.click(within(entryEl(27)).getByRole('button', { name: 'Sign: Move the sync' }));
    fireEvent.click(within(entryEl(27)).getByRole('button', { name: 'Confirm signature' }));
    await waitFor(() => expect(entryEl(27)).toBeNull());
    const alert = within(outcomesEl()!).getByRole('alert');
    expect(alert.textContent).toBe('Refused — approval expired Move the sync · request 27');
    expect(alert.getAttribute('data-outcome-request')).toBe('27');
    expect(docketEl().textContent).not.toContain('Signed.');
    expect(entryEl(28).querySelector('.n-entry__outcome')).toBeNull();   // the entry that moved up carries nothing of it
  });

  const same = (id: number) => t(id, { risk_tier: 3, kind: 'restart_service', agent: 'steve', title: 'Restart endpoint_test', payload: { service: 'endpoint_test' } });

  it('Reject all N: when the re-read re-keys the collapse, the partial result stays with the request that is left', async () => {
    let posted = 0;
    hub.feed = () => ({ body: { tasks: posted >= 3 ? [same(22)] : [same(21), same(22), same(23)] } });
    hub.post = (url) => { posted += 1; return url.includes('/22/') ? { status: 409, body: { error: 'task is not waiting' } } : { body: { ok: true } }; };
    await mount();
    expect(entryEl(21).getAttribute('data-entry-kind')).toBe('identical');
    fireEvent.click(within(entryEl(21)).getByRole('button', { name: 'Reject all 3 identical' }));
    fireEvent.click(within(entryEl(21)).getByRole('button', { name: 'Reject 3' }));
    await waitFor(() => expect(entryEl(21)).toBeNull());
    expect(entryEl(22).getAttribute('data-entry-kind')).toBe('single');   // same:21 became task:22
    await waitFor(() => expect(within(entryEl(22)).getByRole('alert').textContent).toBe('Rejected 2 of 3; 1 refused: task is not waiting'));
    expect(outcomesEl()).toBeNull();
  });

  it('Reject all N: when the re-read leaves none of them, the partial result is drawn in the register', async () => {
    let posted = 0;
    hub.feed = () => ({ body: { tasks: posted >= 3 ? [] : [same(21), same(22), same(23)] } });
    hub.post = (url) => { posted += 1; return url.includes('/22/') ? { status: 409, body: { error: 'task is not waiting' } } : { body: { ok: true } }; };
    await mount();
    fireEvent.click(within(entryEl(21)).getByRole('button', { name: 'Reject all 3 identical' }));
    fireEvent.click(within(entryEl(21)).getByRole('button', { name: 'Reject 3' }));
    await waitFor(() => expect(outcomesEl()).toBeTruthy());
    expect(within(outcomesEl()!).getByRole('alert').textContent).toBe('Rejected 2 of 3; 1 refused: task is not waiting Restart endpoint_test · 3 requests');
    expect(posts().map((p) => p.url)).toEqual([21, 22, 23].map((id) => `/autonomy/tasks/${id}/decision`));
  });

  it('a hub group that promotes its next leader is drawn afresh: nothing typed, armed or written carries over', async () => {
    const del = (id: number) => t(id, { risk_tier: 3, kind: 'delete_file', title: 'Delete tmp' });
    let signed = false;
    hub.feed = () => (signed
      ? { body: { tasks: [del(42), del(43)], groups: [{ id: 'grp-1', leader_id: 42, member_ids: [42, 43], count: 2, snapshot: 'r'.repeat(32) }] } }
      : { body: { tasks: [del(41), del(42), del(43)], groups: [{ id: 'grp-1', leader_id: 41, member_ids: [41, 42, 43], count: 3, snapshot: 'q'.repeat(32) }] } });
    hub.post = () => { signed = true; return { body: { ok: true } }; };
    await mount();
    const entry = () => docketEl().querySelector('[data-entry-kind="group"]') as HTMLElement;
    fireEvent.click(within(entry()).getByRole('button', { name: 'Add a reason' }));
    fireEvent.change(within(entry()).getByRole('textbox', { name: /^Your reason/ }), { target: { value: 'tidy up' } });
    fireEvent.change(within(entry()).getByRole('textbox', { name: 'Type delete to sign: Delete tmp' }), { target: { value: 'delete' } });
    fireEvent.click(within(entry()).getByRole('button', { name: 'Sign: Delete tmp' }));
    await waitFor(() => expect(entry().getAttribute('data-docket-entry')).toBe('42'));
    expect(posts()).toEqual([{ url: '/autonomy/tasks/41/decision', body: { action: 'accept', reason: 'tidy up' } }]);
    expect(entry().getAttribute('data-entry-state')).toBe('open');                       // still the open entry
    expect((within(entry()).getByRole('textbox', { name: 'Type delete to sign: Delete tmp' }) as HTMLInputElement).value).toBe('');
    expect((within(entry()).getByRole('button', { name: 'Sign: Delete tmp' }) as HTMLButtonElement).disabled).toBe(true);
    expect((entry().querySelector('textarea') as HTMLTextAreaElement).value).toBe('');
    expect(entry().querySelector('.n-entry__outcome')).toBeNull();                       // request 41's outcome is not 42's
    expect(within(outcomesEl()!).getByRole('status').textContent).toBe('Signed. Delete tmp · request 41');
  });

  it('closing an entry ends its edit: a later Sign from the closed line signs the request as it is', async () => {
    hub.feed = feedOf([t(50, { risk_tier: 1, title: 'First', payload: { a: 1 } }), t(51, { risk_tier: 1, title: 'Second' })]);
    await mount();
    fireEvent.click(within(entryEl(50)).getByRole('button', { name: 'Edit, then sign' }));
    fireEvent.change(within(entryEl(50)).getByRole('textbox', { name: 'The request’s payload, as JSON' }), { target: { value: '{"a": 2}' } });
    fireEvent.click(within(entryEl(51)).getByRole('button', { name: 'Open: Second' }));
    expect(entryEl(50).getAttribute('data-entry-state')).toBe('closed');
    fireEvent.click(within(entryEl(50)).getByRole('button', { name: 'Sign: First' }));
    expect(entryEl(50).querySelector('[data-editor]')).toBeNull();
    fireEvent.click(within(entryEl(50)).getByRole('button', { name: 'Confirm signature' }));
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/50/decision', body: { action: 'accept' } }]));
  });
});

/* Below 1680px a closed entry's title is one line, cut with an ellipsis when it does not fit
   (docket.css; e2e/home-registers.spec.ts measures it in every look): the words cut from the
   screen stay in the button's name and its tooltip. The column heads and the rows are one table,
   so their columns line up. */
describe('a closed entry\'s title', () => {
  it('keeps every word in its button\'s name and tooltip', async () => {
    const long = 'Publish Veronica’s LinkedIn draft, which names the client and every figure from the quarterly review';
    hub.feed = feedOf([t(70, { risk_tier: 1, title: 'First' }), t(71, { risk_tier: 1, title: long })]);
    await mount();
    expect(entryEl(71).getAttribute('data-entry-state')).toBe('closed');
    const opener = within(entryEl(71)).getByRole('button', { name: `Open: ${long}` });
    expect(opener.getAttribute('title')).toBe(long);
    expect(opener.textContent).toBe(long);
    const table = docketEl().querySelector('.n-docket__table') as HTMLElement;
    expect(table.querySelector(':scope > .n-docket__cols')).not.toBeNull();
    expect(table.querySelector(':scope > ol.n-docket__list')?.contains(entryEl(71))).toBe(true);
  });
});

describe('only a fresh press decides', () => {
  it('the second click of a double-click never signs, rejects or defers — the next entry may be under the pointer', async () => {
    hub.feed = feedOf([t(60, { risk_tier: 0, title: 'Read A' }), t(61, { risk_tier: 0, title: 'Read B' })]);
    await mount();
    fireEvent.click(within(entryEl(60)).getByRole('button', { name: 'Sign: Read A' }), { detail: 2 });
    fireEvent.click(within(entryEl(61)).getByRole('button', { name: 'Sign: Read B' }), { detail: 2 });
    fireEvent.click(within(entryEl(60)).getByRole('button', { name: 'Reject' }), { detail: 2 });
    fireEvent.click(within(entryEl(60)).getByRole('button', { name: 'Defer' }), { detail: 3 });
    await settle();
    expect(posts()).toEqual([]);
    fireEvent.click(within(entryEl(61)).getByRole('button', { name: 'Sign: Read B' }), { detail: 1 });
    await waitFor(() => expect(posts()).toEqual([{ url: '/autonomy/tasks/61/decision', body: { action: 'accept' } }]));
  });

  it('holding Enter on a two-step Sign arms it but never confirms it', async () => {
    hub.feed = feedOf([t(7, { risk_tier: 3 }), t(62, { risk_tier: 1, title: 'Move it' })]);
    await mount();
    fireEvent.click(within(entryEl(62)).getByRole('button', { name: 'Sign: Move it' }));     // the closed line's Sign
    const confirm = within(entryEl(62)).getByRole('button', { name: 'Confirm signature' });
    expect(document.activeElement).toBe(confirm);
    const held = new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true });
    confirm.dispatchEvent(held);
    expect(held.defaultPrevented).toBe(true);                                // the repeat does not press it
    await settle();
    expect(posts()).toEqual([]);
  });
});

describe('the foot', () => {
  it('off a live reading, says the counts are the last good reading\'s', async () => {
    hub.feed = feedOf([t(4, { risk_tier: 0 })]);
    await mount();
    expect(docketEl().querySelector('.n-docket__total')?.textContent).not.toContain('Last good reading');
    hub.feed = () => ({ fail: true });
    await act(async () => { await refreshPolled(DOCKET_FEED_PATH, { admin: true }); });
    const total = docketEl().querySelector('.n-docket__total') as HTMLElement;
    expect(total.className).toContain('n-docket__total--stale');
    expect(total.textContent).toMatch(/^Last good reading \d\d:\d\d · 1 entry · 1 request/);
    expect(total.querySelector('[data-mark="stale"]')).toBeTruthy();
  });

  it('counts the kinds that open in Decisions apart from the signing mix', async () => {
    hub.feed = feedOf([t(70, { risk_tier: 3, kind: 'settings.retention' }), t(71, { risk_tier: 1 })]);
    await mount();
    const total = docketEl().querySelector('.n-docket__total') as HTMLElement;
    expect(total.textContent).toContain('2 entries · 2 requests');
    expect(total.textContent).toContain('0 typed');
    expect(total.textContent).toContain('1 two-step');
    expect(total.textContent).toContain('1 in Decisions');
  });

  it('empty while something waits elsewhere: nothing waits here, not "nothing is waiting"', async () => {
    hub.payments = () => ({ body: { payments: [{ id: 'p1', status: 'pending' }] } });
    await mount();
    await waitFor(() => expect(docketEl().querySelector('[data-docket-other]')).toBeTruthy());
    expect(docketEl().querySelector('[data-docket-state="empty"]')?.textContent).toBe('Nothing here awaits your signature.');
    expect(docketEl().textContent).not.toContain('Nothing is waiting for you.');
  });
});

describe('what an entry says', () => {
  it('previews the open entry by itself and says what signing would run', async () => {
    hub.preview = () => ({ body: { effects: [{ field: 'cmd', value: 'lms server restart' }, { field: 'service', value: 'lmstudio' }], would_execute: false } });
    hub.feed = feedOf([t(30, { risk_tier: 3, kind: 'restart_service' }), t(31, { risk_tier: 1 })]);
    await mount();
    await waitFor(() => expect(entryEl(30).textContent).toContain('Would run: lms server restart'));
    expect(entryEl(30).textContent).toContain('The dry run reports: service lmstudio');
    expect(entryEl(30).textContent).toContain('When you sign, it is queued for the worker.');
    const previews = () => fetchMock.mock.calls.filter(([url]) => String(url).startsWith('/api/autonomy/tasks/')).map(([url]) => String(url));
    expect(previews()).toEqual(['/api/autonomy/tasks/30/preview']);     // the closed entry waits to be asked
  });

  it('draws an optional row only when the hub sent its field', async () => {
    hub.feed = feedOf([t(32, { risk_tier: 3, kind: 'k', title: 'Bare' })]);
    await mount();
    const terms = () => Array.from(entryEl(32).querySelectorAll('dt')).map((dt) => dt.textContent);
    expect(terms()).toEqual(['If you sign', 'To undo', 'If you wait']);
    expect(entryEl(32).textContent).toContain('Not reported by the hub.');
    expect(entryEl(32).textContent).toContain('Nothing runs. It stays here until you decide.');
    expect(entryEl(32).querySelector('.n-entry__why')).toBeNull();
  });

  it('writes every row the hub sent', async () => {
    hub.feed = feedOf([t(33, {
      risk_tier: 3, kind: 'toolrpc.terminal_run', title: 'Run a script', agent: 'steve',
      approval_mode: { effective: 'ask', source: 'global', global: 'ask' }, asked_under: { mode: 'ask', source: 'global', global: 'ask', by_mode: true },
      delegated_by: { spawn_id: 'sp-1', parent: 'pepper', label: 'model-written goal' }, pushed: 0,
      rollback: { description: 'Revert the commit.', limitations: 'Pushed history stays.' },
      approval_deadline_at: new Date(Date.now() + 3_600_000).toISOString(),
      payload: { injection_flags: ['prompt_injection'] },
      judge: { advisory: true, score: 72, judge: { provider: 'ollama', model: 'qwen3', local: true } },
    })]);
    await mount();
    const entry = entryEl(33);
    expect(Array.from(entry.querySelectorAll('dt')).map((dt) => dt.textContent)).toEqual(['If you sign', 'To undo', 'If you wait', 'Caution', 'Opinion']);
    const text = entry.textContent;
    expect(text).toContain('Held because the approval mode was Ask when this was queued: anything with a side effect waits for you.');
    expect(text).toContain('Not sent to your phone.');
    expect(text).toContain('asked by a sub-agent of Pepper');
    expect(text).not.toContain('model-written goal');
    expect(text).toContain('Steve');
    expect(text).toContain('CTO / Builds');
    expect(text).toContain('Revert the commit.');
    expect(text).toContain('Pushed history stays.');
    expect(text).toMatch(/Expires unanswered at (?:\d{1,2} \w+(?: \d{4})?, )?\d\d:\d\d\./);   // an hour on can be tomorrow, or next year
    expect(text).toContain('Raised from untrusted content.');
    expect(text).toContain('Model opinion · advisory only · you decide · 72/100 · ollama/qwen3 · local');
    expect(text).toContain('Your approval is recorded, but this kind runs only in Auto mode (now Ask).');
  });

  it('draws titles as plain text', async () => {
    const title = '<img src=x onerror=alert(1)> **bold** [x](javascript:alert(1))';
    hub.feed = feedOf([t(34, { risk_tier: 1, title })]);
    await mount();
    expect(entryEl(34).querySelector('h3')?.textContent).toBe(title);
    expect(docketEl().querySelector('img, strong, a[href^="javascript"]')).toBeNull();
  });

  it('lists what waits elsewhere, counts only when their feeds are live', async () => {
    hub.feed = feedOf([t(35, { risk_tier: 1 })]);
    hub.payments = () => ({ body: { payments: [{ id: 'p1', status: 'pending' }, { id: 'p2', status: 'settled' }] } });
    hub.skills = () => ({ body: { proposals: [{}], count: 1, more: 2 } });
    const navigate = await mount();
    await waitFor(() => expect(docketEl().querySelector('[data-docket-other]')?.textContent)
      .toBe('Other things waiting: 1 payment — Trust › Payments · 3 skill changes — Work › Decisions'));
    fireEvent.click(within(docketEl().querySelector('[data-docket-other]') as HTMLElement).getByRole('link', { name: 'Trust › Payments' }));
    expect(navigate).toHaveBeenCalledWith('/v2/console/payments');
  });

  it('says nothing about elsewhere when those feeds are refused', async () => {
    hub.feed = feedOf([t(36, { risk_tier: 1 })]);
    hub.payments = () => ({ status: 401, body: {} });
    hub.skills = () => ({ status: 503, body: {} });
    await mount();
    await settle();
    expect(docketEl().querySelector('[data-docket-other]')).toBeNull();
  });

  it('speaks Romanian', async () => {
    hub.feed = feedOf([t(37, { risk_tier: 3, kind: 'restart_service', title: 'Repornește lmstudio' })]);
    await mount({ lang: 'ro' });
    expect(docketEl().querySelector('h2')?.textContent).toBe('1 așteaptă semnătura ta');
    expect(Array.from(entryEl(37).querySelectorAll('dt')).map((dt) => dt.textContent)).toEqual(['Dacă semnezi', 'Ca să anulezi', 'Dacă aștepți']);
    expect(within(entryEl(37)).getByRole('textbox', { name: 'Scrie restart ca să semnezi: Repornește lmstudio' })).toBeTruthy();
  });
});

describe('a link to an entry', () => {
  it('opens the entry holding the request — a group member included — and says when one is not on the docket', async () => {
    history.replaceState(null, '', '/v2/cockpit#docket-entry-42');
    const same = (id: number) => t(id, { risk_tier: 1, kind: 'note.write', title: 'Write it' });
    hub.feed = feedOf([t(5, { risk_tier: 3 }), same(41), same(42)],
      [{ id: 'g', leader_id: 41, member_ids: [41, 42], count: 2, snapshot: 'z'.repeat(32) }]);
    await mount();
    await waitFor(() => expect(entryEl(41).getAttribute('data-entry-state')).toBe('open'));
    expect(entryEl(5).getAttribute('data-entry-state')).toBe('closed');
    expect(document.activeElement).toBe(entryEl(41).querySelector('h3'));
    act(() => openDocketEntry(99));
    await waitFor(() => expect(docketEl().querySelector('[data-docket-state="not-on-docket"]')?.textContent)
      .toContain('Request 99 is not on the docket: it may be decided already.'));
    expect(within(docketEl()).getByRole('link', { name: 'Open it in Decisions' }).getAttribute('href')).toBe('/v2/console/decision-inbox?card=99');
  });
});

describe('DocketLine (the floating window)', () => {
  it('says how many await a signature, and that signing happens in the main window', async () => {
    hub.feed = feedOf([t(1), t(2, { risk_tier: 3 })]);
    render(<DocketLine lang="en" demo={false} />);
    await waitFor(() => expect(document.querySelector('[data-docket-line]')?.textContent).toBe('2 await your signature — sign in the main window'));
    expect(screen.queryByRole('button', { name: 'Open in app' })).toBeNull();
    expect(document.querySelector('[data-docket-line] input, [data-docket-line] [data-verb]')).toBeNull();
  });

  it('repeats "Open in app" only when given the handoff', async () => {
    hub.feed = feedOf([t(1)]);
    const open = vi.fn();
    render(<DocketLine lang="en" demo={false} onOpenInApp={open} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Open in app' }));
    expect(open).toHaveBeenCalledTimes(1);
  });

  it('is not drawn while checking or when nothing waits, and says unknown — not "nothing" — when refused', async () => {
    hub.feed = () => ({ hang: true });
    const { unmount } = render(<DocketLine lang="en" demo={false} />);
    expect(document.querySelector('[data-docket-line]')).toBeNull();
    unmount();
    resetPolling();
    hub.feed = feedOf([]);
    const second = render(<DocketLine lang="en" demo={false} />);
    await settle();
    expect(document.querySelector('[data-docket-line]')).toBeNull();
    second.unmount();
    resetPolling();
    hub.feed = () => ({ status: 401, body: {} });
    render(<DocketLine lang="en" demo={false} />);
    await waitFor(() => expect(document.querySelector('[data-docket-line]')?.textContent)
      .toBe('Docket: unknown — needs the owner credential'));
  });

  it('after an empty answer, a failed read is unknown — never the "nothing waits" of before', async () => {
    hub.feed = feedOf([]);
    render(<DocketLine lang="en" demo={false} />);
    await settle();
    expect(document.querySelector('[data-docket-line]')).toBeNull();
    hub.feed = () => ({ fail: true });
    await act(async () => { await refreshPolled(DOCKET_FEED_PATH, { admin: true }); });
    const line = document.querySelector('[data-docket-line]') as HTMLElement;
    expect(line.getAttribute('data-docket-line')).toBe('offline');
    expect(line.textContent).toBe('Docket: unknown — no answer');
    hub.feed = () => ({ status: 500, body: {} });
    await act(async () => { await refreshPolled(DOCKET_FEED_PATH, { admin: true }); });
    expect(document.querySelector('[data-docket-line]')?.textContent).toBe('Docket: unknown — the hub answered 500');
    hub.feed = feedOf([]);
    await act(async () => { await refreshPolled(DOCKET_FEED_PATH, { admin: true }); });
    expect(document.querySelector('[data-docket-line]')).toBeNull();          // answered again: nothing waits
  });

  it('after an empty answer gone stale, says stale and when it was last checked', async () => {
    vi.useFakeTimers();
    hub.feed = feedOf([]);
    render(<DocketLine lang="en" demo={false} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(document.querySelector('[data-docket-line]')).toBeNull();
    visibility = 'hidden';                               // answers stop arriving (polling pauses)
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await act(async () => { await vi.advanceTimersByTimeAsync(80_000); });
    const line = document.querySelector('[data-docket-line]') as HTMLElement;
    expect(line.getAttribute('data-docket-line')).toBe('stale');
    expect(line.textContent).toMatch(/^Docket: stale — last checked \d\d:\d\d$/);
    expect(line.querySelector('[data-mark="stale"]')).toBeTruthy();
  });
});
