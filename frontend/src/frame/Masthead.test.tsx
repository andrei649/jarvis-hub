import React, { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearActionFailures } from '../api/client';
import { pageForRoute } from '../nav/routes';
import { refreshPolled, resetPolling } from '../signals/poll';
import type { Attention } from '../signals/types';
import { themeById } from '../theme/registry';
import { FIT_STEPS, Masthead, ONE_ROW_QUERY, fitMasthead, fitSteps, rowSpills, type MastheadProps } from './Masthead';
import { Notices } from './Notices';
import { initialHubSnapshot } from './types';
import { ARMED, HALTED, stubHub } from './test-support';

const AREA_NAMES = ['Home', 'Work', 'Agents', 'Memory', 'Trust', 'Build', 'Connect', 'Observe', 'Settings'];

function renderMasthead(over: Partial<MastheadProps> = {}) {
  const props: MastheadProps = {
    page: pageForRoute({ mode: 'trust', panel: null }), lang: 'en', setLang: vi.fn(), scheme: 'dark', schemePreference: 'dark',
    setScheme: vi.fn(), theme: themeById('ledger'), attention: {}, findChord: 'Ctrl+K', onFind: vi.fn(), onGlance: vi.fn(),
    navigate: vi.fn(), demo: false, ...over,
  };
  const view = render(<Masthead {...props} />);
  return { props, ...view };
}
const areaNav = () => screen.getByRole('navigation', { name: 'Areas' });

beforeEach(() => {
  resetPolling();
  clearActionFailures();
  localStorage.clear();
  history.replaceState(null, '', '/v2/trust?frame=ledger');
  stubHub(() => ({ status: 200, body: ARMED }), vi.stubGlobal);
});
afterEach(() => { resetPolling(); clearActionFailures(); vi.unstubAllGlobals(); });

