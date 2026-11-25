/* The open entry's signature whole in the docket body's view as the docket first draws it
   (PHASE_B_PLAN.md §9.5: at 1280×800 "the open entry's SignLine is fully visible"; §5.1: from 1340px
   the open entry shown in full). The layout gives it the room in every look but one measured case:
   Classic, in Romanian, at 1280×800, the demo sample's sign line ended 3px below what the body shows,
   after the look's own term column (theme --n-term-max) gave back 46px. There the docket scrolls its body
   by what is hidden, only where the whole entry (its tier line first) stays in view, and only until the
   owner scrolls it or opens another entry (Docket.tsx useSignatureInView). Where the view is too short for
   the entry and its signature together (a phone), it scrolls nothing: the final gate found the first
   version scrolling 88-124px at 320 and 390px, and 62px in Classic, Romanian, at 1100px, which hid the
   docket's state line and the open entry's tier word ("Irreversible") at first paint and showed no more
   of the signature at a phone. Its repair stopped the scroll at the open entry's top, which still let it
   take 21-22px in Classic, English, at 1100×800 and cut the demo's state line ("Demo sample — signing is
   disabled."), which stands above the entry, under the register head's rule (the adversarial verifier of
   the final round). The scroll now takes only the blank above the body's first line, whatever draws it.

   jsdom lays nothing out: the geometry here is stubbed (the body's view, where the docket's state line's
   text, the open entry and its title start and where its signature ends, in the body's content), and the
   stub follows the body's scrollTop as a browser would. The render matrix (e2e/ledger-shots.spec.ts
   docket-1280, docket-sign) measures the real thing in every look. */
import React from 'react';
import { act, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetPolling } from '../signals/poll';
import { Docket, signatureScroll } from './Docket';

/** `state`: where the text of the docket's state line begins (its 12px top padding above it). */
type Geometry = { view: number; state: number; entry: number; title: number; sign: number };
let geometry: Geometry;
const scrolls = new WeakMap<Element, number>();
const observers: Array<() => void> = [];
const ORIGIN = 100;

const rect = (top: number, bottom: number) => ({ top, bottom, left: 0, right: 400, width: 400, height: bottom - top, x: 0, y: top, toJSON: () => ({}) }) as DOMRect;
const bodyEl = () => document.querySelector('[data-register="docket"] .n-register__body') as HTMLElement;

beforeEach(() => {
  resetPolling();
  observers.length = 0;
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) }) as unknown as Response));
  vi.stubGlobal('ResizeObserver', class {
    private readonly run: () => void;
    constructor(callback: () => void) { this.run = () => callback(); observers.push(this.run); }
    observe() {}
    unobserve() {}
    disconnect() { const at = observers.indexOf(this.run); if (at >= 0) observers.splice(at, 1); }
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollTop', {
    configurable: true,
    get(this: HTMLElement) { return scrolls.get(this) ?? 0; },
    set(this: HTMLElement, value: number) { scrolls.set(this, Math.max(0, value)); },
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get(this: HTMLElement) { return this.classList.contains('n-register__body') ? geometry.view : 0; },
  });
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    if (this.classList.contains('n-register__body')) return rect(ORIGIN, ORIGIN + geometry.view);
    const body = this.closest('.n-register__body');
    const scrolled = body ? scrolls.get(body) ?? 0 : 0;
    // the state line's box: its text starts `state` px down, below its own top padding (jsdom reads no
    // stylesheet, so the stub gives the content box)
    if (this.matches('.n-docket__state')) return rect(ORIGIN + geometry.state - scrolled, ORIGIN + geometry.state + 20 - scrolled);
    if (this.matches('.n-entry--open')) return rect(ORIGIN + geometry.entry - scrolled, ORIGIN + geometry.sign - scrolled);
    if (this.matches('.n-entry--open .n-entry__title')) return rect(ORIGIN + geometry.title - scrolled, ORIGIN + geometry.title + 54 - scrolled);
    if (this.matches('.n-entry--open :is(.n-signline, .n-entry__signrow)')) return rect(ORIGIN + geometry.sign - 52 - scrolled, ORIGIN + geometry.sign - scrolled);
    return rect(0, 0);
  });
});
afterEach(() => {
  resetPolling();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete (HTMLElement.prototype as { scrollTop?: unknown }).scrollTop;
  delete (HTMLElement.prototype as { clientHeight?: unknown }).clientHeight;
});

/** The window resized, a font arrived: what the docket's ResizeObservers see. */
const resize = () => act(() => { for (const run of [...observers]) run(); });

describe('signatureScroll', () => {
  it('scrolls by what is hidden, rounded up, and not at all when the signature is whole', () => {
    expect(signatureScroll(436, 439, 88)).toBe(3);
    expect(signatureScroll(436, 438.4, 88)).toBe(3);
    expect(signatureScroll(436, 425, 88)).toBe(0);
    expect(signatureScroll(436, 436, 88)).toBe(0);
  });

  it('scrolls only where the whole entry stays in view, its first line included, and never above the body\'s start', () => {
    expect(signatureScroll(436, 439, 40)).toBe(3);
    expect(signatureScroll(436, 439, 3)).toBe(3);
    expect(signatureScroll(436, 439, 2.6)).toBe(0);
    expect(signatureScroll(300, 439, 40)).toBe(0);
    expect(signatureScroll(436, 439, 0)).toBe(0);
  });

  it('takes only the blank above the body\'s first line: never the docket\'s state line (Classic, English, 1100×800: 22px hidden, the state line\'s text 12px down)', () => {
    expect(signatureScroll(418, 440, 12)).toBe(0);
    expect(signatureScroll(418, 430, 12)).toBe(12);
    expect(signatureScroll(418, 431, 12)).toBe(0);
  });

  it('scrolls nothing at a phone, where the signature lies far below the view (320px: 355px shown, signed 600px down)', () => {
    expect(signatureScroll(355, 960, 40)).toBe(0);
    expect(signatureScroll(418, 480, 40)).toBe(0);
  });
});

