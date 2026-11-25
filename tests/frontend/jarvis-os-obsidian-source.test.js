import { expect, it } from 'vitest';
import { obsidianOpenUri } from '../../apps/jarvis-os/public/js/obsidian-source.js';

const source = { vault: 'My Vault', file: 'Projects/Register/A & B – Site.md', readable: false };

it('opens only the named Markdown note with separately encoded Obsidian parameters', () => {
  const link = obsidianOpenUri(source);
  expect(link).toBe('obsidian://open?vault=My%20Vault&file=Projects%2FRegister%2FA%20%26%20B%20%E2%80%93%20Site.md');
  expect(new URL(link).searchParams.get('file')).toBe(source.file);
});

it('omits malformed, hidden or ambiguous native note destinations', () => {
  for (const file of ['/x.md', '../x.md', 'a//b.md', 'a\\x.md', 'data:x.md',
    '%2e%2e/x.md', 'a.md#x.md', 'a^b.md', '.obsidian/x.md', 'x.json', '\ud800.md']) {
    expect(obsidianOpenUri({ ...source, file })).toBeNull();
  }
  expect(obsidianOpenUri({ ...source, vault: 'C:/Other' })).toBeNull();
  expect(obsidianOpenUri({ ...source, readable: 'yes' })).toBeNull();
  expect(obsidianOpenUri(null)).toBeNull();
});
