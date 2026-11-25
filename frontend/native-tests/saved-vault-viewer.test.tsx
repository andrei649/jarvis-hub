import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Linking } from 'react-native';
import { SavedVaultNoteViewer } from '../../mobile/src/components/SavedVaultNoteViewer';
import { readSavedChatNote } from '../../mobile/src/api/chatNote';
import { ApiError } from '../../mobile/src/api/client';

vi.mock('../../mobile/src/api/chatNote', () => ({ readSavedChatNote: vi.fn() }));
const read = vi.mocked(readSavedChatNote);
const target = { id: 'v1-' + '8'.repeat(64), vault: 'Șantier', inbox: 'Saved notes' };
const relPath = 'Saved notes/Status A & B.md';
const receipt = { relPath, source: { vault: target.vault, file: relPath, readable: true as const } };
const props = { target, receipt, config: { baseUrl: 'https://hub.test', token: 'local', adminToken: '' }, onClose: vi.fn() };
afterEach(() => { cleanup(); vi.restoreAllMocks(); read.mockReset(); });

it('reads current text from the hub and hands off to device Obsidian only when tapped', async () => {
  const markdown = '## Actual note\nLast **line**. [Reference](https://example.com)';
  read.mockResolvedValue(markdown);
  const link = vi.spyOn(Linking, 'openURL').mockRejectedValue(new Error('Unavailable'));
  render(<SavedVaultNoteViewer {...props} />);
  await screen.findByText('Actual note');
  fireEvent.click(screen.getByText('Reference'));
  expect(read).toHaveBeenCalledWith(props.config, target, receipt);
  expect(link).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Show Markdown'));
  expect(screen.getByText(/Last \*\*line\*\*/).textContent).toBe(markdown);
  fireEvent.click(screen.getByText('Open in Obsidian on this device'));
  expect(link).toHaveBeenCalledWith('obsidian://open?vault=%C8%98antier&file=Saved%20notes%2FStatus%20A%20%26%20B.md');
  await screen.findByText(/could not open this link/);
  expect(screen.getByText(/Last \*\*line\*\*/)).toBeTruthy();
});

it('discards a late read after switching connections and retries the current hub', async () => {
  let old!: (text: string) => void;
  read.mockImplementationOnce(() => new Promise(resolve => { old = resolve; }))
    .mockRejectedValueOnce(new ApiError('Not available', 404)).mockResolvedValueOnce('Recovered note');
  const page = render(<SavedVaultNoteViewer {...props} />);
  const next = { ...props.config, baseUrl: 'https://second.test' };
  page.rerender(<SavedVaultNoteViewer {...props} config={next} />);
  await screen.findByText(/unavailable in the original vault/);
  await act(async () => { old('Other connection text'); });
  expect(screen.queryByText('Other connection text')).toBeNull();
  expect(screen.queryByText('Open in Obsidian on this device')).toBeNull();
  fireEvent.click(screen.getByText('Try again'));
  await screen.findByText('Recovered note');
  expect(read).toHaveBeenLastCalledWith(next, target, receipt);
});
