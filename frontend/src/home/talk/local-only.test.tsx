/* The local-only list (PHASE_B_PLAN.md §5.3): the chat-history search reads the
   hub's LOCAL_ONLY_AGENTS from signals/agents-policy.ts instead of its own hard-coded copy, so a
   passage cited to frigga, ultron or howard needs no cloud consent. */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { apiGet, apiPost } from '../../api/client';
import { ChatHistorySearch } from '../../chat-history-search';

vi.mock('../../api/client', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), getAdminToken: () => '', getToken: () => '' }));
vi.mock('../../api/owner-session', () => ({ isNetworkedOrigin: () => false, ownerSession: () => null,
  csrfToken: () => '', onOwnerSession: () => () => {} }));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const hit = { session_id: 'old', turn: 3, role: 'assistant', timestamp: '2026-10-01T10:00:00Z', agent_id: 'frigga', snippet: 'the porch light' };
const transcript = { schema_version: 1, session_id: 'old', scope: 'retained_current_history', redacted: true,
  turns: [{ turn: 3, role: 'assistant', timestamp: hit.timestamp, agent_id: 'frigga', content: 'Turn on the porch light at dusk.',
    reference_revision: 'a'.repeat(64) }] };

it.each([
  ['frigga', true], ['ultron', true], ['howard', true], ['athena', false], ['jarvis', false],
])('treats %s as strictly local: %s', async (recipient, local) => {
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValue(transcript);
  render(<ChatHistorySearch lang="en" opener={null} onClose={vi.fn()} hasDraft={false} hasAttachment={false}
    recipient={recipient} onUse={() => true} canUse={() => true} />);
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved message text' }), { target: { value: 'porch' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Review source' }));
  await screen.findByRole('textbox', { name: 'Select exact text from the verified message' });
  expect(!!screen.queryByText(/This selected agent is strictly local\./)).toBe(local);
  expect(!!screen.queryByRole('checkbox', { name: /if it uses a cloud model/ })).toBe(!local);
});
