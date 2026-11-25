import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stringProblems } from '../strings';
import { READING_STATES, type Reading } from '../../signals/types';
import {
  Consequence, Disclosure, HAND_MARKS, KEY_MARKS, KIT_STRINGS, MARK_KINDS, MARK_STRINGS, Mark, MarksKey, Register, SecHead,
  SourceLabel, TIER_STRINGS, TierGlyph, Total, basisWords, clockTime, markWord, reasonWords, stateWord,
} from './index';
import { CUT_TITLE_ATTRIBUTE, HEAD_ROW_PROPERTY, useHeadRow } from './Register';

const at = (h: number, m: number) => new Date(2026, 10, 23, h, m).getTime();
const label = (reading: Partial<Reading<unknown>> & Pick<Reading<unknown>, 'state'>, lang = 'en', verb?: 'checked' | 'verified') => {
  const { container } = render(<SourceLabel reading={{ lastGoodAt: null, ...reading }} lang={lang} verb={verb} />);
  const el = container.querySelector('.n-src') as HTMLElement;
  return { text: el.textContent, state: el.getAttribute('data-source-state'), mark: el.querySelector('[data-mark]')?.getAttribute('data-mark') ?? null };
};

describe('the kit\'s strings', () => {
  it('are complete in English and Romanian', () => {
    expect(stringProblems(MARK_STRINGS)).toEqual([]);
    expect(stringProblems(TIER_STRINGS)).toEqual([]);
    expect(stringProblems(KIT_STRINGS)).toEqual([]);
  });
});

