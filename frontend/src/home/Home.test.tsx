/* Home and the conversation page with their registers wired in (PHASE_B_PLAN.md §5.1, §2.1):
   the day register and its band, the conversation, the docket, and agents with the record at
   2200px and wider; the conversation page and the floating window. The registers' own content is
   their owners' tests; this pins where each one is drawn, and what Home adds around them. */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { V2 } from '../data';
import { initialHubSnapshot } from '../frame/types';
import { pageForRoute } from '../nav/routes';
import { resetPolling } from '../signals/poll';
import { stubHub } from '../frame/test-support';
import { ChatPage } from './ChatPage';
import { Home, MoreInHome, RECORD_QUERY, dayTitle } from './Home';
import type { TalkInput } from './talk/types';

const roster = [{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true, role: 'Prime Orchestrator' }];
const talk = {
  messages: [], thinking: null, onStop: () => {}, onProv: () => {}, lang: 'en', t: V2.I18N.en, onSubmit: () => true,
  onSelectAgent: () => {}, agent: 'jarvis', agents: roster, recipientStatus: 'ready', sessionId: '', selectedTurn: true,
} as unknown as TalkInput;
const MONDAY = new Date(2026, 10, 23, 10, 51);

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
beforeEach(() => {
  resetPolling();
  history.replaceState(null, '', '/v2/cockpit?frame=ledger');
  stubHub(() => ({ status: 503 }), vi.stubGlobal);
});
afterEach(() => { resetPolling(); vi.unstubAllGlobals(); });

/** A window.matchMedia that answers `wide` for the fourth register's query. */
function stubWidth(wide: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query === RECORD_QUERY ? wide : false, media: query,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
  }));
}

