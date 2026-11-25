/* The area page and the two pages built on it: PanelPage (a Console panel in its area) and
   ModePage (a mode, or the area-page empty state that replaces ModeEmpty). The contents column
   is the navigation engineer's ContentsColumn; /v2/console is its AllPages site map. */
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../gap', () => ({
  ConsolePanel: ({ panelId, showFailures }: { panelId: string; showFailures?: boolean }) =>
    <div data-testid="console-panel">{`${panelId}|failures:${showFailures !== false}`}</div>,
}));

import { usePageHeader } from '../page-header';
import { AllPages } from '../nav/AllPages';
import { pageForRoute } from '../nav/routes';
import { AreaPage, pageHeading } from './AreaPage';
import { ModePage, modePageState } from './ModePage';
import { PanelPage } from './PanelPage';

const common = { lang: 'en' as const, attention: {}, onFind: () => {} };

beforeEach(() => { history.replaceState(null, '', '/v2/trust?frame=ledger'); });
afterEach(() => { vi.restoreAllMocks(); });

describe('AreaPage', () => {
  it('titles a landing page with its area and a sub-page with its own label', () => {
    expect(pageHeading(pageForRoute({ mode: 'trust', panel: null }), 'en')).toBe('Trust');
    expect(pageHeading(pageForRoute({ mode: 'console', panel: 'kill-switch' }), 'en')).toBe('Emergency stop');
    expect(pageHeading(pageForRoute({ mode: 'console', panel: 'kill-switch' }), 'ro')).toBe('Oprire de urgență');
    // Home's landing is Today, as Home's own heading says ("Today — Monday, 23 November")
    expect(pageHeading(pageForRoute({ mode: 'cockpit', panel: null }), 'en')).toBe('Today');
    expect(pageHeading(pageForRoute({ mode: 'cockpit', panel: null }), 'ro')).toBe('Azi');
  });

  it('draws the page head, the area\'s contents and the body; a contents link navigates in the app', () => {
    const navigate = vi.fn();
    const onFind = vi.fn();
    render(<AreaPage page={pageForRoute({ mode: 'console', panel: 'kill-switch' })} navigate={navigate} {...common} onFind={onFind}><p>body</p></AreaPage>);
    expect(screen.getByRole('heading', { level: 1, name: 'Emergency stop' })).toBeTruthy();
    const contents = screen.getByRole('navigation', { name: 'Pages in Trust' });
    expect(contents.closest('.n-areapage__contents')).not.toBeNull();
    const current = within(contents).getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(current.map((a) => a.textContent)).toEqual(['Emergency stop']);
    expect(screen.getByText('body')).toBeTruthy();
    const payments = within(contents).getByRole('link', { name: 'Payments' });
    expect(payments.getAttribute('href')).toBe('/v2/console/payments?frame=ledger');
    fireEvent.click(payments);
    expect(navigate).toHaveBeenCalledWith('/v2/console/payments');
    // "Find a panel…" opens the search sheet filtered to panels
    fireEvent.click(within(contents).getByRole('button', { name: 'Find a panel…' }));
    expect(onFind).toHaveBeenCalledWith('panels');
  });

  it('puts the attention notes beside their pages, from what the frame read', () => {
    render(<AreaPage page={pageForRoute({ mode: 'trust', panel: null })} navigate={() => {}} {...common}
      attention={{ payments: { key: 'payments', count: 2 }, killSwitch: { key: 'killSwitch', state: 'armed' } }} />);
    const contents = screen.getByRole('navigation', { name: 'Pages in Trust' });
    expect(within(contents).getByRole('link', { name: /^Payments/ }).querySelector('[data-note]')).not.toBeNull();
    expect(within(contents).getByRole('link', { name: /^Emergency stop/ }).querySelector('[data-note]')).not.toBeNull();
    expect(within(contents).getByRole('link', { name: 'Permissions' }).querySelector('[data-note]')).toBeNull();
  });

  it('marks the page a duplicate stands for (the panel jobs is the mode jobs)', () => {
    render(<AreaPage page={pageForRoute({ mode: 'console', panel: 'jobs' })} navigate={() => {}} {...common} />);
    const current = screen.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page');
    expect(current.map((a) => a.getAttribute('data-page'))).toEqual(['mode:jobs']);
  });

  it('puts a page\'s own toolbar in the page head', () => {
    function Jobs() { usePageHeader(<button type="button">New job</button>, []); return <p>jobs</p>; }
    render(<AreaPage page={pageForRoute({ mode: 'jobs', panel: null })} navigate={() => {}} {...common}><Jobs /></AreaPage>);
    const head = document.querySelector('.n-areapage__head') as HTMLElement;
    expect(within(head).getByRole('button', { name: 'New job' })).toBeTruthy();
  });

  it('draws the empty state in place of the body, and keeps the contents usable', () => {
    const onDemo = vi.fn();
    render(<AreaPage page={pageForRoute({ mode: 'memory', panel: null })} navigate={() => {}} {...common} empty onDemo={onDemo}><p>hidden body</p></AreaPage>);
    expect(screen.queryByText('hidden body')).toBeNull();
    expect(screen.getByText('Nothing to show yet — this page’s source has not answered. It fills in when it does.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show a demo sample' }));
    expect(onDemo).toHaveBeenCalled();
    expect(screen.getByRole('navigation', { name: 'Pages in Memory' })).toBeTruthy();
  });

  it('lets an overflowing body with no control in it take the focus, named by the page title (WCAG 2.1.1)', async () => {
    // jsdom has no layout: give the body an overflow (and its controls a box) by hand
    const proto = HTMLElement.prototype;
    const overflow = (el: HTMLElement) => el.classList.contains('n-areapage__body');
    vi.spyOn(proto, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) { return overflow(this) ? 900 : 0; });
    vi.spyOn(proto, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) { return overflow(this) ? 400 : 0; });
    vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(function (this: Element) {
      return [{ width: 10, height: 10 }] as unknown as DOMRectList;
    });
    const view = render(<AreaPage page={pageForRoute({ mode: 'finance', panel: null })} navigate={() => {}} {...common}>
      <p>a long read-only page</p></AreaPage>);
    const body = document.querySelector('.n-areapage__body') as HTMLElement;
    body.style.overflowY = 'auto';
    // a recheck (the next frame after a change) sees the overflow and nothing to reach
    body.append(document.createElement('span'));
    await waitFor(() => expect(body.getAttribute('tabindex')).toBe('0'));
    expect(body.getAttribute('role')).toBe('group');
    expect(screen.getByRole('group', { name: 'Gecko · Finance' })).toBe(body);
    // a control inside: the body leaves the tab order, as it was
    view.rerender(<AreaPage page={pageForRoute({ mode: 'finance', panel: null })} navigate={() => {}} {...common}>
      <p>a long page</p><button type="button">Act</button></AreaPage>);
    await waitFor(() => expect(body.hasAttribute('tabindex')).toBe(false));
    expect(body.hasAttribute('role')).toBe(false);
  });

  it('leaves a body that does not overflow out of the tab order', async () => {
    render(<AreaPage page={pageForRoute({ mode: 'finance', panel: null })} navigate={() => {}} {...common}><p>short</p></AreaPage>);
    const body = document.querySelector('.n-areapage__body') as HTMLElement;
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    expect(body.hasAttribute('tabindex')).toBe(false);
    expect(body.hasAttribute('role')).toBe(false);
  });

  it('has no contents column on All pages, which lists every area\'s pages', () => {
    const navigate = vi.fn();
    render(<AreaPage page={pageForRoute({ mode: 'console', panel: null })} navigate={navigate} {...common}>
      <AllPages lang="en" navigate={navigate} attention={{}} /></AreaPage>);
    expect(screen.getByRole('heading', { level: 1, name: 'All pages' })).toBeTruthy();
    expect(document.querySelector('.n-areapage__contents')).toBeNull();
    expect(screen.queryByRole('navigation', { name: /^Pages in / })).toBeNull();
    const map = document.querySelector('[data-frame="allpages"]') as HTMLElement;
    expect(within(map).getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(
      ['Home', 'Work', 'Agents', 'Memory', 'Trust', 'Build', 'Connect', 'Observe', 'Settings']);
    const anchors = within(map).getByRole('link', { name: 'Audit anchors' });
    expect(anchors.getAttribute('href')).toBe('/v2/console/audit-anchors?frame=ledger');
    fireEvent.click(anchors);
    expect(navigate).toHaveBeenCalledWith('/v2/console/audit-anchors');
  });
});