describe('Mark', () => {
  it('has a word for every mark, in both languages, and writes it when asked', () => {
    for (const kind of MARK_KINDS) {
      for (const lang of ['en', 'ro']) {
        const word = markWord(kind, lang);
        expect(word.trim(), `${kind} ${lang}`).not.toBe('');
        const { container, unmount } = render(<Mark kind={kind} lang={lang} word />);
        expect(container.textContent).toBe(word);
        expect(container.querySelector(`svg[data-mark="${kind}"]`)?.getAttribute('aria-hidden')).toBe('true');
        unmount();
      }
    }
    expect(markWord('idle', 'en')).toBe('No activity reported');
    expect(Object.values(MARK_STRINGS.en)).not.toContain('Idle');
  });

  it('is hidden beside its word, and named when it stands alone', () => {
    const { container } = render(<><Mark kind="ok" /><Mark kind="problem" label /><Mark kind="seal-open" label lang="ro" /></>);
    expect(container.querySelector('[data-mark="ok"]')?.getAttribute('aria-hidden')).toBe('true');
    expect(screen.getByRole('img', { name: 'Problem' })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Așteaptă semnătura ta' })).toBeTruthy();
  });

  it('spends the accent only on the owner\'s hand, and draws the chain\'s seal in ink', () => {
    expect([...HAND_MARKS].sort()).toEqual(['seal', 'seal-open']);
    for (const kind of MARK_KINDS) {
      const { container, unmount } = render(<Mark kind={kind} />);
      const svg = container.querySelector('svg') as SVGElement;
      expect(svg.classList.contains('n-mk--hand'), kind).toBe(kind === 'seal' || kind === 'seal-open');
      expect(svg.classList.contains('n-mk--chain'), kind).toBe(kind === 'chain');
      expect(svg.childNodes.length, kind).toBeGreaterThan(0);
      unmount();
    }
  });
});

describe('TierGlyph', () => {
  it('draws three bars and names the tier; an unknown tier is the strictest and says unknown', () => {
    const cases: Array<[unknown, boolean, string, number]> = [
      [0, false, 'Read only', 0], [1, false, 'Reversible', 1], [2, false, 'External', 2], [3, false, 'Irreversible', 3],
      [3, true, 'Money', 3], [7, false, 'Unknown risk', 3], [null, false, 'Unknown risk', 3], ['3', false, 'Unknown risk', 3],
    ];
    for (const [tier, money, word, bars] of cases) {
      const { container, unmount } = render(<TierGlyph tier={tier} money={money} word />);
      const el = container.querySelector('.n-tier') as HTMLElement;
      expect(el.textContent, String(tier)).toBe(word);
      expect(el.getAttribute('data-bars'), String(tier)).toBe(String(bars));
      expect(container.querySelectorAll('rect[fill="currentColor"]').length, String(tier)).toBe(bars);
      unmount();
    }
    render(<TierGlyph tier={2} lang="ro" />);
    expect(screen.getByRole('img', { name: 'Extern' })).toBeTruthy();
  });
});

describe('SourceLabel', () => {
  it('says every reading state in words, with its time, and never a number for unknown', () => {
    expect(label({ state: 'live', lastGoodAt: at(10, 50) })).toEqual({ text: 'Live · checked 10:50', state: 'live', mark: 'ok' });
    expect(label({ state: 'live', lastGoodAt: at(10, 50) }, 'en', 'verified').text).toBe('Live · verified 10:50');
    expect(label({ state: 'empty', lastGoodAt: at(10, 50) })).toEqual({ text: 'Empty · checked 10:50', state: 'empty', mark: null });
    expect(label({ state: 'stale', lastGoodAt: at(9, 12) })).toEqual({ text: 'Stale · checked 09:12', state: 'stale', mark: 'stale' });
    expect(label({ state: 'unknown', reason: 'checking' })).toEqual({ text: 'Checking…', state: 'unknown', mark: 'unknown' });
    expect(label({ state: 'unknown', reason: 'http', status: 500 }).text).toBe('Unknown — the hub answered 500');
    expect(label({ state: 'unknown', reason: 'not-measured' }).text).toBe('Unknown — not measured');
    expect(label({ state: 'refused', reason: 'credential', status: 401 })).toEqual({ text: 'Refused — needs the owner credential', state: 'refused', mark: 'blocked' });
    expect(label({ state: 'offline', reason: 'network', lastGoodAt: at(10, 44) })).toEqual({ text: 'Offline · last good reading 10:44', state: 'offline', mark: 'unknown' });
    expect(label({ state: 'offline', reason: 'network' }).text).toBe('Offline');
    expect(label({ state: 'demo' })).toEqual({ text: 'Demo sample', state: 'demo', mark: null });
    expect(label({ state: 'disabled' })).toEqual({ text: 'Off', state: 'disabled', mark: 'idle' });
    for (const state of READING_STATES) {
      const { text } = label({ state, reason: state === 'unknown' ? 'checking' : undefined });
      expect(text, state).not.toMatch(/^\s*0\b/);
    }
  });

  it('speaks Romanian', () => {
    expect(label({ state: 'live', lastGoodAt: at(10, 50) }, 'ro').text).toBe('În direct · actualizat la 10:50');
    expect(label({ state: 'refused', reason: 'credential' }, 'ro').text).toBe('Refuzat — necesită credențialul proprietarului');
    expect(label({ state: 'demo' }, 'ro').text).toBe('Mostră demo');
  });

  it('has words for states, reasons and bases', () => {
    expect(stateWord('offline')).toBe('Offline');
    expect(reasonWords('http', 'en')).toBe('the hub answered with an error');
    expect(reasonWords(undefined)).toBeNull();
    expect(basisWords('declared')).toBe('declared, not measured');
    expect(basisWords('seeded', 'ro')).toBe('mostră demo');
    expect(clockTime(at(7, 5))).toBe('07:05');
  });
});

describe('Register, SecHead, Total', () => {
  it('draw a titled register with its hook, meta, scrolling body and foot', () => {
    render(
      <Register title="Docket" meta={<span>Live</span>} register="docket" bodyProps={{ role: 'log', tabIndex: 0 }} foot={<Total aside="Open">6 entries</Total>}>
        <SecHead title="Other things waiting" aside="2" />
        <p>entry</p>
      </Register>,
    );
    const region = screen.getByRole('region', { name: 'Docket' });
    expect(region.getAttribute('data-register')).toBe('docket');
    expect(region.querySelector('.n-register__meta')?.textContent).toBe('Live');
    expect(screen.getByRole('log').classList.contains('n-register__body')).toBe(true);
    expect(screen.getByRole('heading', { level: 3, name: 'Other things waiting' }).className).toBe('n-sec__title');
    const total = region.querySelector('.n-register__foot .n-total') as HTMLElement;
    expect(total.textContent).toBe('6 entriesOpen');
  });

  it('keep the body and the foot in one box after the head, so a spread of registers can share a row for the heads', () => {
    const { container } = render(
      <Register title="Docket" meta="Live" register="docket" foot={<Total>6 entries</Total>}><p>entry</p></Register>,
    );
    const register = container.querySelector('[data-register="docket"]') as HTMLElement;
    expect([...register.children].map((el) => el.className)).toEqual(['n-register__head', 'n-register__main']);
    const main = register.children[1] as HTMLElement;
    expect([...main.children].map((el) => el.className)).toEqual(['n-register__body', 'n-register__foot']);
    expect(main.querySelector('.n-register__body')?.textContent).toBe('entry');
    // without a foot, the body alone
    cleanup();
    const bare = render(<Register title="Agents" register="record">x</Register>);
    expect([...(bare.container.querySelector('.n-register__main') as HTMLElement).children].map((el) => el.className)).toEqual(['n-register__body']);
  });
});

/* Registers side by side that keep their own heights (Trust's columns) give their heads one height
   (Register.tsx useHeadRow): the review of the heads' round found Trust's record head 16px taller than
   "Your authority" where its meta drops under its title (Classic at 1340-1440px), the rules under them
   16px apart. jsdom lays nothing out, so each head's box is given (by its register's hook): where it
   stands, and its own height, which the shared height (HEAD_ROW_PROPERTY) can only raise. */
describe('useHeadRow', () => {
  type Box = { top: number; left: number; natural: number };
  let boxes: Record<string, Box>;
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      const box = this.classList.contains('n-register__head') ? boxes[this.parentElement?.getAttribute('data-register') ?? ''] : undefined;
      if (!box) return { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON() { return this; } } as DOMRect;
      const height = Math.max(box.natural, parseFloat(this.style.getPropertyValue(HEAD_ROW_PROPERTY)) || 0);
      return { left: box.left, top: box.top, right: box.left + 400, bottom: box.top + height, width: 400, height, x: box.left, y: box.top, toJSON() { return this; } } as DOMRect;
    });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  function Columns({ meta = true }: { meta?: boolean }) {
    const row = React.useRef<HTMLDivElement>(null);
    useHeadRow(row);
    return (
      <div ref={row}>
        <div><Register title="The record" register="record" meta={meta ? <span>Audit chain · every action, sealed</span> : undefined}>x</Register></div>
        <div><Register title="Your authority" register="authority" meta={<span>Approval mode: Ask</span>}>y</Register></div>
      </div>
    );
  }
  const shared = (container: HTMLElement, register: string) =>
    (container.querySelector(`[data-register="${register}"] > .n-register__head`) as HTMLElement).style.getPropertyValue(HEAD_ROW_PROPERTY);

  it('holds every head beside a taller one up to its height, so the rules under them lie on one line', () => {
    boxes = { record: { top: 120, left: 0, natural: 74 }, authority: { top: 120, left: 460, natural: 58 } };
    const { container } = render(<Columns />);
    expect(shared(container, 'record')).toBe('74px');
    expect(shared(container, 'authority')).toBe('74px');
  });

  it('adds nothing while the heads are level, and leaves registers one under another to their own heads', () => {
    boxes = { record: { top: 120, left: 0, natural: 58 }, authority: { top: 120, left: 460, natural: 58 } };
    const level = render(<Columns />);
    expect(shared(level.container, 'record')).toBe('');
    expect(shared(level.container, 'authority')).toBe('');
    cleanup();
    boxes = { record: { top: 120, left: 0, natural: 74 }, authority: { top: 900, left: 0, natural: 58 } };
    const stacked = render(<Columns />);
    expect(shared(stacked.container, 'record')).toBe('');
    expect(shared(stacked.container, 'authority')).toBe('');
  });

  it('measures again when a head changes, lets the heads go back to their own height, and leaves nothing when it ends', async () => {
    boxes = { record: { top: 120, left: 0, natural: 74 }, authority: { top: 120, left: 460, natural: 58 } };
    const { container, rerender, unmount } = render(<Columns />);
    expect(shared(container, 'authority')).toBe('74px');
    // the record's meta is no longer drawn: its head is a title alone again
    boxes.record.natural = 58;
    rerender(<Columns meta={false} />);
    await act(async () => { await Promise.resolve(); });
    expect(shared(container, 'record')).toBe('');
    expect(shared(container, 'authority')).toBe('');
    boxes.record.natural = 90;
    rerender(<Columns />);
    await act(async () => { await Promise.resolve(); });
    expect(shared(container, 'authority')).toBe('90px');
    const heads = [...container.querySelectorAll('.n-register__head')] as HTMLElement[];
    unmount();
    for (const head of heads) expect(head.style.getPropertyValue(HEAD_ROW_PROPERTY)).toBe('');
  });
});

