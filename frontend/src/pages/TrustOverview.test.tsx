// @ts-nocheck
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', async (orig) => ({ ...(await orig()), apiGet: vi.fn() }));
vi.mock('../api/actions', async (orig) => ({ ...(await orig()), setKillSwitch: vi.fn().mockResolvedValue({}), decidePayment: vi.fn().mockResolvedValue({}) }));
const kill = { state: 'live', value: { halted: false }, checkedAt: 1, lastGoodAt: Date.now(), stop: vi.fn(), refresh: vi.fn() };
vi.mock('../frame/useKillSwitch', () => ({ useKillSwitch: () => kill }));

import { apiGet } from '../api/client';
import { decidePayment, setKillSwitch } from '../api/actions';
import { resetPolling } from '../signals/poll';
import { TrustOverview } from './TrustOverview';
import { hubFixture, httpError, routeGet, secondsAgo } from './testkit';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const navigate = vi.fn();
const entry = (seq: number, over = {}) => ({ seq, ts: secondsAgo(seq), actor: 'jarvis', action: 'route', why: `Routed question ${seq}`, cause: '', metadata: {}, entry_hash: `abcd${seq}000000000000ef${seq}`, prev_hash: '', signature: 's', ...over });
const payment = (over = {}) => ({ id: 'p1', mandate_id: 'm1', payee: 'Gecko', amount: 4200, currency: 'EUR', memo: 'Savings ladder sweep', status: 'pending', created_at: Date.now() / 1000, ...over });

function routes(over = {}) {
  routeGet(get, {
    '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 921, tamper_evident: true },
    '/api/security/audit/intent': { verify: { ok: true, bad_seq: null, n: 3 }, entries: [entry(3), entry(2), entry(1)] },
    '/api/payments': { payments: [payment()] },
    '/autonomy/mode': { mode: 'ask' },
    '/autonomy/tasks?status=running': { tasks: [] },
    '/api/subagents': { spawns: [], stats: { active: 0, cap: 3 } },
    ...over,
  });
}
const ui = (props = {}) => <TrustOverview hub={hubFixture()} lang="en" demo={false} navigate={navigate} {...props} />;

beforeEach(() => {
  resetPolling();
  get.mockReset(); navigate.mockReset();
  setKillSwitch.mockClear(); decidePayment.mockClear(); kill.stop.mockReset(); kill.refresh.mockReset();
  kill.state = 'live'; kill.value = { halted: false };
  kill.stop.mockResolvedValue({ ok: true });
  kill.refresh.mockResolvedValue(undefined);
});
afterEach(() => { resetPolling(); cleanup(); });

