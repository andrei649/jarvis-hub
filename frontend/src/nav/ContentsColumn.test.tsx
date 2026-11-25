import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AllPages } from './AllPages';
import { ContentsColumn } from './ContentsColumn';
import { AREAS, PAGES, areaById, pageForMode, pageForPanel, type PageEntry } from './areas';
import { contentsModel, currentKeyOf } from './contents-model';
import type { Attention } from '../signals/types';

const area = (id: string) => areaById(id)!;
function column(areaId: string, current: PageEntry, over: Partial<React.ComponentProps<typeof ContentsColumn>> = {}) {
  const navigate = vi.fn();
  const onFind = vi.fn();
  render(<ContentsColumn area={area(areaId)} current={current} lang="en" attention={{}} navigate={navigate} onFind={onFind} {...over} />);
  return { navigate, onFind };
}
const hrefs = () => screen.getAllByRole('link').map((a) => a.getAttribute('data-page'));

beforeEach(() => { localStorage.clear(); history.replaceState(null, '', '/v2/trust?demo=1'); });

describe('contentsModel', () => {
  it('lists only listed pages, primary first, and counts the rest as more', () => {
    for (const a of AREAS) {
      const model = contentsModel(a, null);
      const listed = a.pages.filter((p) => p.listed);
      expect(model.total, a.id).toBe(listed.length);
      expect(model.groups.flatMap((g) => [...g.primary, ...g.more]).map((i) => i.entry.key).sort(), a.id).toEqual(listed.map((p) => p.key).sort());
      expect(model.moreCount, a.id).toBe(listed.filter((p) => !p.primary).length);
      expect(model.groups.flatMap((g) => g.primary).every((i) => i.entry.primary), a.id).toBe(true);
    }
    expect(contentsModel(area('home'), null).groups.flatMap((g) => [...g.primary, ...g.more]).some((i) => i.entry.key === 'mode:glance')).toBe(false);
  });

  it('marks a duplicate\'s original as current', () => {
    const dup = pageForPanel('jobs')!;
    expect(dup.duplicateOf).toEqual({ kind: 'mode', id: 'jobs' });
    expect(currentKeyOf(dup)).toBe('mode:jobs');
    expect(contentsModel(area('work'), dup).currentKey).toBe('mode:jobs');
  });
});

