import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ConsoleOverlay } from '../gap';
import { CONSOLE_PANELS } from '../console-routes';

beforeEach(() => {
  history.replaceState(null, '', '/v2/console?demo=1#anchor');
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
});
it('offers a bookmark link for every panel without mounting or fetching any panel', () => {
  render(<ConsoleOverlay onClose={() => {}} />);
  const links = screen.getAllByRole('link');
  expect(links.map(link => [link.textContent, link.getAttribute('href')])).toEqual(CONSOLE_PANELS.map(panel => [panel.label, `/v2/console/${panel.id}?demo=1#anchor`]));
  expect(global.fetch).not.toHaveBeenCalled();
});
it('focuses only the selected panel and navigation remains read-only', async () => {
  render(<ConsoleOverlay panelId="decision-inbox" onClose={() => {}} />);
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('heading', { name: 'Decision Inbox' })));
  expect(screen.queryByRole('link', { name: 'Kill Switch' })).toBeNull();
  expect(screen.getByRole('link', { name: 'All console panels' }).getAttribute('href')).toContain('/v2/console');
  for (const [, options] of vi.mocked(global.fetch).mock.calls) expect(options?.method || 'GET').toBe('GET');
});
it('follows ordinary panel links through History API', () => {
  render(<ConsoleOverlay onClose={() => {}} />);
  fireEvent.click(screen.getByRole('link', { name: 'Decision Inbox' }));
  expect(location.pathname).toBe('/v2/console/decision-inbox');
});