describe('PanelPage', () => {
  it('renders the panel in its area, leaves failed actions to the notices, and moves focus to the heading', async () => {
    render(<PanelPage panelId="kill-switch" page={pageForRoute({ mode: 'console', panel: 'kill-switch' })} navigate={() => {}} {...common} />);
    expect(await screen.findByTestId('console-panel')).toHaveProperty('textContent', 'kill-switch|failures:false');
    const heading = screen.getByRole('heading', { level: 1, name: 'Emergency stop' });
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });
});

describe('ModePage', () => {
  it('draws a mode only when one of its sources is live, or in demo, and says which', () => {
    expect(modePageState(['MEMORY_STATS'], { MEMORY_STATS: true }, false)).toMatchObject({ empty: false, source: { state: 'live' } });
    expect(modePageState(['MEMORY_STATS'], {}, true)).toMatchObject({ empty: false, source: { state: 'demo' } });
    expect(modePageState(['MEMORY_STATS'], {}, false)).toMatchObject({ empty: true, source: { state: 'unknown' } });
    expect(modePageState(null, {}, false)).toEqual({ empty: false, source: null });
  });

  it('does not call a mode live while the hub itself is stale or offline, and invents no time for it', () => {
    expect(modePageState(['MEMORY_STATS'], { MEMORY_STATS: true }, false, 'live')).toMatchObject({ empty: false, source: { state: 'live' } });
    for (const hubState of ['stale', 'offline'] as const) {
      const { empty, source } = modePageState(['MEMORY_STATS'], { MEMORY_STATS: true }, false, hubState);
      expect(empty).toBe(false);
      expect(source).toMatchObject({ state: hubState, lastGoodAt: null, checkedAt: null });
    }
    // in demo the hub's reading is not consulted: the page is the demo sample
    expect(modePageState(['MEMORY_STATS'], {}, true, 'offline')).toMatchObject({ empty: false, source: { state: 'demo' } });
    render(<ModePage mode="memory" page={pageForRoute({ mode: 'memory', panel: null })} navigate={() => {}} {...common}
      demo={false} live={{ MEMORY_STATS: true }} onDemo={() => {}} liveKeys={['MEMORY_STATS']} hubState="offline"><p>memory mode</p></ModePage>);
    expect(document.querySelector('.n-areapage__meta [data-source-state]')?.getAttribute('data-source-state')).toBe('offline');
    expect(screen.getByText('memory mode')).toBeTruthy();
  });

  it('replaces ModeEmpty with the area-page empty state', () => {
    const onDemo = vi.fn();
    const { rerender } = render(<ModePage mode="memory" page={pageForRoute({ mode: 'memory', panel: null })} navigate={() => {}} {...common}
      demo={false} live={{}} onDemo={onDemo} liveKeys={['MEMORY_STATS']}><p>memory mode</p></ModePage>);
    expect(screen.queryByText('memory mode')).toBeNull();
    expect(document.querySelector('[data-empty]')).not.toBeNull();
    expect(document.querySelector('.n-areapage__head [data-source-state]')?.getAttribute('data-source-state')).toBe('unknown');
    rerender(<ModePage mode="memory" page={pageForRoute({ mode: 'memory', panel: null })} navigate={() => {}} {...common}
      demo={false} live={{ MEMORY_STATS: true }} onDemo={onDemo} liveKeys={['MEMORY_STATS']}><p>memory mode</p></ModePage>);
    expect(screen.getByText('memory mode')).toBeTruthy();
    expect(document.querySelector('.n-areapage__head [data-source-state]')?.getAttribute('data-source-state')).toBe('live');
  });

  it('always draws a mode without sources (the roster, projects, jobs, world signals)', () => {
    render(<ModePage mode="agents" page={pageForRoute({ mode: 'agents', panel: null })} navigate={() => {}} {...common}
      demo={false} live={{}} onDemo={() => {}}><p>roster</p></ModePage>);
    expect(screen.getByText('roster')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 1, name: 'Agents' })).toBeTruthy();
    expect(document.querySelector('.n-areapage__head [data-source-state]')).toBeNull();
  });
});
