import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { PRESSURE_NONE, PressureBanner, pressureText, readPressure } from '../pressure-banner';

const payload = {
  boot_id: 'boot-a',
  conditions: [
    { condition: 'memory_critical', level: 'critical', percent: 96.2, dismissed: false },
    { condition: 'disk_elevated', level: 'elevated', percent: 88, dismissed: false,
      paths: [{ path: '/srv/jarvis', percent: 88 }] },
  ],
  worst: { condition: 'memory_critical', level: 'critical', percent: 96.2, dismissed: false },
};

describe('pressure banner (H161)', () => {
  it('reads the worst undismissed condition and the boot it belongs to', () => {
    const s = readPressure(payload);
    expect(s.bootId).toBe('boot-a');
    expect(s.worst).toEqual({ condition: 'memory_critical', percent: 96, paths: [] });
  });

  it('says what each condition means', () => {
    expect(pressureText({ condition: 'disk_critical', percent: 97, paths: [{ path: '/srv/jarvis', percent: 97 }] }))
      .toBe('Disk almost full: /srv/jarvis at 97%. Free some space, or the hub may stop saving your data.');
    expect(pressureText({ condition: 'memory_critical', percent: 96, paths: [] }))
      .toBe('Memory almost exhausted: 96% in use. The local model or the hub may be stopped by the system.');
    expect(pressureText({ condition: 'oom_restart_suspected', percent: null, paths: [] }))
      .toBe('The hub restarted after running short of memory (suspected out-of-memory stop).');
    expect(pressureText({ condition: 'disk_elevated', percent: 88, paths: [{ path: '/', percent: 88 }] }))
      .toBe('Disk filling up: / at 88%.');
    expect(pressureText({ condition: 'memory_elevated', percent: 87, paths: [] }))
      .toBe('Memory running high: 87% in use.');
  });

  it('shows only the worst one, and dismisses it for this boot', () => {
    const onDismiss = vi.fn();
    render(<PressureBanner state={readPressure(payload)} onDismiss={onDismiss} />);
    const banner = screen.getByTestId('pressure-banner');
    expect(banner.getAttribute('role')).toBe('alert');
    expect(banner.textContent).toContain('Memory almost exhausted');
    expect(banner.textContent).not.toContain('Disk filling up');
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalledWith('memory_critical', 'boot-a');
  });

  it('an elevated condition is a status, not an alarm', () => {
    render(<PressureBanner state={readPressure({ ...payload, worst: payload.conditions[1] })} onDismiss={() => {}} />);
    expect(screen.getByTestId('pressure-banner').getAttribute('role')).toBe('status');
  });

  it('says nothing when all is well or the answer is malformed', () => {
    for (const raw of [null, 'x', {}, { boot_id: 'b', worst: null }, { boot_id: 'b', worst: { condition: 'swap_full' } },
      { boot_id: 5, worst: payload.worst }]) {
      expect(readPressure(raw)).toEqual(PRESSURE_NONE);
    }
    const { container } = render(<PressureBanner state={PRESSURE_NONE} onDismiss={() => {}} />);
    expect(container.innerHTML).toBe('');
    const orphan = render(<PressureBanner state={{ bootId: null, worst: readPressure(payload).worst }} onDismiss={() => {}} />);
    expect(orphan.container.innerHTML).toBe('');   // nothing to dismiss it against
  });

  it('bounds what it shows from the hub', () => {
    const long = '/'.concat('d'.repeat(500));
    const s = readPressure({ boot_id: 'b', worst: { condition: 'disk_critical', percent: 1000,
      paths: [{ path: long, percent: 99 }, { path: 7, percent: 'x' }] } });
    expect(s.worst?.percent).toBe(100);
    expect(s.worst?.paths).toEqual([{ path: long.slice(0, 120), percent: 99 }]);
  });
});