describe('the docket draws its open entry\'s signature whole in the body\'s view', () => {
  it('scrolls the body by what lies below its view, as first drawn (Classic, Romanian, 1280×800: 3px), the title still in view', () => {
    geometry = { view: 436, state: 12, entry: 40, title: 88, sign: 439 };
    render(<Docket lang="ro" demo navigate={vi.fn()} />);
    const body = bodyEl();
    expect(body.scrollTop).toBe(3);
    const title = body.querySelector('.n-entry--open .n-entry__title') as HTMLElement;
    const sign = body.querySelector('.n-entry--open .n-signline') as HTMLElement;
    expect(title.getBoundingClientRect().top).toBeGreaterThanOrEqual(ORIGIN);
    expect(sign.getBoundingClientRect().bottom).toBeLessThanOrEqual(ORIGIN + geometry.view);
  });

  it('scrolls nothing where the signature is whole (every other look and language)', () => {
    geometry = { view: 458, state: 12, entry: 40, title: 88, sign: 425 };
    render(<Docket lang="en" demo navigate={vi.fn()} />);
    expect(bodyEl().scrollTop).toBe(0);
  });

  it('scrolls nothing where the view is too short for the entry and its signature together (a phone): the docket\'s state line and the entry\'s tier word stay in view', () => {
    geometry = { view: 300, state: 12, entry: 40, title: 88, sign: 439 };
    render(<Docket lang="ro" demo navigate={vi.fn()} />);
    expect(bodyEl().scrollTop).toBe(0);
    // and a window resized down to it later leaves the body at its top too
    geometry = { ...geometry, view: 355, sign: 960 };
    resize();
    expect(bodyEl().scrollTop).toBe(0);
  });

  it('scrolls nothing where showing the signature would take the entry\'s first line out of view (Classic, Romanian, 1100px: 62px hidden, the entry 40px down)', () => {
    geometry = { view: 418, state: 12, entry: 40, title: 88, sign: 480 };
    render(<Docket lang="ro" demo navigate={vi.fn()} />);
    expect(bodyEl().scrollTop).toBe(0);
  });

  it('scrolls nothing where showing the signature would cut the docket\'s state line above the entry (Classic, English, 1100×800: 22px hidden, the entry 40px down, the state line\'s text 12px down)', () => {
    geometry = { view: 418, state: 12, entry: 40, title: 88, sign: 440 };
    render(<Docket lang="en" demo navigate={vi.fn()} />);
    const body = bodyEl();
    expect(body.scrollTop).toBe(0);
    const state = body.querySelector('.n-docket__state') as HTMLElement;
    expect(state.textContent).toMatch(/Demo sample/);
    expect(state.getBoundingClientRect().top).toBeGreaterThanOrEqual(ORIGIN);
    // and a window resized to it later scrolls nothing either
    geometry = { ...geometry, view: 436, sign: 439 };
    resize();
    expect(body.scrollTop).toBe(3);
    geometry = { ...geometry, view: 418, sign: 440 };
    resize();
    expect(body.scrollTop).toBe(0);
    expect(state.getBoundingClientRect().top).toBeGreaterThanOrEqual(ORIGIN);
  });

  it('follows the window until the owner scrolls: then a resize moves nothing', () => {
    geometry = { view: 436, state: 12, entry: 40, title: 88, sign: 439 };
    render(<Docket lang="ro" demo navigate={vi.fn()} />);
    const body = bodyEl();
    expect(body.scrollTop).toBe(3);
    // the window grows: the signature fits as first drawn, so the body goes back to its top
    geometry = { ...geometry, view: 530 };
    resize();
    expect(body.scrollTop).toBe(0);
    // and shrinks again
    geometry = { ...geometry, view: 430 };
    resize();
    expect(body.scrollTop).toBe(9);
    fireEvent.scroll(body);   // the docket's own scroll arriving: it changes nothing
    geometry = { ...geometry, view: 436 };
    resize();
    expect(body.scrollTop).toBe(3);
    fireEvent.scroll(body);
    // the owner scrolls the body: never undone
    body.scrollTop = 120;
    fireEvent.scroll(body);
    geometry = { ...geometry, view: 400 };
    resize();
    expect(body.scrollTop).toBe(120);
    geometry = { ...geometry, view: 530 };
    resize();
    expect(body.scrollTop).toBe(120);
  });

  it('leaves the body alone once another entry is opened', () => {
    geometry = { view: 436, state: 12, entry: 40, title: 88, sign: 439 };
    render(<Docket lang="ro" demo navigate={vi.fn()} />);
    const body = bodyEl();
    expect(body.scrollTop).toBe(3);
    fireEvent.scroll(body);
    const other = body.querySelector('[data-entry-state="closed"] .n-entry__open') as HTMLButtonElement;
    fireEvent.click(other);
    expect(body.querySelector('[data-entry-state="open"] .n-entry__title')?.textContent).toBe(other.textContent);
    geometry = { ...geometry, view: 300, sign: 520 };
    resize();
    expect(body.scrollTop).toBe(3);
  });
});
