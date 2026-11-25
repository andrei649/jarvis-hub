/* Create task from the transcript: only the owner's own nonblank text or a completed reply opens
   the task dialog, with the selected text alone (no attached vault notes or images), and the draft
   goes when the chat scope changes. Since the Ledger cutover (PHASE_B_PLAN.md §5.3, §8.3) a reply
   carries "Create task" in its action row and an owner turn in its More menu. */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeAll, expect, it, vi } from 'vitest';
import { Conversation } from '../cockpit';
import { fetchBoards, createTask } from '../panels/kanban/api';
import { openComposerMenu } from '../home/talk/test-support';

vi.mock('../panels/kanban/api', () => ({
  fetchBoards: vi.fn().mockResolvedValue({ current: 'design', boards: [{ slug: 'design', name: 'Design' }] }),
  createTask: vi.fn(),
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});

const messages = [
  { role: 'user', text: 'Review the sketch', vaultNames: ['Private note'], imageNames: ['source.png'] },
  { role: 'agent', who: 'frigga', text: 'Try a lavender background.', _turnId: 1, _complete: true },
  { role: 'agent', who: 'frigga', text: 'Still drafting…', _turnId: 2 },
  { role: 'agent', who: 'system', text: 'Connection interrupted' },
  { role: 'user', text: ' ' },
];

/** The owner turn's "Create task" (its More menu) and the completed reply's (its action row). */
const ownerTask = () => within(openComposerMenu('more', document.querySelector('[data-turn="owner"]') as HTMLElement))
  .getByRole('button', { name: 'Create task' });
const replyTask = () => within(document.querySelectorAll('[data-turn="reply"]')[0] as HTMLElement)
  .getByRole('button', { name: 'Create task' });

it('opens only the selected user or completed assistant text and drops the draft when the chat scope changes', async () => {
  const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="frigga:s1" lang="en" />);
  // two places offer it: the nonblank owner turn and the completed reply — not the reply still being
  // written, not the system line, not the blank owner turn
  expect(document.querySelectorAll('[data-turn="owner"] [data-talk-menu="more"]')).toHaveLength(1);
  expect(screen.getAllByRole('button', { name: 'Create task' })).toHaveLength(1);
  expect(document.querySelectorAll('[data-act="task"]')).toHaveLength(2);
  expect(fetchBoards).not.toHaveBeenCalled();
  for (const [index, open] of [ownerTask, replyTask].entries()) {
    fireEvent.click(open());
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getAllByDisplayValue(messages[index].text).length).toBeGreaterThan(0);
    expect(within(dialog).queryByText('Private note')).toBeNull();
    expect(within(dialog).queryByText('source.png')).toBeNull();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s2" lang="en" />);
    expect(screen.queryByRole('dialog')).toBeNull();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="frigga:s1" lang="en" />);
    expect(screen.queryByRole('dialog')).toBeNull();
  }
  expect(createTask).not.toHaveBeenCalled();
  view.rerender(<Conversation messages={messages} messageActionsAllowed={false} messageScope="frigga:s1" />);
  expect(document.querySelector('[data-act="task"]')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Create task' })).toBeNull();
});
