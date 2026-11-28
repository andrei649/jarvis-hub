import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', enabled: true, chat_routing: 'orchestrated', rosterSource: 'api' as const },
];

describe('Mid-turn composer Steer button (H395)', () => {
  it('shows Steer while a turn is active, calls onSteer, and clears the draft on success', async () => {
    const onSteer = vi.fn().mockResolvedValue(true);
    const onSubmit = vi.fn().mockReturnValue(true);

    const { rerender } = render(
      <InputBar
        onSubmit={onSubmit}
        onSteer={onSteer}
        turnActive={true}
        selectedTurn={true}
        recipientStatus="ready"
        agent="jarvis"
        agents={AGENTS as any}
        sessionId="sess_123"
        t={{ placeholder: 'Write to {agent}', transmit: 'Send' }}
        lang="en"
      />,
    );

    const textarea = screen.getByRole('textbox');
    expect(screen.queryByRole('button', { name: 'Steer' })).toBeNull();

    fireEvent.change(textarea, { target: { value: 'check src/core instead' } });
    const steerBtn = screen.getByRole('button', { name: 'Steer' });
    expect(steerBtn).toBeTruthy();

    fireEvent.click(steerBtn);
    await waitFor(() => expect(onSteer).toHaveBeenCalledWith('check src/core instead'));
    await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe(''));
    expect(onSubmit).not.toHaveBeenCalled();

    // Slash commands do not show the plain-text Steer button.
    fireEvent.change(textarea, { target: { value: '/status' } });
    expect(screen.queryByRole('button', { name: 'Steer' })).toBeNull();

    // Once turnActive is false, Steer disappears.
    fireEvent.change(textarea, { target: { value: 'next question' } });
    rerender(
      <InputBar
        onSubmit={onSubmit}
        onSteer={onSteer}
        turnActive={false}
        selectedTurn={true}
        recipientStatus="ready"
        agent="jarvis"
        agents={AGENTS as any}
        sessionId="sess_123"
        t={{ placeholder: 'Write to {agent}', transmit: 'Send' }}
        lang="en"
      />,
    );
    expect(screen.queryByRole('button', { name: 'Steer' })).toBeNull();
  });
});