describe('Masthead', () => {
  it('is the frame\'s masthead, with the brand linking to Today', () => {
    const { props } = renderMasthead();
    const header = document.querySelector('[data-frame="masthead"]') as HTMLElement;
    expect(header.tagName).toBe('HEADER');
    const brand = screen.getByRole('link', { name: 'Nerva — today’s page' });
    expect(brand.getAttribute('href')).toBe('/v2/cockpit?frame=ledger');
    fireEvent.click(brand);
    expect(props.navigate).toHaveBeenCalledWith('/v2/cockpit');
  });

  it('lists the nine areas in masthead order, marks the current one and carries their anchors', () => {
    const { props } = renderMasthead();
    const links = within(areaNav()).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(AREA_NAMES);
    expect(links.map((a) => a.getAttribute('data-anchor'))).toEqual(
      ['home', 'work', 'agents', 'memory', 'trust', 'build', 'connect', 'observe', 'settings'].map((id) => `area.${id}`));
    expect(links.filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.textContent)).toEqual(['Trust']);
    expect(links[6].getAttribute('href')).toBe('/v2/interop?frame=ledger');
    fireEvent.click(links[5]);
    expect(props.navigate).toHaveBeenCalledWith('/v2/build');
    // a modified click is the browser's (a new tab), not the app's (jsdom cannot open the tab)
    const noTab = (event: Event) => event.preventDefault();
    document.addEventListener('click', noTab);
    fireEvent.click(links[3], { ctrlKey: true });
    document.removeEventListener('click', noTab);
    expect(props.navigate).not.toHaveBeenCalledWith('/v2/memory');
  });

  it('marks a sub-page\'s area as current', () => {
    renderMasthead({ page: pageForRoute({ mode: 'console', panel: 'kill-switch' }) });
    const current = within(areaNav()).getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(current.map((a) => a.textContent)).toEqual(['Trust']);
  });

  it('shows a count only when the attention model has a live one, never a 0', () => {
    const { unmount } = renderMasthead({ attention: {} });
    expect(areaNav().querySelectorAll('[data-note]')).toHaveLength(0);
    expect(within(areaNav()).getByRole('link', { name: 'Work' })).toBeTruthy();
    unmount();
    const attention: Attention = { docket: { key: 'docket', count: 9 }, services: { key: 'services', count: 4 } };
    renderMasthead({ attention });
    const work = within(areaNav()).getByRole('link', { name: 'Work — 9 need you' });
    const note = work.querySelector('[data-note="docket"]') as HTMLElement;
    expect(note.classList.contains('n-areas__note--hand')).toBe(true);
    // the long words, the short ones and the count alone, switched by width and by the fit
    expect([...note.querySelectorAll('.n-areas__words')].map((el) => el.textContent)).toEqual(['9 need you', '9']);
    expect(note.querySelector('.n-areas__count')?.textContent).toBe('9');
    // a word space parts the name from its note, so the drawn words ("Work 9") are words of the
    // link's name, not "Work9" (WCAG 2.5.3; axe label-content-name-mismatch in the e2e lane)
    expect(work.textContent).toBe('Work 9 need you99');
    // the words stay in the tooltip whatever form is drawn
    expect(work.getAttribute('title')).toBe('Work — 9 need you');
    const observe = within(areaNav()).getByRole('link', { name: 'Observe — 4 services down' });
    expect(observe.querySelector('[data-mark="problem"]')).not.toBeNull();
    expect(observe.querySelector('.n-areas__note--hand')).toBeNull();
    expect(observe.getAttribute('title')).toBe('Observe — 4 services down');
    // a link with no note has no tooltip to repeat
    expect(within(areaNav()).getByRole('link', { name: 'Agents' }).hasAttribute('title')).toBe(false);
  });

  it('switches the language with an EN | RO radio group', () => {
    const { props } = renderMasthead();
    const group = screen.getByRole('radiogroup', { name: 'Language' });
    const [en, ro] = within(group).getAllByRole('radio');
    expect(en.getAttribute('aria-checked')).toBe('true');
    expect(ro.getAttribute('aria-checked')).toBe('false');
    expect([en.textContent, ro.textContent]).toEqual(['EN', 'RO']);
    expect(en.tabIndex).toBe(0);
    expect(ro.tabIndex).toBe(-1);
    fireEvent.click(within(group).getByRole('radio', { name: 'Romanian' }));
    expect(props.setLang).toHaveBeenCalledWith('ro');
    (props.setLang as any).mockClear();
    fireEvent.keyDown(en, { key: 'ArrowRight' });
    expect(props.setLang).toHaveBeenCalledWith('ro');
  });

  it('speaks Romanian', () => {
    renderMasthead({ lang: 'ro' });
    const nav = screen.getByRole('navigation', { name: 'Zone' });
    expect(within(nav).getAllByRole('link').map((a) => a.textContent)).toEqual(
      ['Acasă', 'Lucru', 'Agenți', 'Memorie', 'Încredere', 'Construire', 'Conexiuni', 'Observare', 'Setări']);
    const group = screen.getByRole('radiogroup', { name: 'Limbă' });
    expect(within(group).getByRole('radio', { name: 'Română' }).getAttribute('aria-checked')).toBe('true');
    expect(screen.getByRole('button', { name: 'Oprește toți agenții' })).toBeTruthy();
  });

  it('toggles the resolved scheme, and is unavailable with its reason for a dark-only Classic look', () => {
    const { props, unmount } = renderMasthead();
    fireEvent.click(screen.getByRole('button', { name: 'Scheme: Dark. Switch to Light' }));
    expect(props.setScheme).toHaveBeenCalledWith('light');
    unmount();
    const classic = renderMasthead({ theme: themeById('obsidian') });
    const toggle = screen.getByRole('button', { name: 'Scheme: Dark. Classic looks are dark only' });
    expect(toggle.getAttribute('aria-disabled')).toBe('true');
    expect(toggle.getAttribute('title')).toBe('Scheme: Dark. Classic looks are dark only');
    fireEvent.click(toggle);
    expect(classic.props.setScheme).not.toHaveBeenCalled();
  });

  it('opens the search sheet from Find (data-anchor="console", its key shown) and goes to Glance', () => {
    const { props } = renderMasthead();
    const find = screen.getByRole('button', { name: 'Search or run a command — finds every area, panel, agent and action · Ctrl+K' });
    // its name begins with the words it shows, long and short (WCAG 2.5.3, label in name)
    const name = find.getAttribute('aria-label') as string;
    for (const shown of find.querySelectorAll('.n-masthead__find-words > span')) expect(name.startsWith(shown.textContent as string)).toBe(true);
    expect(find.getAttribute('data-anchor')).toBe('console');
    // the key is shown and the name ends with it; the cap is drawn by frame.css from data-key
    // (kit-css.test.ts pins the rule) and is aria-hidden, so the only text the button puts on
    // screen is the words: text after them, before the name's own key, fails label-in-name
    // (axe label-content-name-mismatch counts on-screen text, aria-hidden or not)
    const key = find.querySelector('kbd');
    expect(key?.getAttribute('data-key')).toBe('Ctrl+K');
    expect(key?.getAttribute('aria-hidden')).toBe('true');
    expect(name.endsWith('Ctrl+K')).toBe(true);
    const onScreen = find.cloneNode(true) as HTMLElement;
    onScreen.querySelectorAll('.n-masthead__find-words').forEach((el) => el.remove());
    expect(onScreen.textContent).toBe('');
    fireEvent.click(find);
    expect(props.onFind).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Glance — the day on one quiet screen' }));
    expect(props.onGlance).toHaveBeenCalledTimes(1);
  });

  it('stops with one click: it posts, then reads the state again and says Halted', async () => {
    let halted = false;
    vi.unstubAllGlobals();
    const calls = stubHub((method) => {
      if (method === 'POST') { halted = true; return { status: 200, body: { ok: true, engaged: true } }; }
      return { status: 200, body: halted ? HALTED : ARMED };
    }, vi.stubGlobal);
    const { props } = renderMasthead();
    const stop = await screen.findByRole('button', { name: 'Stop all agents' });
    expect(stop.getAttribute('title')).toContain('One click');
    fireEvent.click(stop);
    const resume = await screen.findByRole('link', { name: 'All agents are halted. Resume in Trust › Emergency stop' });
    const posts = calls.filter((c) => c.method === 'POST');
    expect(posts).toEqual([{ method: 'POST', path: '/api/security/kill-switch', body: { engage: true, scope: 'global', reason: 'hud' } }]);
    expect(calls.slice(calls.indexOf(posts[0]) + 1).some((c) => c.method === 'GET' && c.path === '/api/security/kill-switch')).toBe(true);
    expect(screen.queryByRole('button', { name: 'Stop all agents' })).toBeNull();
    expect(resume.getAttribute('href')).toBe('/v2/console/kill-switch?frame=ledger');
    fireEvent.click(resume);
    expect(props.navigate).toHaveBeenCalledWith('/v2/console/kill-switch');
  });

  it('offers the stop while its state is unknown', async () => {
    vi.unstubAllGlobals();
    stubHub(() => ({ status: 503, body: { error: 'kill-switch not available' } }), vi.stubGlobal);
    renderMasthead();
    const stop = screen.getByRole('button', { name: 'Stop all agents' }) as HTMLButtonElement;
    expect(stop.disabled).toBe(false);
  });

  it('raises a refused stop as an alert in the notices: nothing was halted', async () => {
    vi.unstubAllGlobals();
    stubHub((method) => (method === 'POST'
      ? { status: 403, body: { error: 'kernel denied: admin.kill_switch' } } : { status: 200, body: ARMED }), vi.stubGlobal);
    function WithNotices() {
      const [refusal, setRefusal] = useState<string | null>(null);
      const page = pageForRoute({ mode: 'trust', panel: null });
      return <>
        <Masthead page={page} lang="en" setLang={() => {}} scheme="dark" schemePreference="dark" setScheme={() => {}}
          theme={themeById('ledger')} attention={{}} findChord="Ctrl+K" onFind={() => {}} onGlance={() => {}} navigate={() => {}}
          demo={false} onStopResult={setRefusal} />
        <Notices lang="en" hub={initialHubSnapshot()} page={page} demo={false} stopRefusal={refusal}
          onDismissStopRefusal={() => setRefusal(null)} showFailures={false} />
      </>;
    }
    render(<WithNotices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Stop all agents' }));
    const alert = await screen.findByRole('alert');
    expect(alert.getAttribute('data-notice')).toBe('stop');
    expect(alert.textContent).toContain('Stop was refused — kernel denied: admin.kill_switch. Nothing was halted.');
    expect(document.querySelector('[data-frame="masthead"] [role="alert"]')).toBeNull();
    expect(screen.getByRole('button', { name: 'Stop all agents' })).toBeTruthy();
    fireEvent.click(within(alert).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  /** The masthead beside the frame's notices, failed actions included, as Frame draws them. */
  function WithNotices({ lang = 'en' as const }: { lang?: 'en' | 'ro' }) {
    const [refusal, setRefusal] = useState<string | null>(null);
    const page = pageForRoute({ mode: 'trust', panel: null });
    return <>
      <Masthead page={page} lang={lang} setLang={() => {}} scheme="dark" schemePreference="dark" setScheme={() => {}}
        theme={themeById('ledger')} attention={{}} findChord="Ctrl+K" onFind={() => {}} onGlance={() => {}} navigate={() => {}}
        demo={false} onStopResult={setRefusal} />
      <Notices lang={lang} hub={initialHubSnapshot()} page={page} demo={false} stopRefusal={refusal}
        onDismissStopRefusal={() => setRefusal(null)} />
    </>;
  }

  it('reads a 504 whose state read again says halted as a stop that worked: Halted, and no refusal anywhere', async () => {
    let posted = false;
    vi.unstubAllGlobals();
    stubHub((method) => {
      if (method === 'POST') { posted = true; return { status: 504, body: { error: 'gateway timeout' } }; }
      return { status: 200, body: posted ? HALTED : ARMED };
    }, vi.stubGlobal);
    render(<WithNotices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Stop all agents' }));
    expect(await screen.findByRole('link', { name: 'All agents are halted. Resume in Trust › Emergency stop' })).toBeTruthy();
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 10)); });
    expect(screen.queryByRole('alert')).toBeNull();
    expect(document.querySelector('[data-notice="stop"], [data-notice="failures"]')).toBeNull();
    expect(document.body.textContent).not.toMatch(/Nothing was halted|did not happen/);
  });

  it('raises a refused stop as one alert, not a second "failed actions" line for the same POST', async () => {
    vi.unstubAllGlobals();
    stubHub((method) => (method === 'POST'
      ? { status: 403, body: { error: 'kernel denied: admin.kill_switch' } } : { status: 200, body: ARMED }), vi.stubGlobal);
    render(<WithNotices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Stop all agents' }));
    const alert = await screen.findByRole('alert');
    expect(alert.getAttribute('data-notice')).toBe('stop');
    expect(screen.getAllByRole('alert')).toHaveLength(1);
    expect(document.querySelector('[data-notice="failures"]')).toBeNull();
  });

  it('withdraws an earlier sentence once the switch comes to read halted', async () => {
    let halted = false;
    vi.unstubAllGlobals();
    stubHub((method) => (method === 'POST' ? 'down' : { status: 200, body: halted ? HALTED : ARMED }), vi.stubGlobal);
    render(<WithNotices />);
    fireEvent.click(await screen.findByRole('button', { name: 'Stop all agents' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('The stop got no answer from the hub, and the hub still reports no halt: nothing is halted yet.');
    // the hub acted on it after all: the next reading says halted
    halted = true;
    await act(async () => { await refreshPolled('/api/security/kill-switch'); });
    expect(await screen.findByRole('link', { name: 'All agents are halted. Resume in Trust › Emergency stop' })).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('shows a refusal itself when no notices region takes it', async () => {
    vi.unstubAllGlobals();
    stubHub((method) => (method === 'POST' ? { status: 403, body: { error: 'kernel denied: x' } } : { status: 200, body: ARMED }), vi.stubGlobal);
    renderMasthead();
    fireEvent.click(await screen.findByRole('button', { name: 'Stop all agents' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Stop was refused — kernel denied: x. Nothing was halted.');
  });
});

/* Fitting the row (Masthead.tsx FIT_STEPS; frame.css draws each step, frame-fit-css.test.ts pins
   that it does). jsdom lays nothing out, so the geometry is a model: a row that needs `need(steps)`
   px in a window `room` px wide, and Find's words — drawn whole ("long", from 1680px), short
   ("search" step, or below 1680px) or not at all ("find" step) — that need `words(form)` px in a
   box `box(steps)` px wide (40 when not given). Every read of the layout is counted. */
type FindForm = 'long' | 'short' | 'none';
type RowModel = { room: number; need: (steps: string[]) => number; words?: (form: FindForm) => number; box?: (steps: string[]) => number; long?: boolean };
const layoutReads = { count: 0 };
function stubRow(model: RowModel) {
  const at = (el: Element) => el.closest('.n-masthead');
  const steps = (el: Element) => (at(el)?.getAttribute('data-fit') || '').split(' ').filter(Boolean);
  const form = (el: Element): FindForm => (steps(el).includes('find') ? 'none' : steps(el).includes('search') || !model.long ? 'short' : 'long');
  const width = (el: Element, scroll: boolean) => {
    layoutReads.count += 1;
    if (el.classList.contains('n-masthead')) return scroll ? Math.max(model.room, model.need(steps(el))) : model.room;
    if (el.classList.contains('n-masthead__find-words')) {
      if (form(el) === 'none') return 0;
      const box = model.box ? model.box(steps(el)) : 40;
      return scroll ? Math.max(box, model.words ? model.words(form(el)) : box) : box;
    }
    return 0;
  };
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, get() { return width(this, true); } });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return width(this, false); } });
}
/** A window from 1100px wide (the masthead's one row). */
const oneRowWindow = () => vi.stubGlobal('matchMedia', (query: string) => ({
  matches: query === ONE_ROW_QUERY, media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
}));
function bareHeader() {
  const header = document.createElement('header');
  header.className = 'n-masthead';
  header.setAttribute('data-bare', '');
  header.innerHTML = '<div class="n-masthead__areas"></div><button class="n-masthead__find"><span class="n-masthead__find-words"></span></button><div class="n-masthead__tools"></div>';
  document.body.appendChild(header);
  return header;
}

describe('Masthead — fitting its row from 1100px', () => {
  const innerWidth = window.innerWidth;
  afterEach(() => {
    delete (HTMLElement.prototype as any).scrollWidth;
    delete (HTMLElement.prototype as any).clientWidth;
    Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: innerWidth });
    document.querySelectorAll('header[data-bare]').forEach((el) => el.remove());
  });

  it('takes the fewest steps, in order, the least loss first, and never drops one it still needs', () => {
    expect(FIT_STEPS).toEqual(['search', 'notes', 'glance', 'hand', 'tight', 'brand', 'stop', 'find', 'tighter', 'scroll']);
    expect(fitSteps(() => false)).toEqual([]);
    expect(fitSteps((steps) => steps.length < 3)).toEqual(['search', 'notes', 'glance']);
    // going on from steps already taken, it keeps those still needed and takes back, the lossiest
    // first, one that no longer is
    expect(fitSteps((steps) => steps.length < 3, ['search', 'notes', 'glance'])).toEqual(['search', 'notes', 'glance']);
    expect(fitSteps((steps) => steps.length < 2, ['search', 'notes', 'glance'])).toEqual(['search', 'notes']);
    // a row that never fits takes every step; the areas row scrolling is the last resort
    expect(fitSteps(() => true)).toEqual([...FIT_STEPS]);
    // below 1680px Find's placeholder is short already: the "search" step would change nothing
    expect(fitSteps((steps) => steps.length < 2, [], false)).toEqual(['notes', 'glance']);
    expect(fitSteps(() => true, [], false)).toEqual(FIT_STEPS.filter((step) => step !== 'search'));
  });

  it('measures its way through the steps until nothing spills; below 1100px it takes none', () => {
    const model: RowModel = { room: 1100, need: (steps) => 1400 - 80 * steps.length };
    stubRow(model);
    const header = bareHeader();
    fitMasthead(header, { wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('notes glance hand tight');
    // nothing changed: it only goes on from where it is, and finds nothing to do
    fitMasthead(header, { fresh: false, wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('notes glance hand tight');
    // a wider window, measured afresh: fewer steps
    model.room = 1300;
    fitMasthead(header, { wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('notes glance');
    // from 1680px Find's long words are the first to give way
    model.room = 1300;
    fitMasthead(header, { wide: true, long: true });
    expect(header.getAttribute('data-fit')).toBe('search notes');
    // the masthead below 1100px is two rows (the areas scroll, or sit in the drawer): no step
    fitMasthead(header, { wide: false });
    expect(header.hasAttribute('data-fit')).toBe(false);
  });

  it('takes back, the lossiest first, the steps a later one made unneeded', () => {
    // Find's icon frees far more than the steps before it: once it is taken, the stop's words, the
    // brand's name and the tighter spacing it no longer needs come back; the notes stay short, as
    // the row still needs one of the earlier steps
    const frees: Record<string, number> = { notes: 60, glance: 40, hand: 40, tight: 50, brand: 50, stop: 60, find: 260 };
    const model: RowModel = { room: 1150, need: (steps) => 1460 - steps.reduce((sum, step) => sum + (frees[step] ?? 0), 0) };
    stubRow(model);
    const header = bareHeader();
    // the walk goes as far as Find's icon (every step before it leaves 1160px in 1150), and then
    // the row keeps only what it needs with it: the stop's words, the brand's name, the spacing,
    // the owner's count words and Glance's word come back; the notes' words cannot
    expect(fitSteps((steps) => model.need([...steps]) > model.room, [], false)).toEqual(['notes', 'find']);
    fitMasthead(header, { wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('notes find');
    // a wider window, measured afresh: Find keeps its words, and no step is given up for nothing
    model.room = 1420;
    fitMasthead(header, { wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('notes');
    // the same at each room whichever way the window was resized
    const at = (room: number) => { model.room = room; fitMasthead(header, { wide: true, long: false }); return header.getAttribute('data-fit') || ''; };
    const rooms = [1500, 1400, 1300, 1200, 1100];
    const down = rooms.map(at);
    expect([...rooms].reverse().map(at).reverse()).toEqual(down);
  });

  it('never cuts Find\'s words: they give way at their own steps, after the steps before them', () => {
    // the row fits, but Find's box is squeezed below its words: that is a spill like any other
    const model: RowModel = {
      room: 1500, need: () => 1200, long: true,
      words: (form) => (form === 'long' ? 180 : 150),
      // each step frees room the field (the row's flexible part) takes; "tight" frees the most
      box: (steps) => 40 + 20 * steps.length + (steps.includes('tight') ? 60 : 0),
    };
    stubRow(model);
    const header = bareHeader();
    const words = header.querySelector('.n-masthead__find-words') as HTMLElement;
    const cut = () => words.scrollWidth - words.clientWidth > 1;
    // long words (180px) in a 40px box: "search" first (150px), then the steps in order until the
    // box holds them — never the "find" step, which drops them, while an earlier one helps. The
    // walk ends on "search notes glance hand tight" (200px); "tight" freed so much that "hand" and
    // "glance" come back (160px still holds 150), "notes" cannot (140px would not)
    fitMasthead(header, { wide: true, long: true });
    expect(header.getAttribute('data-fit')).toBe('search notes tight');
    expect(cut()).toBe(false);
    // without the "search" step (its words drawn as they are, 180px here): the walk ends on "notes
    // glance hand tight" (180px), which every one of them is needed for
    fitMasthead(header, { wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('notes glance hand tight');
    expect(cut()).toBe(false);
    // a box that never holds them: Find's words go at the "find" step, after the stop's; the row
    // itself fits, so the steps before it, which did not help the words, all come back
    model.box = () => 40;
    fitMasthead(header, { wide: true, long: false });
    expect(header.getAttribute('data-fit')).toBe('find');
    expect(cut()).toBe(false);
    // room enough: the words are drawn whole and no step is taken
    model.box = () => 200;
    fitMasthead(header, { wide: true, long: true });
    expect(header.hasAttribute('data-fit')).toBe(false);
  });

  /* Review, fourth round: Find read "Sear…" (Atlas, 1440px) and "Caută sau rulează o coman…"
     (Ledger Romanian, 1680px) because its words were 0.44–0.89px wider than their box, which the
     whole-pixel scrollWidth and clientWidth read as 44 in 43 or 163 in 162 — not a spill by more
     than a pixel — while Chromium draws the ellipsis for any overflow of a layout unit. */
  it('counts Find\'s words cut by less than a pixel as a spill, as Chromium draws the ellipsis', () => {
    const header = bareHeader();
    const words = header.querySelector('.n-masthead__find-words') as HTMLElement;
    const box = (left: number, right: number) => ({ left, right, top: 12, bottom: 30, width: right - left, height: 18, x: left, y: 12, toJSON() { return this; } }) as DOMRect;
    Object.defineProperty(words, 'scrollWidth', { configurable: true, value: 163 });
    Object.defineProperty(words, 'clientWidth', { configurable: true, value: 162 });
    const rect = vi.spyOn(words, 'getBoundingClientRect').mockReturnValue(box(400, 562));
    let textRight = 562.73;
    const range = vi.spyOn(document, 'createRange').mockImplementation(() => ({ selectNodeContents: () => {}, getClientRects: () => [box(400, textRight)] }) as unknown as Range);
    try {
      expect(rowSpills(header)).toBe(true);
      // drawn whole, exactly as wide as its box: it fits
      textRight = 562;
      Object.defineProperty(words, 'scrollWidth', { configurable: true, value: 162 });
      expect(rowSpills(header)).toBe(false);
    } finally {
      range.mockRestore();
      rect.mockRestore();
    }
  });

  it('fits itself when it renders and again when the window is resized, and keeps every name', () => {
    oneRowWindow();
    const model: RowModel = { room: 1100, need: (steps) => 1400 - 80 * steps.length };
    stubRow(model);
    renderMasthead({ attention: { docket: { key: 'docket', count: 128 }, record: { key: 'record', brokenAt: 412907 } } });
    const header = document.querySelector('[data-frame="masthead"]') as HTMLElement;
    expect(header.getAttribute('data-fit')).toBe('notes glance hand tight');
    model.room = 1300;
    act(() => {
      Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1300 });
      window.dispatchEvent(new Event('resize'));
    });
    expect(header.getAttribute('data-fit')).toBe('notes glance');
    // what a step takes off the screen stays in the names and the tooltips
    expect(within(areaNav()).getByRole('link', { name: 'Work — 128 need you' }).getAttribute('title')).toBe('Work — 128 need you');
    expect(within(areaNav()).getByRole('link', { name: 'Trust — record broken at entry 412907' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Stop all agents' })).toBeTruthy();
    const find = screen.getByRole('button', { name: 'Search or run a command — finds every area, panel, agent and action · Ctrl+K' });
    expect(find.getAttribute('title')).toBe(find.getAttribute('aria-label'));
    expect(screen.getByRole('link', { name: 'Nerva — today’s page' }).getAttribute('title')).toBe('Nerva — today’s page');
  });

  it('measures afresh when the words change, as a language switch does', async () => {
    oneRowWindow();
    // the Romanian row is wider: it needs two more steps than the English one
    const model: RowModel = { room: 1200, need: (steps) => (document.querySelector('[lang="ro"][aria-checked="true"]') ? 1520 : 1360) - 80 * steps.length };
    stubRow(model);
    const { rerender, props } = renderMasthead();
    const header = document.querySelector('[data-frame="masthead"]') as HTMLElement;
    expect(header.getAttribute('data-fit')).toBe('notes glance');
    // the words changed on screen: the row refits before the next paint (its words are observed)
    await act(async () => { rerender(<Masthead {...props} lang="ro" />); });
    expect(header.getAttribute('data-fit')).toBe('notes glance hand tight');
    await act(async () => { rerender(<Masthead {...props} lang="en" />); });
    expect(header.getAttribute('data-fit')).toBe('notes glance');
  });

  it('reads no layout on a render that changes nothing, as App\'s render on every streamed token', async () => {
    oneRowWindow();
    stubRow({ room: 1100, need: (steps) => 1400 - 80 * steps.length });
    const { rerender, props } = renderMasthead();
    const header = document.querySelector('[data-frame="masthead"]') as HTMLElement;
    expect(header.getAttribute('data-fit')).toBe('notes glance hand tight');
    layoutReads.count = 0;
    // new callbacks and an equal attention model, as App passes them on each of its renders
    for (let i = 0; i < 5; i += 1) {
      await act(async () => { rerender(<Masthead {...props} onFind={vi.fn()} navigate={vi.fn()} attention={{}} />); });
    }
    expect(layoutReads.count).toBe(0);
    // a change it draws is measured
    await act(async () => { rerender(<Masthead {...props} attention={{ docket: { key: 'docket', count: 128 } }} />); });
    expect(layoutReads.count).toBeGreaterThan(0);
  });

  it('refits when the stop\'s busy words change the tools\' width', async () => {
    oneRowWindow();
    // the stop's "Stopping…" (the busy words) needs one step more than "Stop all agents"
    const model: RowModel = { room: 1200, need: (steps) => (document.querySelector('[data-stop][aria-busy="true"]') ? 1440 : 1360) - 80 * steps.length };
    stubRow(model);
    // the stop's POST waits for the test to answer it, so its busy words stay on screen meanwhile
    let release: () => void = () => {};
    const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body, clone() { return this; }, headers: { get: () => 'application/json' } });
    vi.stubGlobal('fetch', (_url: string, init: { method?: string } = {}) => (init.method === 'POST'
      ? new Promise((resolve) => { release = () => resolve(reply({ ok: true, engaged: true })); })
      : Promise.resolve(reply(ARMED))));
    renderMasthead();
    const header = document.querySelector('[data-frame="masthead"]') as HTMLElement;
    expect(header.getAttribute('data-fit')).toBe('notes glance');
    const stop = await screen.findByRole('button', { name: 'Stop all agents' });
    await act(async () => { fireEvent.click(stop); });
    expect(stop.textContent).toContain('Stopping…');
    expect(header.getAttribute('data-fit')).toBe('notes glance hand');
    await act(async () => { release(); });
    await waitFor(() => expect(stop.getAttribute('aria-busy')).toBeNull());
    expect(header.getAttribute('data-fit')).toBe('notes glance');
  });
});

describe('Masthead — the halted stop', () => {
  it('keeps "resume in Trust" in its title, whatever form the fit draws', async () => {
    vi.unstubAllGlobals();
    stubHub(() => ({ status: 200, body: HALTED }), vi.stubGlobal);
    renderMasthead();
    const halted = await screen.findByRole('link', { name: 'All agents are halted. Resume in Trust › Emergency stop' });
    expect(halted.getAttribute('title')).toBe('All agents are halted. Resume in Trust › Emergency stop');
    // its long and short forms, switched by the width and the "stop" step
    expect([...halted.querySelectorAll('span')].map((el) => el.textContent)).toEqual(['Halted · resume in Trust', 'Halted']);
  });
});

describe('StopButton — a halt read too long ago', () => {
  const killSwitch = (state: 'live' | 'stale', halted: boolean) => ({
    state, value: { halted }, checkedAt: 1, lastGoodAt: new Date(2026, 10, 24, 10, 44).getTime(),
    stop: vi.fn(async () => ({ ok: true as const, answer: 'accepted' as const, after: 'halted' as const })), refresh: vi.fn(async () => {}),
  });

  it('hides the stop only for a current halt; a stale one offers it again and says why', async () => {
    const { StopButton } = await import('./StopButton');
    const live = render(<StopButton killSwitch={killSwitch('live', true) as any} lang="en" navigate={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Stop all agents' })).toBeNull();
    expect(screen.getByRole('link', { name: /All agents are halted/ })).toBeTruthy();
    live.unmount();
    const stale = killSwitch('stale', true);
    render(<StopButton killSwitch={stale as any} lang="en" navigate={vi.fn()} />);
    const stop = screen.getByRole('button', { name: 'Stop all agents' });
    expect(stop.getAttribute('data-stop')).toBe('stale-halted');
    expect(document.getElementById(stop.getAttribute('aria-describedby') as string)?.textContent)
      .toBe('The last reading (10:44) said every agent was halted; it is out of date, so the stop is offered again.');
    await act(async () => { fireEvent.click(stop); });
    expect(stale.stop).toHaveBeenCalledTimes(1);
  });
});
