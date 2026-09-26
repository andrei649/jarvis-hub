// @ts-nocheck
/* H168 — agent text renders through the one shared Markdown component (markdown.tsx) in
   the chat bubbles, the decision cards and canvas artifacts: lists, fences, tables and
   safe links render as elements; raw HTML and unsafe links stay text; a user's own words
   stay literal; an artifact still shows at most 4,000 characters. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { ContextColumn } from '../shell';
import { ArtifactsPanel, MARKDOWN_LIMIT } from '../artifacts';
import { V2 } from '../data';

const t = V2.I18N.en;
const RICH = [
  'Here is the **plan**:',
  '',
  '1. read the logs',
  '2. fix the `parser`',
  '',
  '```',
  'x = 1  # kept verbatim',
  '```',
  '',
  '| step | who |',
  '| --- | --- |',
  '| ship | jarvis |',
  '',
  'See [the docs](https://example.com/docs) or [this](javascript:alert(1)).',
  '<img src=x onerror=alert(2)>',
].join('\n');

afterEach(() => { cleanup(); delete global.fetch; });

function inert(container) {
  expect(container.querySelector('script, iframe, img')).toBeNull();
  expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  expect(screen.getByText('this').tagName).toBe('SPAN');                    // an unsafe link stays text
  expect(screen.getByText(/<img src=x onerror=alert\(2\)>/)).toBeTruthy();  // raw HTML stays literal
}

describe('chat bubbles — H168', () => {
  it('an agent reply renders as Markdown', () => {
    const { container } = render(<Conversation messages={[{ role: 'agent', who: 'jarvis', text: RICH, ts: '09:00' }]} thinking={null} t={t} />);
    const bubble = container.querySelector('.msg.agent .bubble');
    expect(bubble.querySelector('strong').textContent).toBe('plan');
    expect([...bubble.querySelectorAll('ol li')].map((li) => li.textContent)).toEqual(['read the logs', 'fix the parser']);
    expect(bubble.querySelector('li code').textContent).toBe('parser');
    expect(bubble.querySelector('pre code').textContent).toBe('x = 1  # kept verbatim');
    expect([...bubble.querySelectorAll('td')].map((td) => td.textContent)).toEqual(['ship', 'jarvis']);
    const link = screen.getByText('the docs');
    expect(link.getAttribute('href')).toBe('https://example.com/docs');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
    expect(bubble.textContent).not.toContain('**');
    inert(container);
  });

  it('a vision analysis renders as Markdown too, and the owner’s own words stay literal', () => {
    const { container } = render(<Conversation messages={[
      { role: 'user', text: 'make it **bold** and - a list', ts: '09:00' },
      { role: 'vision', text: '- a cat\n- a mat', ts: '09:01', model: 'm', backend: 'b', destination: 'd', local: true },
    ]} thinking={null} t={t} />);
    expect([...container.querySelectorAll('.msg.agent .bubble li')].map((li) => li.textContent)).toEqual(['a cat', 'a mat']);
    const mine = container.querySelector('.msg.user .bubble');
    expect(mine.textContent).toBe('make it **bold** and - a list');
    expect(mine.querySelector('strong, li')).toBeNull();
  });
});

describe('decision cards — H168', () => {
  it('a decision body renders as Markdown', () => {
    const decisions = [{ _id: 'd1', who: 'friday', kind: 'approve', kindLabel: 'APPROVE', body: RICH, actions: [{ l: 'ok', primary: true }] }];
    const { container } = render(<ContextColumn decisions={decisions} onDecision={() => {}} t={t} />);
    const body = container.querySelector('.dcard .db');
    expect(body.querySelector('strong').textContent).toBe('plan');
    expect(body.querySelectorAll('ol li')).toHaveLength(2);
    expect(body.querySelector('table')).toBeTruthy();
    inert(container);
  });
});

describe('canvas artifacts — H168', () => {
  const canvas = (body) => {
    global.fetch = vi.fn((url) => {
      const path = String(url);
      if (path === '/api/artifacts') return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ enabled: false, items: [] }) });
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ elements: [
        { id: 'm1', agent: 'jarvis', type: 'markdown', pinned: false, created_at: 1770000000, payload: { title: 'Brief', body } },
      ] }) });
    });
  };

  it('a markdown artifact renders fences, ordered lists, tables and safe links', async () => {
    canvas(RICH);
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    expect(await screen.findByText('the docs')).toBeTruthy();
    expect(container.querySelectorAll('ol li')).toHaveLength(2);
    expect(container.querySelector('pre code').textContent).toBe('x = 1  # kept verbatim');
    expect(container.querySelector('table')).toBeTruthy();
    inert(container);
  });

  it('a single newline in an artifact stays a line break', async () => {
    canvas('first line\nsecond line');
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    await screen.findByText('Brief');
    const p = container.querySelector('.md p');
    expect(p.querySelectorAll('br')).toHaveLength(1);
    expect(p.textContent).toBe('first linesecond line');
  });

  it('shows at most the canvas bound, cut on a code point', async () => {
    const astral = '😀';
    canvas('a'.repeat(MARKDOWN_LIMIT - 1) + astral + 'TAIL-NOT-SHOWN');
    const { container } = render(<ArtifactsPanel refreshKey={0} lang="en" />);
    await screen.findByText('Brief');
    const shown = container.querySelector('.md p').textContent;
    expect(Array.from(shown)).toHaveLength(MARKDOWN_LIMIT);
    expect(shown.endsWith(astral)).toBe(true);
    expect(container.textContent).not.toContain('TAIL-NOT-SHOWN');
  });
});
