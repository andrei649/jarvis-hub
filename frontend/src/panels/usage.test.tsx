// @ts-nocheck
import React from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ConsoleOverlay } from '../gap';
import { CONSOLE_PANEL_MAP } from '../console-routes';

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('hud.user_token', 'synthetic-user');
  localStorage.setItem('hud.admin_token', 'synthetic-owner');
});

it('makes Usage a reachable Command Center section', () => {
  expect(CONSOLE_PANEL_MAP.get('usage')?.label).toBe('Usage');
  expect(CONSOLE_PANEL_MAP.get('usage')?.group).toBe('Start');
});

it('shows the actual APM response totals and breakdowns in the console', async () => {
  global.fetch = vi.fn().mockImplementation((url) => Promise.resolve({
    ok: true, status: 200, json: async () => String(url).includes('/api/admin/apm') ? {
      totals: { runs: 3, input_tokens: 6000, output_tokens: 2000, cost_usd: 0.012,
        unpriced_calls: 1 },
      by_agent: [{ agent: 'jarvis', model: 'gpt-4o', runs: 3, input_tokens: 6000,
        output_tokens: 2000, cost_usd: 0.012, unpriced_calls: 1, priced: false }],
      by_model: [{ model: 'gpt-4o', runs: 3, input_tokens: 6000, output_tokens: 2000,
        cost_usd: 0.012, unpriced_calls: 1 }],
      by_locality: {
        local: { runs: 1, input_tokens: 1000, output_tokens: 500, cost_usd: 0, unpriced_calls: 0 },
        cloud: { runs: 1, input_tokens: 2000, output_tokens: 1000, cost_usd: 0.012, unpriced_calls: 0 },
        unknown: { runs: 1, input_tokens: 3000, output_tokens: 500, cost_usd: 0, unpriced_calls: 1 },
      },
    } : {},
  }));
  render(<ConsoleOverlay panelId="apm" onClose={() => {}} />);
  await waitFor(() => expect(screen.getByText('all usage')).toBeTruthy());
  const total = screen.getByText('all usage').parentElement!.textContent!;
  expect(total).toContain('3 runs');
  expect(total).toContain('6,000 in / 2,000 out');
  expect(total).toContain('$0.012000 estimated');
  expect(total).toContain('1 unpriced call');
  expect(screen.getByText('jarvis').parentElement!.textContent).toContain('3 runs');
  expect(screen.getByText('cloud').parentElement!.textContent).toContain('3,000 tokens');
  expect(screen.getByRole('meter', { name: 'Token locality' })).toBeTruthy();
  expect(screen.getByRole('meter', { name: 'Known estimated cost locality' })).toBeTruthy();
  const apmCalls = global.fetch.mock.calls.filter(([url]) => String(url).includes('/api/admin/apm'));
  expect(apmCalls).toHaveLength(1);
  expect(apmCalls[0][1].headers).toMatchObject({
    'X-User-Token': 'synthetic-user', 'X-Admin-Token': 'synthetic-owner',
  });
});

it('opens the read-only Billing tab in Settings', async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
  render(<ConsoleOverlay panelId="settings" onClose={() => {}} />);
  fireEvent.click(screen.getByRole('tab', { name: 'Billing' }));
  expect(screen.getByRole('tab', { name: 'Billing' }).getAttribute('aria-selected')).toBe('true');
  await waitFor(() => expect(screen.getByText('USAGE')).toBeTruthy());
  await waitFor(() => expect(global.fetch.mock.calls.filter(([url]) =>
    String(url).includes('/api/admin/apm'))).toHaveLength(1));
  const apmCall = global.fetch.mock.calls.find(([url]) => String(url).includes('/api/admin/apm'));
  expect(apmCall[1].headers).toMatchObject({
    'X-User-Token': 'synthetic-user', 'X-Admin-Token': 'synthetic-owner',
  });
});
