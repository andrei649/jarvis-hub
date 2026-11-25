import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeAll, expect, it, vi } from 'vitest';
import { Conversation } from '../cockpit';
import { fetchBoards, createTask } from '../panels/kanban/api';

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

it('opens only the selected user or completed assistant text and drops the draft when the chat scope changes', async () => {
  const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="frigga:s1" lang="en" />);
  const actions = screen.getAllByRole('button', { name: 'Create task' });
  expect(actions).toHaveLength(2);
  expect(fetchBoards).not.toHaveBeenCalled();
  for (const [index, action] of actions.entries()) {
    fireEvent.click(action);
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
  expect(screen.queryByRole('button', { name: 'Create task' })).toBeNull();
});