/* A part of a head's flow (an aside's, a meta's, a total half's) that is cut with an ellipsis keeps its
   whole text in a tooltip (Register.tsx useCutTitles): the last gate found "While you were away"'s
   aside cut by its register with no way to read it. jsdom lays nothing out, so a part's widths are
   given (data-scroll: what it holds, data-client: what it shows, in whole pixels, as textCut reads them
   where there is no Range geometry). */
describe('a part cut with an ellipsis', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) { return Number(this.getAttribute('data-scroll') ?? 0); });
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) { return Number(this.getAttribute('data-client') ?? 0); });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('keeps its whole text in its title, in a section head\'s aside; a whole part has none', () => {
    const { container } = render(
      <SecHead title="While you were away" aside={(
        <>
          <span data-scroll="180" data-client="180">since 00:00 (start of today)</span>
          <span className="n-src" data-scroll="296" data-client="240"><span className="n-src__word">Unknown</span><span className="n-src__why">{' — switched off on the hub'}</span></span>
        </>
      )} />,
    );
    const [since, source] = [...container.querySelectorAll('.n-sec__aside > *')] as HTMLElement[];
    expect(since.hasAttribute('title')).toBe(false);
    expect(source.getAttribute('title')).toBe('Unknown — switched off on the hub');
    expect(source.hasAttribute(CUT_TITLE_ATTRIBUTE)).toBe(true);
    // the text itself, which a reader of the page hears, is whole
    expect(source.textContent).toBe('Unknown — switched off on the hub');
  });

  it('loses the title once it is whole again, and follows its words while it is cut', async () => {
    const aside = (words: string, cut: boolean) => <span data-scroll={cut ? '300' : '120'} data-client="200">{words}</span>;
    const { container, rerender } = render(<SecHead title="Today" aside={aside('Refused — needs the owner credential', true)} />);
    const part = () => container.querySelector('.n-sec__aside > span') as HTMLElement;
    expect(part().getAttribute('title')).toBe('Refused — needs the owner credential');
    rerender(<SecHead title="Today" aside={aside('Refuzat — necesită credențialul proprietarului', true)} />);
    await act(async () => { await Promise.resolve(); });
    expect(part().getAttribute('title')).toBe('Refuzat — necesită credențialul proprietarului');
    rerender(<SecHead title="Today" aside={aside('Live · checked 10:50', false)} />);
    await act(async () => { await Promise.resolve(); });
    expect(part().hasAttribute('title')).toBe(false);
    expect(part().hasAttribute(CUT_TITLE_ATTRIBUTE)).toBe(false);
  });

  it('keeps its whole text in its title in a register\'s meta, and leaves a title the page gave a part as it is', () => {
    const { container } = render(
      <Register title="The record" meta={(
        <>
          <span data-scroll="320" data-client="276">Audit chain · every action, sealed</span>
          <span title="Routing policy: not served" data-scroll="320" data-client="276">Routing policy unknown</span>
          <span data-scroll="90" data-client="90">Live</span>
        </>
      )}>x</Register>,
    );
    const [chain, policy, live] = [...container.querySelectorAll('.n-register__meta > *')] as HTMLElement[];
    expect(chain.getAttribute('title')).toBe('Audit chain · every action, sealed');
    expect(policy.getAttribute('title')).toBe('Routing policy: not served');
    expect(policy.hasAttribute(CUT_TITLE_ATTRIBUTE)).toBe(false);
    expect(live.hasAttribute('title')).toBe(false);
  });

  it('keeps its whole text in its title in either half of a total', () => {
    const { container } = render(
      <Total aside={<span data-scroll="260" data-client="200">4 typed · 2 two-step · 0 one click</span>}>
        <b data-scroll="40" data-client="40">6 entries</b>
        <span data-scroll="220" data-client="150">9 requests from four agents</span>
      </Total>,
    );
    const [entries, requests] = [...container.querySelectorAll('.n-total__main > *')] as HTMLElement[];
    expect(entries.hasAttribute('title')).toBe(false);
    expect(requests.getAttribute('title')).toBe('9 requests from four agents');
    expect((container.querySelector('.n-total__aside > span') as HTMLElement).getAttribute('title')).toBe('4 typed · 2 two-step · 0 one click');
  });
});

