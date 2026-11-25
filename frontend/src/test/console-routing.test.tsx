/* The Console as pages (PHASE_B_PLAN.md §3.2, §3.3, §8.3; ported from the Console overlay's tests
   when the overlay was deleted): /v2/console is All pages, a site map that offers a bookmark link
   for every panel without mounting or fetching any of them; /v2/console/<id> is that panel as a
   page of its area, which takes the focus on its own heading and only reads when it opens; and the
   site map's links move through the History API. */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { CONSOLE_PANELS } from '../console-routes';
import { PanelPage } from '../frame/PanelPage';
import { navigateHud, parseHudRoute } from '../hud-routing';
import { AllPages } from '../nav/AllPages';
import { pageForPanel, pageKey } from '../nav/areas';
import { pageForRoute, pathOf } from '../nav/routes';

beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, '', '/v2/console?demo=1#anchor');
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
});

it('offers a bookmark link for every panel without mounting or fetching any panel', () => {
  render(<AllPages lang="en" navigate={navigateHud} />);
  const map = document.querySelector('[data-frame="allpages"]') as HTMLElement;
  for (const panel of CONSOLE_PANELS) {
    const entry = pageForPanel(panel.id);
    expect(entry, panel.id).not.toBeNull();
    // a declared duplicate (the jobs panel is the jobs mode) is listed once, as the page it duplicates
    const ref = entry!.duplicateOf ?? entry!.ref;
    const link = map.querySelector(`a[data-page="${pageKey(ref)}"]`) as HTMLAnchorElement | null;
    expect(link, panel.id).not.toBeNull();
    // the site map keeps the context (demo) and drops what belongs to the page it leaves (the hash)
    expect(link!.getAttribute('href'), panel.id).toBe(`${pathOf(ref)}?demo=1`);
  }
  expect(document.querySelector('[data-panel]')).toBeNull();
  expect(global.fetch).not.toHaveBeenCalled();
});

it('focuses the selected panel\'s own heading, mounts that panel alone, and only reads', async () => {
  await import('../gap');   // PanelPage loads the gap chunk lazily: have it loaded, so the wait is for the panel
  history.replaceState(null, '', '/v2/console/decision-inbox');
  render(<PanelPage panelId="decision-inbox" page={pageForRoute(parseHudRoute('/v2/console/decision-inbox'))} lang="en"
    attention={{}} navigate={navigateHud} onFind={() => {}} />);
  const heading = await screen.findByRole('heading', { level: 1, name: 'Decisions' });
  await waitFor(() => expect(document.activeElement).toBe(heading));
  expect(document.querySelectorAll('[data-panel]')).toHaveLength(1);
  expect(document.querySelector('[data-panel="decision-inbox"]')).not.toBeNull();
  // another area's panel is not a link here: the contents column lists Work's pages only
  expect(screen.queryByRole('link', { name: 'Emergency stop' })).toBeNull();
  await waitFor(() => expect(vi.mocked(global.fetch).mock.calls.length).toBeGreaterThan(0));
  for (const [, options] of vi.mocked(global.fetch).mock.calls) expect((options as RequestInit | undefined)?.method || 'GET').toBe('GET');
});

it('follows ordinary panel links through History API', () => {
  render(<AllPages lang="en" navigate={navigateHud} />);
  fireEvent.click(screen.getByRole('link', { name: 'Decisions' }));
  expect(location.pathname).toBe('/v2/console/decision-inbox');
});
