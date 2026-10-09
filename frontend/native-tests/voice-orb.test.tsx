import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { VoiceOrb } from '../../mobile/src/components/VoiceOrb';
import { AccessibilityInfo, foreground, motionListenerCount, setReducedMotion } from './support/native';

async function settle() { await act(async () => { await Promise.resolve(); }); }
function pointX(container: HTMLElement) { return Number(container.querySelectorAll('circle')[1]?.getAttribute('cx')); }

beforeEach(() => { foreground('active'); setReducedMotion(false); vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('renders a bounded native SVG state with an honest energy source', async () => {
  const { container, getByLabelText } = render(<VoiceOrb status="listening" level={0.25} size={900} />);
  await settle();
  expect(getByLabelText('listening, measured mic level')).toBeTruthy();
  expect(container.querySelector('svg')?.getAttribute('width')).toBe('360');
  expect(container.querySelectorAll('circle').length).toBeLessThanOrEqual(73);
  expect(container.querySelectorAll('line').length).toBeLessThanOrEqual(24);
  expect(container.querySelectorAll('ellipse')).toHaveLength(2);
  const noSignal = render(<VoiceOrb status="listening" />);
  await settle();
  expect(noSignal.getByLabelText('listening, no measured mic level')).toBeTruthy();
  const speaking = render(<VoiceOrb status="speaking" level={0.25} />);
  await settle();
  expect(speaking.getByLabelText('speaking, state animation')).toBeTruthy();
});

it('stops geometry ticks in reduced motion and resumes on a preference change', async () => {
  const { container } = render(<VoiceOrb status="speaking" />);
  await settle();
  const start = pointX(container);
  act(() => vi.advanceTimersByTime(50));
  expect(pointX(container)).not.toBe(start);
  act(() => setReducedMotion(true));
  const frozen = pointX(container);
  act(() => vi.advanceTimersByTime(500));
  expect(pointX(container)).toBe(frozen);
  act(() => setReducedMotion(false));
  act(() => vi.advanceTimersByTime(50));
  expect(pointX(container)).not.toBe(frozen);
});

it('pauses in background and cancels timer and accessibility listener on unmount', async () => {
  const { container, unmount } = render(<VoiceOrb status="idle" />);
  await settle();
  expect(motionListenerCount()).toBe(1);
  expect(vi.getTimerCount()).toBe(1);
  act(() => foreground('background'));
  expect(vi.getTimerCount()).toBe(0);
  const paused = pointX(container);
  act(() => vi.advanceTimersByTime(500));
  expect(pointX(container)).toBe(paused);
  act(() => foreground('active'));
  expect(vi.getTimerCount()).toBe(1);
  unmount();
  expect(vi.getTimerCount()).toBe(0);
  expect(motionListenerCount()).toBe(0);
});

it('freezes if reduced-motion support is unavailable', async () => {
  setReducedMotion(null);
  const { container } = render(<VoiceOrb status="speaking" />);
  await settle();
  expect(vi.getTimerCount()).toBe(0);
  const frozen = pointX(container);
  act(() => vi.advanceTimersByTime(500));
  expect(pointX(container)).toBe(frozen);
});

it('samples rapid measured levels at the 50 ms visual cadence', async () => {
  const ui = render(<VoiceOrb status="listening" level={0} />);
  await settle();
  const radius = () => ui.container.querySelector('circle')?.getAttribute('r');
  const initial = radius();
  for (let index = 0; index < 10; index++) ui.rerender(<VoiceOrb status="listening" level={index / 40} />);
  expect(radius()).toBe(initial);
  act(() => vi.advanceTimersByTime(50));
  expect(radius()).not.toBe(initial);
});

it('ignores a stale initial preference read after a newer accessibility change', async () => {
  let finishQuery: (value: boolean) => void = () => {};
  vi.spyOn(AccessibilityInfo, 'isReduceMotionEnabled').mockImplementationOnce(() => new Promise(resolve => { finishQuery = resolve; }));
  render(<VoiceOrb status="speaking" />);
  await settle();
  act(() => setReducedMotion(true));
  await act(async () => { finishQuery(false); await Promise.resolve(); });
  expect(vi.getTimerCount()).toBe(0);
});

it('shows current measured energy without a timer while reduced motion freezes rotation', async () => {
  setReducedMotion(true);
  const ui = render(<VoiceOrb status="listening" level={0} />);
  await settle();
  expect(vi.getTimerCount()).toBe(0);
  const startingRotation = ui.container.querySelector('ellipse')?.getAttribute('transform');
  const startingRadius = ui.container.querySelector('circle')?.getAttribute('r');
  ui.rerender(<VoiceOrb status="listening" level={0.25} />);
  expect(ui.container.querySelector('circle')?.getAttribute('r')).not.toBe(startingRadius);
  expect(ui.container.querySelector('ellipse')?.getAttribute('transform')).toBe(startingRotation);
  expect(vi.getTimerCount()).toBe(0);
});