describe('ContentsColumn', () => {
  it('is a labelled nav with the area, its page count and its groups', () => {
    column('trust', pageForMode('trust')!);
    const nav = screen.getByRole('navigation', { name: 'Pages in Trust' });
    expect(within(nav).getByRole('heading', { level: 2, name: 'Trust' })).toBeTruthy();
    expect(nav.textContent).toMatch(/\d+ pages/);
    const model = contentsModel(area('trust'), null);
    for (const g of model.groups) {
      if (g.label) expect(within(nav).queryAllByText(g.label.en).length > 0, g.label.en).toBe(g.primary.length > 0);
    }
    expect(within(nav).getAllByText('Your authority').length).toBeGreaterThan(0);
  });

  it('marks the current page, and draws real links that keep the query', () => {
    column('trust', pageForMode('trust')!);
    const current = screen.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(current.map((a) => a.getAttribute('data-page'))).toEqual(['mode:trust']);
    const link = document.querySelector('[data-page="panel:payments"]') as HTMLAnchorElement | null;
    // payments is a primary page of Trust: its href is the console path with the query kept
    expect(link?.getAttribute('href')).toBe('/v2/console/payments?demo=1');
  });

  it('hides the pages behind "N more pages" and shows them on request', () => {
    column('trust', pageForMode('trust')!);
    const model = contentsModel(area('trust'), null);
    expect(model.moreCount).toBeGreaterThan(0);
    const button = screen.getByRole('button', { name: new RegExp(`^${model.moreCount} more pages?$`) });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(hrefs()).toHaveLength(model.total - model.moreCount);
    fireEvent.click(button);
    expect(hrefs()).toHaveLength(model.total);
    expect(screen.getByRole('button', { name: 'Show fewer pages' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('opens the rest by itself when the current page sits behind it', () => {
    const behind = PAGES.find((p) => p.area === 'trust' && p.listed && !p.primary)!;
    column('trust', behind);
    expect(screen.getByRole('button', { name: 'Show fewer pages' })).toBeTruthy();
    expect(document.querySelector(`[data-page="${behind.key}"]`)?.getAttribute('aria-current')).toBe('page');
  });

  it('on the jobs duplicate marks the page it duplicates', () => {
    column('work', pageForPanel('jobs')!);
    expect(screen.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page').map((a) => a.getAttribute('data-page'))).toEqual(['mode:jobs']);
    expect(document.querySelector('[data-page="panel:jobs"]')).toBeNull();
  });

  it('lists Home\'s sub-pages, not Glance', () => {
    column('home', pageForPanel('today')!);
    expect(document.querySelector('[data-page="panel:today"]')?.getAttribute('aria-current')).toBe('page');
    expect(document.querySelector('[data-page="mode:chat"]')).not.toBeNull();
    expect(document.querySelector('[data-page="mode:glance"]')).toBeNull();
  });

  it('says where the rest are, and finds a panel through the sheet', () => {
    const { onFind, navigate } = column('trust', pageForMode('trust')!);
    const total = contentsModel(area('trust'), null).total;
    expect(screen.getByRole('navigation').textContent).toContain(`finds any of the ${total}`);
    expect(screen.getByRole('navigation').querySelector('kbd')?.textContent).toMatch(/K$/i);
    fireEvent.click(screen.getByRole('button', { name: 'Find a panel…' }));
    expect(onFind).toHaveBeenCalledWith('panels');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('navigates on a plain click and leaves a modified click to the browser', () => {
    const { navigate } = column('trust', pageForMode('trust')!);
    const link = document.querySelector('[data-page="panel:payments"]') as HTMLElement;
    const hold = (e: Event) => e.preventDefault();   // jsdom does not navigate; keep its notice out of the log
    document.addEventListener('click', hold);
    fireEvent.click(link, { ctrlKey: true });
    fireEvent.click(link, { button: 1 });
    document.removeEventListener('click', hold);
    expect(navigate).not.toHaveBeenCalled();
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith('/v2/console/payments');
  });

  describe('notes', () => {
    const note = (k: string) => document.querySelector(`[data-page="${k}"] [data-note]`);

    it('draw nothing without a live value: unknown is no number', () => {
      column('work', pageForMode('work')!);
      expect(document.querySelectorAll('[data-note]')).toHaveLength(0);
      expect(document.body.textContent).not.toMatch(/\b0 need/);
    });

    it('show the docket beside Decisions in the owner\'s hand, and the long words for assistive tech', () => {
      column('work', pageForMode('work')!, { attention: { docket: { key: 'docket', count: 9 } } as Attention });
      const n = note('panel:decision-inbox')!;
      expect(n.getAttribute('data-hand')).toBe('true');
      expect(n.textContent).toContain('9');
      expect(n.querySelector('[data-visually-hidden]')?.textContent).toBe('9 need you');
      expect(n.querySelector('[aria-hidden="true"]')?.textContent).toBe('9');
    });

    it('show payments waiting and the stop\'s word beside their pages', () => {
      column('trust', pageForMode('trust')!, { attention: {
        payments: { key: 'payments', count: 1 }, killSwitch: { key: 'killSwitch', state: 'unknown' },
      } as Attention });
      expect(note('panel:payments')?.textContent).toContain('1 waits');
      expect(note('panel:kill-switch')?.textContent).toContain('Unknown');
      expect(note('panel:kill-switch')?.querySelector('[data-mark="unknown"]')).not.toBeNull();
      expect(note('panel:payments')?.getAttribute('data-hand')).toBe('true');
    });
  });

  it('speaks Romanian: labels, count and the Find line', () => {
    column('trust', pageForMode('trust')!, { lang: 'ro' });
    const nav = screen.getByRole('navigation', { name: 'Paginile din Încredere' });
    expect(within(nav).getByRole('heading', { level: 2 }).textContent).toBe('Încredere');
    expect(nav.textContent).toMatch(/găsește oricare dintre cele/);
    expect(within(nav).getByRole('button', { name: 'Caută un panou…' })).toBeTruthy();
  });
});

describe('AllPages', () => {
  beforeEach(() => { global.fetch = vi.fn(); history.replaceState(null, '', '/v2/console?demo=1'); });

  it('is a link for every listed page of every area, and mounts and asks for nothing', () => {
    const navigate = vi.fn();
    render(<AllPages lang="en" navigate={navigate} />);
    const listed = PAGES.filter((p) => p.listed);
    expect(screen.getAllByRole('link')).toHaveLength(listed.length);
    for (const p of listed) expect(document.querySelector(`[data-page="${p.key}"]`), p.key).not.toBeNull();
    expect(document.querySelector('[data-page="mode:glance"]')).toBeNull();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(AREAS.map((a) => a.label.en));
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('opens a page in place and keeps the query on its href', () => {
    const navigate = vi.fn();
    render(<AllPages lang="en" navigate={navigate} />);
    const link = document.querySelector('[data-page="panel:logs"]') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe('/v2/console/logs?demo=1');
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith('/v2/console/logs');
  });

  it('shows a note only for a live value, and speaks Romanian', () => {
    const { rerender } = render(<AllPages lang="ro" navigate={vi.fn()} />);
    expect(document.querySelectorAll('[data-note]')).toHaveLength(0);
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toContain('Încredere');
    rerender(<AllPages lang="ro" navigate={vi.fn()} attention={{ docket: { key: 'docket', count: 2 } } as Attention} />);
    expect(document.querySelector('[data-page="panel:decision-inbox"] [data-note]')).not.toBeNull();
  });
});

describe('page links leave the page being left behind', () => {
  it('drops a Decisions card and the hash, keeps the context', async () => {
    const { pageHref } = await import('../hud-routing');
    window.history.replaceState(null, '', '/v2/console/decision-inbox?card=5&demo=1&frame=ledger#docket-entry-42');
    expect(pageHref('/v2/trust')).toBe('/v2/trust?demo=1&frame=ledger');
    window.history.replaceState(null, '', '/');
  });
});
