// @ts-nocheck
/* H165 — the Documentation console panel lists the hub's allowlisted docs, renders the
   chosen one through the shared Markdown renderer, keeps hostile markup inert, and
   offers a new-tab deep link without an opener. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { DocsPanel, sectionIndex } from '../panels/docs';
import { SettingsPanel } from '../gap';
import { CONSOLE_PANELS } from '../console-routes';

const LIST = { docs: [
  { slug: 'user-guide', title: 'User guide', available: true, sections: [] },
  { slug: 'flags', title: 'Feature flags', available: true,
    sections: [{ anchor: 'llm.execute_code', title: 'llm.execute_code', names: ['llm.execute_code'] },
               { anchor: 'jarvis_x', title: 'JARVIS_X', names: ['JARVIS_X'] }] },
  { slug: 'privacy', title: 'Privacy', available: false, sections: [] },
] };
const SETTINGS = { llm: [
  { key: 'execute_code', label: 'Let the model run code', value: false, kind: 'toggle' },
  { key: 'max_tokens', label: 'Max tokens', value: 0, kind: 'number' },
] };
const BODIES = {
  'user-guide': { slug: 'user-guide', title: 'User guide', truncated: false,
    markdown: '# Getting started\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>alert(1)</script>' },
  flags: { slug: 'flags', title: 'Feature flags', truncated: true, markdown: '## JARVIS_X\n\nCosts a model call.' },
};

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  window.history.replaceState(null, '', '/v2/console/docs');
  global.fetch = vi.fn(async (url) => {
    const u = String(url);
    const body = u.endsWith('/api/help/docs') ? LIST : u.includes('/api/admin/settings') ? SETTINGS
      : BODIES[decodeURIComponent((u.split('/api/help/docs/')[1] || '').split('?')[0])];
    return { ok: !!body, status: body ? 200 : 404, json: async () => body || { error: 'no such document' } };
  });
});

describe('DocsPanel', () => {
  it('is registered in the console Start group', () => {
    expect(CONSOLE_PANELS.find((p) => p.id === 'docs')).toEqual(
      { id: 'docs', label: 'Documentation', group: 'Start', component: 'DocsPanel' });
  });

  it('renders the user guide by default, with its table, and keeps script inert', async () => {
    const { container } = render(<DocsPanel />);
    await waitFor(() => expect(container.querySelector('h1')?.textContent).toBe('Getting started'));
    expect(container.querySelector('table td').textContent).toBe('1');
    expect(container.querySelector('script')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
    const link = screen.getByText('open in a new tab ↗');
    expect(link.getAttribute('href')).toContain('/v2/console/docs?doc=user-guide');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(link.getAttribute('target')).toBe('_blank');
  });

  it('switches documents, says when one is shown in part, and disables one not shipped', async () => {
    const { container } = render(<DocsPanel />);
    await waitFor(() => expect(screen.getByText('Feature flags')).toBeTruthy());
    expect(screen.getByText('Privacy').closest('button').disabled).toBe(true);
    fireEvent.click(screen.getByText('Feature flags'));
    await waitFor(() => expect(container.querySelector('h2')?.textContent).toBe('JARVIS_X'));
    expect(screen.getByText('shown in part — the file is longer')).toBeTruthy();
  });

  it('opens the document a deep link names', async () => {
    window.history.replaceState(null, '', '/v2/console/docs?doc=flags');
    const { container } = render(<DocsPanel />);
    await waitFor(() => expect(container.querySelector('h2')?.textContent).toBe('JARVIS_X'));
  });
});

describe('Flags cost links', () => {
  it('maps each documented name to its section', () => {
    expect(sectionIndex(LIST, 'flags')).toEqual({ 'llm.execute_code': 'llm.execute_code', JARVIS_X: 'jarvis_x' });
    expect(sectionIndex(null, 'flags')).toEqual({});
  });

  it('opens a deep-linked section and scrolls it into view', async () => {
    window.history.replaceState(null, '', '/v2/console/docs?doc=flags#jarvis_x');
    const seen = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function () { seen.push(this.id); };
    try {
      render(<DocsPanel />);
      await waitFor(() => expect(seen).toEqual(['jarvis_x']));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it('puts a cost link beside a setting FLAGS.md documents, and none beside the rest', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Let the model run code')).toBeTruthy());
    await waitFor(() => expect(screen.getAllByText('cost ↗').length).toBe(1));
    const link = screen.getByText('cost ↗');
    expect(link.getAttribute('href')).toContain('/v2/console/docs?doc=flags#llm.execute_code');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });
});