describe('Trust overview: the chain\'s verdict', () => {
  it('says intact only after the chain was verified, with the count and the time', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Chain intact: 921 sealed entries' })).toBeTruthy());
    const verdict = document.querySelector('[data-chain-state]');
    expect(verdict.getAttribute('data-chain-state')).toBe('intact');
    expect(verdict.textContent).toMatch(/Intact · verified \d\d:\d\d/);
    expect(verdict.textContent).toContain('Keyed: an edit cannot be recomputed');
  });

  it('says an unkeyed chain proves integrity only', async () => {
    routes({ '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 5, tamper_evident: false } });
    render(ui());
    await waitFor(() => expect(screen.getByText(/Unkeyed: this proves integrity only/)).toBeTruthy());
  });

  it('says broken, and where, when the chain does not verify', async () => {
    routes({ '/api/security/audit/verify': { valid: false, first_invalid_id: 17, entries: 30 } });
    render(ui());
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Chain broken at entry 17' })).toBeTruthy());
    expect(document.querySelector('[data-chain-state]').getAttribute('data-chain-state')).toBe('broken');
    expect(screen.queryByText(/Intact/)).toBeNull();
  });

  it('never says intact while the chain is unverified: checking, offline and refused', async () => {
    routes({ '/api/security/audit/verify': new TypeError('Failed to fetch') });
    const first = render(ui());
    expect(screen.getByRole('heading', { name: 'The chain has not been verified' })).toBeTruthy();
    await waitFor(() => expect(first.container.querySelector('[data-reading-state="offline"]')).not.toBeNull());
    expect(screen.queryByText(/intact/i)).toBeNull();
    first.unmount();
    resetPolling();
    routes({ '/api/security/audit/verify': httpError(401) });
    render(ui());
    await waitFor(() => expect(document.querySelector('[data-reading-state="refused"]')).not.toBeNull());
    expect(screen.getByRole('heading', { name: 'The chain has not been verified' })).toBeTruthy();
    expect(screen.queryByText(/intact/i)).toBeNull();
  });

  it('verifies again by reading, never by writing', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(screen.getByRole('heading', { name: /Chain intact/ })).toBeTruthy());
    const before = get.mock.calls.filter(([p]) => p === '/api/security/audit/verify').length;
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Verify again' })); });
    await waitFor(() => expect(get.mock.calls.filter(([p]) => p === '/api/security/audit/verify').length).toBeGreaterThan(before));
    expect(setKillSwitch).not.toHaveBeenCalled();
    expect(decidePayment).not.toHaveBeenCalled();
    expect(screen.getByText('verifying is read only')).toBeTruthy();
  });

  it('is a demo sample in demo: no chain claim, verify off, no request', async () => {
    routes();
    render(ui({ demo: true }));
    expect(screen.getByRole('heading', { name: 'A demo sample: this is not a real chain' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Verify again' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByText(/Intact/)).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});

describe('Trust overview: the record table', () => {
  it('draws the entries the hub sent as plain text, the seal only because the chain verified', async () => {
    routes({ '/api/security/audit/intent': { verify: { ok: true, bad_seq: null, n: 2 }, entries: [entry(2, { why: '<b>bold</b> **x**' }), entry(1)] } });
    render(ui());
    const table = await screen.findByRole('table', { name: 'Recent entries in the audit chain' });
    expect(within(table).getByText('<b>bold</b> **x**')).toBeTruthy();
    expect(table.querySelector('.n-record__what b')).toBeNull();
    expect(within(table).getAllByRole('img', { name: 'Sealed' }).length).toBe(2);
    expect(within(table).queryByRole('columnheader', { name: 'Risk' })).toBeNull();
  });

  it('shows a problem, not a seal, when the log says the chain failed', async () => {
    routes({ '/api/security/audit/intent': { verify: { ok: false, bad_seq: 1, n: 1 }, entries: [entry(1)] } });
    render(ui());
    const table = await screen.findByRole('table');
    expect(within(table).queryByRole('img', { name: 'Sealed' })).toBeNull();
    expect(within(table).getByText('Seal broken')).toBeTruthy();
  });

  it('adds a risk column only when entries carry a tier', async () => {
    routes({ '/api/security/audit/intent': { verify: { ok: true, n: 1 }, entries: [entry(1, { metadata: { risk_tier: 3 } })] } });
    render(ui());
    const table = await screen.findByRole('table');
    expect(within(table).getByRole('columnheader', { name: 'Risk' })).toBeTruthy();
    expect(table.querySelector('[data-tier]')).not.toBeNull();
  });

  it('says what a refused record means instead of drawing an empty table', async () => {
    routes({ '/api/security/audit/intent': httpError(401) });
    render(ui());
    await waitFor(() => expect(document.querySelectorAll('[data-reading-state="refused"]').length).toBeGreaterThan(0));
    expect(screen.queryByRole('table', { name: 'Recent entries in the audit chain' })).toBeNull();
  });
});

describe('Trust overview: payments wait for the owner', () => {
  it('approves a payment only by typing its amount', async () => {
    routes();
    render(ui());
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    const field = screen.getByLabelText(/Type 4200 to approve the payment of 4200 to Gecko/);
    const confirm = screen.getByRole('button', { name: 'Approve payment' });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(field, { target: { value: '420' } });
    expect(confirm.disabled).toBe(true);
    fireEvent.keyDown(field, { key: 'Enter' });
    fireEvent.change(field, { target: { value: '4200' } });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(decidePayment).not.toHaveBeenCalled();
    expect(confirm.disabled).toBe(false);
    await act(async () => { fireEvent.click(confirm); });
    expect(decidePayment).toHaveBeenCalledWith('p1', 'approve');
  });

  it('rejects in one click, and Escape cancels an armed approval', async () => {
    routes();
    render(ui());
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    fireEvent.keyDown(screen.getByLabelText(/Type 4200/), { key: 'Escape' });
    expect(screen.queryByLabelText(/Type 4200/)).toBeNull();
    expect(decidePayment).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Reject' })); });
    expect(decidePayment).toHaveBeenCalledWith('p1', 'reject');
  });

  it('settles an approved payment in two steps', async () => {
    routes({ '/api/payments': { payments: [payment({ status: 'approved' })] } });
    render(ui());
    fireEvent.click(await screen.findByRole('button', { name: 'Settle' }));
    expect(decidePayment).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Settle payment' })); });
    expect(decidePayment).toHaveBeenCalledWith('p1', 'settle');
  });

  it('never settles from one gesture: a double-click\'s second click or a held key does not confirm', async () => {
    routes({ '/api/payments': { payments: [payment({ status: 'approved' })] } });
    render(ui());
    fireEvent.click(await screen.findByRole('button', { name: 'Settle' }), { detail: 1 });
    const confirm = screen.getByRole('button', { name: 'Settle payment' });
    // the double-click's second click lands on the button the first one put there
    await act(async () => { fireEvent.click(confirm, { detail: 2 }); });
    // a held Enter's auto-repeat: its default (the click) is held back
    const repeat = new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true });
    confirm.dispatchEvent(repeat);
    expect(repeat.defaultPrevented).toBe(true);
    expect(decidePayment).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(confirm, { detail: 1 }); });
    expect(decidePayment).toHaveBeenCalledWith('p1', 'settle');
  });

  it('says so, and stays armed, when the hub refuses the decision', async () => {
    routes();
    decidePayment.mockRejectedValueOnce(Object.assign(new Error('POST /api/payments/p1/approve -> 400'), { status: 400, body: { error: 'payment not found or not pending' } }));
    render(ui());
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    fireEvent.change(screen.getByLabelText(/Type 4200/), { target: { value: '4200' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Approve payment' })); });
    expect((await screen.findAllByRole('alert')).map((n) => n.textContent).join(' ')).toMatch(/The hub refused: payment not found or not pending/);
    expect(screen.getByLabelText(/Type 4200/)).toBeTruthy();
    expect(document.body.textContent).not.toContain('POST /api');
  });

  it('does not say a payment was unchanged when the hub never answered', async () => {
    routes();
    decidePayment.mockRejectedValueOnce(new Error('Failed to fetch'));
    render(ui());
    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    fireEvent.change(screen.getByLabelText(/Type 4200/), { target: { value: '4200' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Approve payment' })); });
    expect((await screen.findAllByRole('alert')).map((n) => n.textContent).join(' ')).toMatch(/did not answer. The payment may or may not have changed/);
  });

  it('offers no approve when the amount was not reported, and none for a payment that is not waiting', async () => {
    routes({ '/api/payments': { payments: [payment({ amount: null }), payment({ id: 'p2', status: 'rejected' })] } });
    render(ui());
    await screen.findByText('Rejected');
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull();
    expect(screen.getAllByText('Amount not reported').length).toBeGreaterThan(0);
  });

  it('is refused, not "no payments", without the owner credential', async () => {
    routes({ '/api/payments': httpError(401) });
    render(ui());
    await waitFor(() => expect(document.querySelectorAll('[data-source-state="refused"]').length).toBeGreaterThan(0));
    expect(screen.queryByText('No payments.')).toBeNull();
  });

  it('disables every decision in demo', async () => {
    routes();
    render(ui({ demo: true }));
    const pay = document.querySelector('[data-payment-state="pending"]');
    expect(pay).not.toBeNull();
    for (const b of within(pay).getAllByRole('button')) expect(b.disabled).toBe(true);
    // the stop is not a decision on a request: it acts on the real hub and stopping is the safe
    // direction (§4.1), so it stays live in demo, as the masthead's and Glance's do
    expect(within(document.querySelector('#stop')).getByRole('button', { name: 'Stop all agents' }).disabled).toBe(false);
    expect(screen.getAllByText(/Demo sample/).length).toBeGreaterThan(0);
  });

  it('keeps the typed resume off in demo', async () => {
    routes();
    kill.value = { halted: true };
    render(ui({ demo: true }));
    expect(screen.getByRole('button', { name: 'Resume' }).disabled).toBe(true);
  });

  it('says an agent-scoped halt while the global stop is armed, and Stop still halts everything', async () => {
    routes();
    kill.value = { halted: false, scoped: 2 };
    render(ui());
    expect(document.querySelector('#stop').getAttribute('data-stop-state')).toBe('armed');
    expect(screen.getByText('2 agent-scoped halts are in force; the global stop is armed and halts everything.')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Stop all agents' })); });
    expect(kill.stop).toHaveBeenCalledTimes(1);
  });
});

describe('Trust overview: the owner\'s stop', () => {
  it('stops in one click, with no confirmation, and reports a refusal', async () => {
    routes();
    kill.stop.mockResolvedValueOnce({ ok: false, reason: 'owner credential required' });
    render(ui());
    expect(screen.getByText('Armed')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Stop all agents' })); });
    expect(kill.stop).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/The stop was not confirmed: owner credential required/)).toBeTruthy();
  });

  it('resumes only by typing DISENGAGE, and never from a key', async () => {
    routes();
    kill.value = { halted: true };
    render(ui());
    expect(screen.getByText('Halted')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Stop all agents' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    const field = screen.getByLabelText('Type DISENGAGE to resume the agents');
    const confirm = screen.getByRole('button', { name: 'Resume all agents' });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(field, { target: { value: 'disengage' } });
    expect(confirm.disabled).toBe(true);
    fireEvent.change(field, { target: { value: 'DISENGAGE' } });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(setKillSwitch).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(confirm); });
    expect(setKillSwitch).toHaveBeenCalledWith(false);
    expect(kill.refresh).toHaveBeenCalled();
  });

  it('says a resume the hub refused, and one it never answered, as what they are', async () => {
    routes();
    kill.value = { halted: true };
    setKillSwitch.mockRejectedValueOnce(Object.assign(new Error('POST /autonomy/estop/resume -> 403'), { status: 403, body: { detail: 'owner credential required' } }));
    render(ui());
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }));
    fireEvent.change(screen.getByLabelText('Type DISENGAGE to resume the agents'), { target: { value: 'DISENGAGE' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Resume all agents' })); });
    expect(await screen.findByText(/The hub refused: owner credential required/)).toBeTruthy();
    setKillSwitch.mockRejectedValueOnce(new Error('Failed to fetch'));
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Resume all agents' })); });
    expect(await screen.findByText(/did not answer. It may or may not have resumed/)).toBeTruthy();
  });

  it('offers the stop and no resume when the stop\'s state is unknown', async () => {
    routes();
    kill.state = 'unknown'; kill.value = null;
    render(ui());
    expect(document.querySelector('#stop').getAttribute('data-stop-state')).toBe('unknown');
    expect((screen.getByRole('button', { name: 'Stop all agents' }) as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByRole('button', { name: 'Resume' })).toBeNull();
  });

  it('names who would halt only from sources that answered', async () => {
    routes({ '/autonomy/tasks?status=running': { tasks: [{ id: 5, title: 'Index', agent: 'stark', risk_tier: 0, status: 'running', updated_at: new Date().toISOString() }] } });
    render(ui());
    await waitFor(() => expect(screen.getByText(/Stark, who are working, and the job queue\./)).toBeTruthy());
    cleanup(); resetPolling();
    routes({ '/autonomy/tasks?status=running': httpError(401) });
    render(ui());
    await waitFor(() => expect(get.mock.calls.some(([path]) => String(path).startsWith('/autonomy/tasks?status=running'))).toBe(true));
    await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
    expect(screen.queryByText('Would halt now')).toBeNull();
    expect(screen.queryByText(/No agent is working now/)).toBeNull();
  });
});

describe('Trust overview: capabilities and where work ran', () => {
  it('draws no seeded capability outside demo, and says the grants are not reported', async () => {
    routes();
    render(ui());
    expect(screen.queryByText('fs.read')).toBeNull();
    expect(screen.queryByText('payments.execute')).toBeNull();
    expect(document.querySelector('[data-caps="not-reported"]')).not.toBeNull();
    fireEvent.click(screen.getByRole('link', { name: 'Open Capabilities' }));
    expect(navigate).toHaveBeenCalledWith('/v2/console/capabilities');
  });

  it('draws the seeded list in demo, labelled', () => {
    routes();
    render(ui({ demo: true }));
    expect(screen.getByText('fs.read')).toBeTruthy();
    const caps = document.querySelector('#caps');
    expect(within(caps).getByText(/Demo sample/)).toBeTruthy();
  });

  it('counts the runs with their basis and never draws a percentage', () => {
    routes();
    const hub = hubFixture({ locality: { local_pct: 95, local: 115, cloud: 6, unknown: 0, total: 121 } });
    render(ui({ hub }));
    const where = document.querySelector('#where');
    expect(within(where).getByText('115 of 121 runs')).toBeTruthy();
    expect(where.textContent).toContain('sent to local runners');
    expect(where.textContent).toContain('by route');
    expect(where.textContent).not.toMatch(/\d\s?%/);
    const ladder = within(where).getByRole('list', { name: 'How the figure is known' });
    expect(within(ladder).getByText('By route').getAttribute('aria-current')).toBe('true');
    expect(within(ladder).getByText(/Verified/).className).toContain('is-later');
    expect(within(ladder).getByText(/not available yet/)).toBeTruthy();
    expect(within(where).getByRole('img').getAttribute('aria-label')).toBe('115 local, 6 cloud, 0 not classified');
  });

  it('does not call the last good figure live while the hub is offline, nor mark By route current', () => {
    routes();
    const hub = hubFixture({ state: 'offline', locality: { local_pct: 95, local: 115, cloud: 6, unknown: 0, total: 121 }, lastGoodAt: Date.now() - 10 * 60_000 });
    render(ui({ hub }));
    const where = document.querySelector('#where');
    expect(where.textContent).toContain('115 of 121 runs');
    expect(where.textContent).toMatch(/Offline/);
    expect(where.textContent).not.toMatch(/Live/);
    const ladder = within(where).getByRole('list', { name: 'How the figure is known' });
    expect(within(ladder).getByText('By route').getAttribute('aria-current')).toBeNull();
    expect(within(ladder).getByText('Unknown', { selector: 'li' }).getAttribute('aria-current')).toBe('true');
  });

  it('is unknown, on the ladder\'s first rung, when the hub did not report it', () => {
    routes();
    render(ui({ hub: hubFixture({ locality: null }) }));
    const where = document.querySelector('#where');
    expect(where.textContent).toContain('Where work ran is unknown');
    expect(within(where).getByText('Unknown', { selector: 'li' }).getAttribute('aria-current')).toBe('true');
    expect(where.textContent).not.toMatch(/of \d+ runs/);
  });

  it('says egress as a setting, and names the local-only and cloud-only agents', () => {
    routes();
    const hub = hubFixture({ trust: { mic: 'on', strictLocal: true, cloudAvailable: false, claudeAvailable: false } });
    render(ui({ hub }));
    const where = document.querySelector('#where');
    expect(where.textContent).toContain('No cloud model configured');
    expect(where.textContent).toContain('declared, not measured');
    expect(where.textContent).toContain('Frigga · Ultron · Howard');
    expect(where.textContent).toContain('Athena — unavailable while no cloud model is configured');
    expect(where.textContent).not.toMatch(/sealed/i);
  });

  it('leaves egress unreported when the trust answer is missing', () => {
    routes();
    render(ui({ hub: hubFixture({ trust: null }) }));
    expect(document.querySelector('#where').textContent).toContain('Not reported');
  });

  it('speaks Romanian with the diacritics', async () => {
    routes();
    render(ui({ lang: 'ro' }));
    expect(await screen.findByRole('heading', { name: 'Autoritatea ta' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Oprește toți agenții' })).toBeTruthy();
  });
});
