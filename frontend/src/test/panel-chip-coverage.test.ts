// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../gap.tsx', import.meta.url), 'utf8');

function cardTitle(tag: string): string {
  const m = tag.match(/\btitle=(?:"([^"]+)"|{`([^`]+)`}|{([^}]+)})/);
  return m ? (m[1] || m[2] || m[3] || '(dynamic)') : '(untitled)';
}

describe('Console panel honesty chips', () => {
  it('requires every Console Card to declare a live/seed signal', () => {
    const cards = Array.from(source.matchAll(/<Card\b[\s\S]*?>/g)).map((m) => m[0]);
    const missing = cards
      .filter((tag) => !/\blive\s*=/.test(tag))
      .map(cardTitle);

    expect(missing).toEqual([]);
  });
});
