/* The approval slip (PHASE_B_PLAN.md §5.3, §2.3): "⊛ N action(s) wait for your decision", each
   request linked to its docket entry (title verbatim, plain text) or, when the docket does not hold
   it or did not answer, to the Decisions page on that card. Links navigate in the app; nothing here
   decides. TurnApprovals (turn-tools.tsx) is the slip under the Ledger and keeps its classic note. */
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Reading } from '../../signals/types';

const titles = vi.hoisted(() => new Map<number, unknown>());
const opened = vi.hoisted(() => ({ docket: [] as unknown[], decisions: [] as unknown[] }));
vi.mock('../../docket/links', async (importOriginal) => {
  const real: any = await importOriginal();
  return {
    ...real,
    useDocketTitle: (id: number) => titles.get(id) ?? { state: 'unknown', value: null, checkedAt: null, lastGoodAt: null, reason: 'checking' },
    openDocketEntry: (id: unknown) => { opened.docket.push(id); },
    openDecisionsCard: (id: unknown) => { opened.decisions.push(id); },
  };
});

import { ApprovalSlip } from './ApprovalSlip';
import { TurnApprovals } from '../../turn-tools';

const reading = (state: Reading<string>['state'], value: string | null = null): Reading<string> =>
  ({ state, value, checkedAt: 1, lastGoodAt: value ? 1 : null });

beforeEach(() => { titles.clear(); opened.docket.length = 0; opened.decisions.length = 0; history.replaceState(null, '', '/v2/cockpit?frame=ledger'); });
afterEach(() => { cleanup(); });

describe('the slip', () => {
  it('links a request the docket holds to its entry, with the title as plain text', () => {
    titles.set(17, reading('live', 'Sweep €4,200 <b>to</b> the savings ladder'));
    render(<ApprovalSlip ids={[17]} lang="en" />);
    const slip = screen.getByRole('note');
    expect(slip.querySelector('.n-slip__head')?.textContent).toBe('1 action waits for your decision');
    expect(slip.querySelector('[data-mark="seal-open"]')).toBeTruthy();
    const row = slip.querySelector('[data-slip-entry="17"]') as HTMLElement;
    expect(row.querySelector('.n-slip__title')?.textContent).toBe('Sweep €4,200 <b>to</b> the savings ladder');
    expect(row.querySelector('b')).toBeNull();
    const link = within(row).getByRole('link', { name: 'On the docket' });
    expect(link.getAttribute('href')).toBe('/v2/cockpit?frame=ledger#docket-entry-17');
    expect(fireEvent.click(link)).toBe(false);   // prevented: the app navigates
    expect(opened.docket).toEqual([17]);
    expect(within(slip).queryAllByRole('button')).toEqual([]);   // it links; it never decides
  });

  it('sends a request the docket does not hold, or could not read, to the Decisions page', () => {
    titles.set(18, reading('empty'));
    titles.set(19, { ...reading('refused'), reason: 'credential' });
    titles.set(21, { ...reading('offline'), reason: 'network' });
    render(<ApprovalSlip ids={[18, 19, 20, 21]} lang="en" />);
    const slip = screen.getByRole('note');
    expect(slip.querySelector('.n-slip__head')?.textContent).toBe('4 actions wait for your decision');
    const rows = Array.from(slip.querySelectorAll('[data-slip-entry]')) as HTMLElement[];
    expect(rows.map((row) => row.textContent)).toEqual([
      'Request 18not on the docketOpen in Decisions',
      'Request 19the docket needs the owner credentialOpen in Decisions',
      'Request 20checking the docket…Open in Decisions',
      'Request 21the docket did not answerOpen in Decisions',
    ]);
    const link = within(rows[0]).getByRole('link', { name: 'Open in Decisions' });
    expect(link.getAttribute('href')).toBe('/v2/console/decision-inbox?frame=ledger&card=18');
    fireEvent.click(link);
    expect(opened.decisions).toEqual([18]);
    expect(opened.docket).toEqual([]);
  });

  it('leaves a modified click to the browser (a new tab), so no in-app navigation runs', () => {
    titles.set(17, reading('live', 'Restart lmstudio'));
    render(<ApprovalSlip ids={[17]} lang="en" />);
    expect(fireEvent.click(screen.getByRole('link', { name: 'On the docket' }), { ctrlKey: true })).toBe(true);
    expect(opened.docket).toEqual([]);
  });

  it('writes Romanian with the plural forms', () => {
    render(<ApprovalSlip ids={Array.from({ length: 21 }, (_, i) => i + 1)} lang="ro" />);
    expect(screen.getByRole('note').querySelector('.n-slip__head')?.textContent).toBe('21 de acțiuni așteaptă decizia ta');
    expect(screen.getAllByRole('link', { name: 'Deschide în Decizii' })).toHaveLength(21);
  });

  it('draws nothing without ids', () => {
    const { container } = render(<ApprovalSlip ids={[]} lang="en" />);
    expect(container.innerHTML).toBe('');
  });
});

