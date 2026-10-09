import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BriefingField } from '../../mobile/src/components/BriefingField';
import { AccessibilityInfo, foreground, motionListenerCount, setReducedMotion } from './support/native';

const agents = [{ id: 'one', tier: 'TEC', status: 'busy' }, { id: 'two', tier: 'BUS', status: 'idle' }];
const tasks = [{ owner: 'one', state: 'running' }];
const voice = { status: 'listening' as const, level: 0.4 };
async function settle() { await act(async () => { await Promise.resolve(); }); }
function markerX(container: HTMLElement) { return container.querySelectorAll('circle')[1]?.getAttribute('cx'); }

beforeEach(() => { foreground('active'); setReducedMotion(false); vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('renders bounded SVG with real roster, owner counts, and measured source', async () => {
  const ui = render(<BriefingField agents={agents} tasks={tasks} voice={voice} />);
  await settle();
  expect(ui.getByText(/TEC · 1 agent · 1 active\/busy · 1 running task in feed/)).toBeTruthy();
  expect(ui.getByText(/BUS · 1 agent · 0 active\/busy · 0 running tasks in feed/)).toBeTruthy();
  expect(ui.getByText('measured mic level')).toBeTruthy();
  expect(ui.container.querySelectorAll('circle').length).toBeLessThanOrEqual(97);
  expect(ui.container.querySelectorAll('line').length).toBeLessThanOrEqual(192);
  ui.rerender(<BriefingField agents={[]} tasks={[]} voice={{ status: 'idle' }} />);
  expect(ui.getByText('No reported agents')).toBeTruthy();
  expect(ui.container.querySelectorAll('line')).toHaveLength(0);
  expect(ui.container.querySelectorAll('circle')).toHaveLength(1);
});

it('treats retained data as unavailable and never turns an unknown count into zero', async () => {
  const ui = render(<BriefingField agents={agents} tasks={tasks} voice={{ status: 'idle' }}
    agentsAvailable={false} tasksAvailable={false} />);
  await settle();
  expect(ui.getByText('Agent roster unavailable')).toBeTruthy();
  expect(ui.getByText('Task feed unavailable')).toBeTruthy();
  expect(ui.container.querySelectorAll('line')).toHaveLength(0);
  expect(ui.container.querySelectorAll('circle')).toHaveLength(1);
  expect(ui.queryByText('reported work')).toBeNull();
  expect(ui.queryByText('idle')).toBeNull();
  expect(ui.getByText('activity evidence incomplete')).toBeTruthy();
  expect(ui.container.querySelector('[aria-label]')?.getAttribute('aria-label')).not.toContain('0 reported');

  ui.rerender(<BriefingField agents={agents} tasks={tasks} voice={{ status: 'idle' }}
    agentsAvailable tasksAvailable={false} />);
  expect(ui.getByText(/TEC · 1 agent · 1 active\/busy · Task feed unavailable/)).toBeTruthy();
  expect(ui.queryByText(/0 running tasks/)).toBeNull();
  expect(ui.getByText('reported work')).toBeTruthy();

  ui.rerender(<BriefingField agents={agents} tasks={tasks} voice={{ status: 'idle' }}
    agentsAvailable={false} tasksAvailable />);
  expect(ui.getByText('Agent roster unavailable')).toBeTruthy();
  expect(ui.queryByText(/TEC ·/)).toBeNull();
  expect(ui.getByText('reported work')).toBeTruthy();
  expect(ui.container.querySelectorAll('line')).toHaveLength(0);
});

it('does not imply a measured signal from invalid mic input or voice state', async () => {
  const ui = render(<BriefingField agents={[]} tasks={[]} voice={{ status: 'listening', level: NaN }} />);
  await settle();
  expect(ui.getByText('voice state, no measured level')).toBeTruthy();
  ui.rerender(<BriefingField agents={[]} tasks={[]} voice={{ status: 'speaking', level: 1 }} />);
  expect(ui.getByText('voice state')).toBeTruthy();
});

it('ticks at no more than 15 fps and freezes in reduced motion, background, and inactive prop', async () => {
  const ui = render(<BriefingField agents={agents} tasks={tasks} voice={voice} />);
  await settle();
  expect(vi.getTimerCount()).toBe(1);
  const initial = markerX(ui.container);
  act(() => vi.advanceTimersByTime(60));
  expect(markerX(ui.container)).toBe(initial);
  act(() => vi.advanceTimersByTime(70));
  expect(markerX(ui.container)).not.toBe(initial);
  act(() => setReducedMotion(true));
  expect(vi.getTimerCount()).toBe(0);
  const frozen = markerX(ui.container);
  act(() => vi.advanceTimersByTime(1000));
  expect(markerX(ui.container)).toBe(frozen);
  act(() => setReducedMotion(false));
  act(() => foreground('background'));
  expect(vi.getTimerCount()).toBe(0);
  act(() => foreground('active'));
  expect(vi.getTimerCount()).toBe(1);
  ui.rerender(<BriefingField agents={agents} tasks={tasks} voice={voice} active={false} />);
  expect(vi.getTimerCount()).toBe(0);
  ui.unmount();
  expect(motionListenerCount()).toBe(0);
  expect(vi.getTimerCount()).toBe(0);
});

it('ignores a stale reduced-motion query after a newer preference event', async () => {
  let resolveQuery: (value: boolean) => void = () => {};
  vi.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockImplementationOnce(() => new Promise(resolve => { resolveQuery = resolve; }));
  render(<BriefingField agents={agents} tasks={tasks} voice={voice} />);
  await settle();
  act(() => setReducedMotion(true));
  await act(async () => { resolveQuery(false); await Promise.resolve(); });
  expect(vi.getTimerCount()).toBe(0);
});