describe('Consequence', () => {
  it('draws a row only if its field exists', () => {
    const { container } = render(<Consequence rows={[
      { term: 'If you sign', detail: 'Would run: restart' },
      { term: 'To undo', detail: null },
      { term: 'If you wait', detail: undefined },
      { term: 'Deadline', detail: '' },
      { term: 'Opinion', detail: false },
    ]} />);
    expect([...container.querySelectorAll('dt')].map((dt) => dt.textContent)).toEqual(['If you sign']);
    expect(container.querySelector('dd')?.textContent).toBe('Would run: restart');
    const empty = render(<Consequence rows={[{ term: 'To undo', detail: null }]} />);
    expect(empty.container.innerHTML).toBe('');
  });
});

describe('Disclosure', () => {
  it('opens on click, closes on Escape back to its button, and on a press elsewhere', () => {
    render(<><Disclosure label="Egress" title="Basis: declared">A setting, not a network measurement.</Disclosure><button>outside</button></>);
    const button = screen.getByRole('button', { name: 'Egress' });
    const panel = document.getElementById(button.getAttribute('aria-controls') as string) as HTMLElement;
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(panel.hidden).toBe(true);
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    expect(panel.hidden).toBe(false);
    fireEvent.keyDown(panel, { key: 'Escape' });
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    fireEvent.mouseDown(screen.getByRole('button', { name: 'outside' }));
    expect(panel.hidden).toBe(true);
    expect(button.title).toBe('Basis: declared');
  });

  /* `contain` (the running head's popovers, which sit at the bottom of Glance's sheet): jsdom lays
     nothing out, so the window and the popover's box are given. */
  describe('kept inside the window', () => {
    const view = { width: 420, height: 800 };
    /** Where the popover would be: below its button (`below`), or above it once data-place says so. */
    let below: { left: number; top: number; width: number; height: number };
    let above: { left: number; top: number; width: number; height: number };
    const rect = (r: typeof below) => ({ ...r, x: r.left, y: r.top, right: r.left + r.width, bottom: r.top + r.height, toJSON() { return this; } }) as DOMRect;
    beforeEach(() => {
      vi.spyOn(document.documentElement, 'clientWidth', 'get').mockImplementation(() => view.width);
      vi.spyOn(document.documentElement, 'clientHeight', 'get').mockImplementation(() => view.height);
      vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
        if (!this.classList.contains('n-disclosure__panel')) return rect({ left: 0, top: 0, width: 0, height: 0 });
        const r = this.getAttribute('data-place') === 'above' ? above : below;
        const shift = parseFloat(this.style.getPropertyValue('--n-disclosure-shift')) || 0;
        return rect({ ...r, left: r.left + shift });
      });
    });
    afterEach(() => { vi.restoreAllMocks(); });
    const open = (contain = true) => {
      render(<Disclosure label="Model" contain={contain}>gemma-4-31b · ollama</Disclosure>);
      const button = screen.getByRole('button', { name: 'Model' });
      fireEvent.click(button);
      return document.getElementById(button.getAttribute('aria-controls') as string) as HTMLElement;
    };

    it('opens below its button where it fits there', () => {
      below = { left: 20, top: 300, width: 300, height: 120 };
      above = { left: 20, top: 100, width: 300, height: 120 };
      const panel = open();
      expect(panel.hasAttribute('data-place')).toBe(false);
      expect(panel.hasAttribute('data-shift')).toBe(false);
    });

    it('opens above its button where below would leave the window (a foot at the bottom of the screen)', () => {
      below = { left: 20, top: 760, width: 300, height: 140 };
      above = { left: 20, top: 580, width: 300, height: 140 };
      const panel = open();
      expect(panel.getAttribute('data-place')).toBe('above');
      // and stays below where above would leave even more of it out
      cleanup();
      below = { left: 20, top: 700, width: 300, height: 140 };
      above = { left: 20, top: -300, width: 300, height: 140 };
      expect(open().hasAttribute('data-place')).toBe(false);
    });

    it('moves in from the side it would cross, by a translation, and only as far as needed', () => {
      below = { left: 300, top: 200, width: 260, height: 100 };
      above = below;
      const panel = open();
      expect(panel.hasAttribute('data-shift')).toBe(true);
      expect(panel.style.getPropertyValue('--n-disclosure-shift')).toBe(`${420 - 4 - 560}px`);
      // closed, it is placed afresh the next time it opens
      fireEvent.keyDown(panel, { key: 'Escape' });
      expect(panel.hasAttribute('data-shift')).toBe(false);
    });

    it('is left where its stylesheet puts it without `contain` (the day band\'s)', () => {
      below = { left: 300, top: 760, width: 260, height: 140 };
      above = { left: 300, top: 580, width: 260, height: 140 };
      const panel = open(false);
      expect(panel.hasAttribute('data-place')).toBe(false);
      expect(panel.hasAttribute('data-shift')).toBe(false);
    });
  });
});

describe('MarksKey', () => {
  it('lists every mark it explains with its word, and the source labels', () => {
    const { container } = render(<MarksKey />);
    expect(screen.getByRole('heading', { name: 'Key' })).toBeTruthy();
    const rows = [...container.querySelectorAll('[data-mark-key]')];
    expect(rows.map((r) => r.getAttribute('data-mark-key'))).toEqual([...KEY_MARKS]);
    for (const row of rows) expect(row.textContent).toBe(markWord(row.getAttribute('data-mark-key') as any, 'en'));
    expect(container.querySelector('.n-key__sources')?.textContent).toBe('LiveDemo sampleEmpty');
  });
});