describe('TurnApprovals', () => {
  it('is the slip under the Ledger', () => {
    titles.set(5, reading('live', 'Draft a reply'));
    render(<TurnApprovals ids={[5]} slip lang="en" />);
    expect(screen.getByRole('note').hasAttribute('data-slip')).toBe(true);
    expect(screen.getByRole('link', { name: 'On the docket' })).toBeTruthy();
  });

  it('keeps the classic note, now navigating in the app to the Decisions card', () => {
    history.replaceState(null, '', '/v2/chat');
    render(<TurnApprovals ids={[17, 18]} />);
    const note = screen.getByRole('note');
    expect(note.textContent).toBe('2 actions wait for your decision: card #17, card #18 · decided only in the Decision Inbox');
    const links = within(note).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/v2/console/decision-inbox?card=17', '/v2/console/decision-inbox?card=18']);
    expect(fireEvent.click(links[1])).toBe(false);
    expect(opened.decisions).toEqual([18]);
  });
});

/* The floating desktop window (?desktop=floating with the native bridge) always shows the
   conversation alone (main.tsx), so an in-app route change there would change the address and
   nothing on screen. No link may navigate in place there (PHASE_B_PLAN.md §5.1). */
describe('in the floating desktop window', () => {
  const invoke = vi.fn(async (_cmd: string, _args: unknown) => {});
  beforeEach(() => {
    invoke.mockReset();
    invoke.mockImplementation(async () => {});
    (window as any).__TAURI__ = { core: { invoke } };
    history.replaceState(null, '', '/v2/chat?desktop=floating&frame=ledger');
  });
  afterEach(() => { delete (window as any).__TAURI__; });

  it('names the requests, sends the owner to the main window through the handoff and navigates nowhere', async () => {
    titles.set(17, reading('live', 'Restart lmstudio'));
    titles.set(18, reading('empty'));
    render(<ApprovalSlip ids={[17, 18]} lang="en" floating />);
    const slip = screen.getByRole('note');
    expect(slip.getAttribute('data-slip-mode')).toBe('handoff');
    expect(within(slip).queryAllByRole('link')).toEqual([]);
    expect(Array.from(slip.querySelectorAll('[data-slip-entry]')).map((row) => row.textContent))
      .toEqual(['Restart lmstudio', 'Request 18not on the docket']);
    expect(slip.querySelector('[data-slip-away]')?.textContent).toBe('Decide in the main window.Open in app');
    fireEvent.click(within(slip).getByRole('button', { name: 'Open in app' }));
    await waitFor(() => expect(invoke).toHaveBeenCalledExactlyOnceWith('desktop_action', { action: 'handoff' }));
    expect(opened.docket).toEqual([]);
    expect(opened.decisions).toEqual([]);
    expect(location.pathname + location.search).toBe('/v2/chat?desktop=floating&frame=ledger');
  });

  it('says so when the main window did not open', async () => {
    invoke.mockImplementation(async () => { throw new Error('Main window unavailable'); });
    titles.set(17, reading('live', 'Restart lmstudio'));
    render(<ApprovalSlip ids={[17]} lang="ro" floating />);
    fireEvent.click(screen.getByRole('button', { name: 'Deschide în aplicație' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Fereastra principală nu s-a deschis: Main window unavailable');
  });

  it('is the floating slip whenever the window is the floating one, even without the variant', () => {
    titles.set(17, reading('live', 'Restart lmstudio'));
    render(<TurnApprovals ids={[17]} slip lang="en" />);
    expect(screen.getByRole('note').getAttribute('data-slip-mode')).toBe('handoff');
  });

  it('without the bridge, loads the full HUD instead (a full navigation, without desktop=floating)', () => {
    delete (window as any).__TAURI__;
    titles.set(17, reading('live', 'Restart lmstudio'));
    titles.set(18, reading('empty'));
    render(<ApprovalSlip ids={[17, 18]} lang="en" floating />);
    const slip = screen.getByRole('note');
    expect(slip.getAttribute('data-slip-mode')).toBe('navigate');
    const docket = within(slip).getByRole('link', { name: 'On the docket' });
    expect(docket.getAttribute('href')).toBe('/v2/cockpit?frame=ledger#docket-entry-17');
    const decisions = within(slip).getByRole('link', { name: 'Open in Decisions' });
    expect(decisions.getAttribute('href')).toBe('/v2/console/decision-inbox?frame=ledger&card=18');
    expect(fireEvent.click(docket)).toBe(true);   // not prevented: the browser navigates
    expect(opened.docket).toEqual([]);
    expect(within(slip).queryAllByRole('button')).toEqual([]);
  });

  it('keeps the classic note\'s full navigation to the inbox card, as before Phase B', () => {
    history.replaceState(null, '', '/v2/chat?desktop=floating');
    render(<TurnApprovals ids={[17, 18]} />);
    const links = within(screen.getByRole('note')).getAllByRole('link');
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/v2/console/decision-inbox?card=17', '/v2/console/decision-inbox?card=18']);
    expect(fireEvent.click(links[0])).toBe(true);   // not prevented: a full navigation, without desktop=floating
    expect(opened.decisions).toEqual([]);
  });
});
