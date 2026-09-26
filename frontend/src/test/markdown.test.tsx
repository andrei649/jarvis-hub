// @ts-nocheck
/* H165 / H168 — the shared Markdown renderer emits React elements only: lists, fences
   and tables become ul/ol/pre/table, and raw HTML or a javascript: link stays inert
   text. The source never reaches for dangerouslySetInnerHTML. */
import { describe, it, expect } from 'vitest';
import React from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render } from '@testing-library/react';
import { Markdown, headingAnchor, safeHref } from '../markdown';

const DOC = [
  '# Title',
  'Intro with **bold**, *italic*, `code` and [a site](https://example.test/x).',
  '',
  '- one',
  '- two',
  '',
  '1. first',
  '2. second',
  '',
  '```',
  'raw <b>not bold</b>',
  '```',
  '',
  '| Flag | Default |',
  '|---|---:|',
  '| `JARVIS_X` | off |',
  '',
  '> a quote',
  '',
  '---',
].join('\n');

describe('Markdown — structure', () => {
  it('renders headings, lists, a fence, a table, a quote and a rule', () => {
    const { container } = render(<Markdown text={DOC} />);
    expect(container.querySelector('h1').textContent).toBe('Title');
    expect(container.querySelector('strong').textContent).toBe('bold');
    expect(container.querySelector('em').textContent).toBe('italic');
    expect([...container.querySelectorAll('ul li')].map((li) => li.textContent)).toEqual(['one', 'two']);
    expect([...container.querySelectorAll('ol li')].map((li) => li.textContent)).toEqual(['first', 'second']);
    expect(container.querySelector('pre code').textContent).toBe('raw <b>not bold</b>');
    expect(container.querySelector('pre b')).toBeNull();
    expect([...container.querySelectorAll('th')].map((th) => th.textContent)).toEqual(['Flag', 'Default']);
    expect(container.querySelector('td code').textContent).toBe('JARVIS_X');
    expect(container.querySelector('blockquote').textContent).toBe('a quote');
    expect(container.querySelector('hr')).not.toBeNull();
  });

  it('keeps snake_case names and loose asterisks as text', () => {
    const { container } = render(<Markdown text={'Set MEMORY_EMBED_TURNS and 2 * 3 * 4 stays math.'} />);
    expect(container.querySelector('em')).toBeNull();
    expect(container.textContent).toBe('Set MEMORY_EMBED_TURNS and 2 * 3 * 4 stays math.');
  });
});

describe('Markdown — hostile content stays inert', () => {
  it('shows raw HTML as literal text and creates no script, iframe or handler', () => {
    const hostile = '<script>alert(1)</script>\n\n<iframe src="https://evil.test"></iframe>\n\n<img src=x onerror=alert(1)>';
    const { container } = render(<Markdown text={hostile} />);
    expect(container.querySelector('script, iframe, img')).toBeNull();
    expect(container.textContent).toContain('<script>alert(1)</script>');
    expect(container.textContent).toContain('<iframe src="https://evil.test"></iframe>');
  });

  it('links only http(s) and same-origin paths, always in a new tab without an opener', () => {
    const md = '[ok](https://example.test) [local](/v2/console/docs) [js](javascript:alert(1)) '
      + '[data](data:text/html,x) [proto](//evil.test) [tab](/\t/evil.test) [file](FLAGS.md)';
    const { container } = render(<Markdown text={md} />);
    const links = [...container.querySelectorAll('a')];
    expect(links.map((a) => a.textContent)).toEqual(['ok', 'local']);
    for (const a of links) {
      expect(a.getAttribute('target')).toBe('_blank');
      expect(a.getAttribute('rel')).toBe('noopener noreferrer');
    }
    expect(container.textContent).toContain('js');
    expect(safeHref('javascript:alert(1)')).toBeNull();
    expect(safeHref('//evil.test')).toBeNull();
    expect(safeHref('/\t/evil.test')).toBeNull();
    expect(safeHref('https:/\\evil.test')).toBeNull();
  });

  it('never uses dangerouslySetInnerHTML', () => {
    const source = readFileSync(join(process.cwd(), 'src', 'markdown.tsx'), 'utf-8');
    expect(source).not.toMatch(/dangerouslySetInnerHTML\s*=|\.innerHTML\b|outerHTML|insertAdjacentHTML/);
    expect(source).not.toMatch(/\(\?<[=!]/);  // no regex lookbehind: older Safari cannot parse it
  });
});


describe('Markdown — heading anchors', () => {
  it('computes the same anchors as the hub (one shared fixture)', () => {
    const fixture = JSON.parse(readFileSync(join(process.cwd(), '..', 'tests', 'fixtures', 'heading_anchors.json'), 'utf-8'));
    for (const [heading, anchor] of Object.entries(fixture)) expect(headingAnchor(heading)).toBe(anchor);
  });

  it('gives each heading its id, numbering a repeat like the hub does', () => {
    const { container } = render(<Markdown text={'# Title\n## `A`\n## `A`\n```\n# fenced\n```'} />);
    expect([...container.querySelectorAll('h1, h2')].map((h) => h.id)).toEqual(['title', 'a', 'a-2']);
  });

  it('H168 — breaks: a single newline is a line break; without it the lines join', () => {
    const joined = render(<Markdown text={'one **a**\ntwo\n\nthree'} />).container;
    expect(joined.querySelector('br')).toBeNull();
    expect([...joined.querySelectorAll('p')].map((p) => p.textContent)).toEqual(['one a two', 'three']);
    const broken = render(<Markdown text={'one **a**\ntwo\nthe `end`\n\nthree'} breaks />).container;
    const [first, second] = broken.querySelectorAll('p');
    expect(first.querySelectorAll('br')).toHaveLength(2);
    expect(first.textContent).toBe('one atwothe end');
    expect(first.querySelector('strong').textContent).toBe('a');
    expect(first.querySelector('code').textContent).toBe('end');
    expect(second.querySelector('br')).toBeNull();
  });
});