describe('Home', () => {
  it('draws the four registers in their cells, the day band above, and keeps the widths in CSS', async () => {
    render(<Home hub={initialHubSnapshot()} clock={MONDAY} lang="en" demo={false} navigate={() => {}} talk={talk} turns={[]} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Today — Monday, 23 November' })).toBeTruthy();
    const cell = (name: string) => document.querySelector(`.n-spread__cell--${name}`) as HTMLElement;
    expect(cell('day').querySelector('[data-register="day"]')).not.toBeNull();
    expect(cell('talk').querySelector('[data-register="talk"]')).not.toBeNull();
    expect(cell('docket').querySelector('[data-register="docket"]')).not.toBeNull();
    expect(cell('record').querySelector('[data-register="record"]')).not.toBeNull();
    expect([...document.querySelectorAll('[data-home] [data-register]')].map((el) => el.getAttribute('data-register')))
      .toEqual(['day', 'talk', 'docket', 'record']);
    // the folded day, for the narrower widths
    expect(document.querySelector('.n-home__bandrow [data-frame="dayband"]')).not.toBeNull();
    // the skip link's target: the conversation cell
    expect(document.getElementById('n-talk')?.querySelector('[data-register="talk"]')).not.toBeNull();
    // the widths decide which cells show: the day from 1680px, the band below it, the fourth register from 2200px
    expect(cell('day').getAttribute('data-show-from')).toBe('l');
    expect(cell('record').getAttribute('data-show-from')).toBe('xl');
    expect(document.querySelector('.n-home__bandrow')?.getAttribute('data-show-upto')).toBe('m');
    // a feed that did not answer is unknown on the docket, never "nothing is waiting"
    await waitFor(() => expect(document.querySelector('[data-register="docket"] [data-docket-state]')?.getAttribute('data-docket-state')).toBe('unknown'));
    expect(document.querySelector('[data-register="docket"]')?.textContent).not.toMatch(/Nothing is waiting/);
  });

  it('mounts the fourth register only while the viewport is 2200px wide, so its feeds are not asked below', async () => {
    stubWidth(false);
    let calls = stubHub(() => ({ status: 503 }), vi.stubGlobal);
    const asked = (part: string) => calls.some((c) => c.path.includes(part));
    const { unmount } = render(<Home hub={initialHubSnapshot()} clock={MONDAY} lang="en" demo={false} navigate={() => {}} talk={talk} turns={[]} />);
    expect(document.querySelector('[data-register="record"]')).toBeNull();
    expect(document.querySelector('.n-spread__cell--record')).toBeNull();
    await waitFor(() => expect(asked('/autonomy/tasks?status=blocked')).toBe(true));
    expect(asked('/api/security/audit/intent')).toBe(false);
    unmount();
    resetPolling();
    stubWidth(true);
    calls = stubHub(() => ({ status: 503 }), vi.stubGlobal);
    render(<Home hub={initialHubSnapshot()} clock={MONDAY} lang="en" demo={false} navigate={() => {}} talk={talk} turns={[]} />);
    expect(document.querySelector('.n-spread__cell--record [data-register="record"]')).not.toBeNull();
    await waitFor(() => expect(asked('/api/security/audit/intent')).toBe(true));
  });

  it('opens Home\'s other pages behind "More in Home" at the foot of the day register', () => {
    const navigate = vi.fn();
    render(<MoreInHome lang="en" navigate={navigate} />);
    const toggle = screen.getByRole('button', { name: 'More in Home · 10 pages' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const list = document.getElementById(toggle.getAttribute('aria-controls') as string) as HTMLElement;
    expect(list.hidden).toBe(true);
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(list.hidden).toBe(false);
    const links = within(list).getAllByRole('link');
    expect(links).toHaveLength(10);
    expect(links[0].textContent).toBe('Conversation');
    expect(links.some((a) => a.textContent === 'Today')).toBe(false);
    const today = within(list).getByRole('link', { name: 'What Nerva did today' });
    expect(today.getAttribute('href')).toBe('/v2/console/today?frame=ledger');
    fireEvent.click(today);
    expect(navigate).toHaveBeenCalledWith('/v2/console/today');
  });

  it('dates the day and says "More in Home" in Romanian', () => {
    expect(dayTitle(MONDAY, 'ro')).toBe('luni, 23 noiembrie');
    render(<Home hub={initialHubSnapshot()} clock={MONDAY} lang="ro" demo={false} navigate={() => {}} talk={talk} turns={[]} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Azi — luni, 23 noiembrie' })).toBeTruthy();
    // at the foot of the day register (from 1680px) and at the end of the day band (below it); CSS shows one
    expect(screen.getAllByRole('button', { name: 'Mai multe în Acasă · 10 pagini' })).toHaveLength(2);
  });

  it('keeps Home\'s other pages one click away below 1680px: "More in Home" ends the day band', () => {
    render(<Home hub={initialHubSnapshot()} clock={MONDAY} lang="en" demo={false} navigate={() => {}} talk={talk} turns={[]} />);
    const band = document.querySelector('.n-home__bandrow') as HTMLElement;
    expect(band.getAttribute('data-show-upto')).toBe('m');
    const more = band.querySelector('[data-home-more="band"]') as HTMLElement;
    expect(more.closest('[data-frame="dayband"]')).not.toBeNull();
    expect(more.classList.contains('n-home__more--popover')).toBe(true);
    const toggle = within(more).getByRole('button', { name: 'More in Home · 10 pages' });
    fireEvent.click(toggle);
    expect(within(more).getAllByRole('link')).toHaveLength(10);
    // Escape closes the list and stays in the band
    fireEvent.keyDown(toggle, { key: 'Escape' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('.n-spread__cell--day [data-home-more="register"]')).not.toBeNull();
  });

  it('labels the demo sample and asks the hub nothing for the docket in demo', async () => {
    const calls = stubHub(() => ({ status: 503 }), vi.stubGlobal);
    history.replaceState(null, '', '/v2/cockpit?frame=ledger&demo=1');
    render(<Home hub={initialHubSnapshot(true)} clock={MONDAY} lang="en" demo navigate={() => {}} talk={{ ...talk, demo: true } as TalkInput} turns={[]} />);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(document.querySelector('[data-register="docket"] [data-source-state="demo"]')).not.toBeNull();
    expect(document.querySelector('[data-register="day"] [data-source-state="demo"]')).not.toBeNull();
    expect(calls.some((c) => c.path.includes('/autonomy/tasks?status=blocked'))).toBe(false);
  });
});

describe('ChatPage', () => {
  it('is Home\'s Conversation page, with Home\'s contents and the conversation at full width', () => {
    render(<ChatPage variant="chat" page={pageForRoute({ mode: 'chat', panel: null })} attention={{}} onFind={() => {}}
      talk={talk} turns={[]} hub={initialHubSnapshot()} lang="en" demo={false} navigate={() => {}} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Conversation' })).toBeTruthy();
    const contents = screen.getByRole('navigation', { name: 'Pages in Home' });
    expect(within(contents).getByRole('link', { name: 'Conversation' }).getAttribute('aria-current')).toBe('page');
    const register = document.querySelector('[data-chatpage="chat"] [data-register="talk"]') as HTMLElement;
    expect(register).not.toBeNull();
    expect(register.querySelector('[data-composer-variant="chat"]')).not.toBeNull();
  });

  it('is the floating window: the running head as marks, the window\'s notices, the docket line, the conversation', async () => {
    stubHub((_m, path) => (path.includes('/autonomy/tasks?status=blocked')
      ? { status: 200, body: { tasks: [{ id: 7, status: 'blocked', title: 'Restart qdrant', risk_tier: 2 }], groups: [] } }
      : path === '/autonomy/mode' ? { status: 200, body: { mode: 'ask' } } : { status: 503 }), vi.stubGlobal);
    render(<ChatPage variant="floating" talk={talk} turns={[]} hub={initialHubSnapshot()} lang="en" demo={false} navigate={() => {}}
      notices={<p data-testid="notices">notices</p>} />);
    const page = document.querySelector('[data-chatpage="floating"]') as HTMLElement;
    const head = page.querySelector('.n-runhead--marks') as HTMLElement;
    expect(head).not.toBeNull();
    // all eight running-head items at this width too (§4.2, §11): six signals, the mode, the interrupts
    expect(head.querySelectorAll('[data-signal]')).toHaveLength(6);
    expect(head.querySelector('[data-runhead="interrupts"]')).not.toBeNull();
    const mode = head.querySelector('[data-runhead="mode"]') as HTMLElement;
    expect(mode.hasAttribute('data-readonly')).toBe(true);
    await waitFor(() => expect(mode.querySelector('[data-mode]')?.textContent).toBe('Ask'));
    // read here, changed in the main window: no mode control in the floating window
    expect(within(head).queryByRole('radiogroup')).toBeNull();
    expect(screen.getByTestId('notices')).toBeTruthy();
    expect(page.querySelector('[data-register="talk"] [data-composer-variant="floating"]')).not.toBeNull();
    expect(page.querySelector('[data-frame="masthead"]')).toBeNull();
    // one docket line, no signing here
    await waitFor(() => expect(page.querySelector('[data-docket-line]')?.textContent).toMatch(/1 awaits? your signature/));
    expect(page.querySelector('[data-docket-entry]')).toBeNull();
  });
});
