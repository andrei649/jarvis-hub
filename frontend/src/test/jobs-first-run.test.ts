import {expect, it} from 'vitest';
import {armNote, onceAt} from '../panels/jobs';

const job = {schedule_text: 'every weekday at 8:00', cron: '0 8 * * 1-5'};
const interval = {schedule_text: 'every 2 hours', cron: '0 */2 * * *'};

it('says the first run fires now when the hub queued one', () => {
  expect(armNote({job: interval, first_run: {status: 'queued'}, confirmation: 'first run now, then every 2 hours (0 */2 * * *)'}))
    .toBe('armed · first run now, then every 2 hours (0 */2 * * *)');
});

it('says the job waits for its cadence when no first run was queued', () => {
  expect(armNote({job, first_run: null, confirmation: 'every weekday at 8:00 (0 8 * * 1-5), on its cadence'}))
    .toBe('armed · every weekday at 8:00 (0 8 * * 1-5), on its cadence');
});

it('still reads an older hub that sends no confirmation', () => {
  expect(armNote({job})).toBe('armed · every weekday at 8:00 (0 8 * * 1-5), on its cadence');
  expect(armNote({job, first_run: {status: 'queued'}})).toContain('first run now');
});

it('a one-shot is armed for its time, never on a cadence (H450)', () => {
  const at = '2026-10-01T06:00:00+00:00';
  const job = {schedule_text: 'in 30m', cron: `@at ${at}`, one_shot: true, run_at: at};
  const when = onceAt(job);
  expect(when).toMatch(/^once at 2026-10-0[12] \d{2}:\d{2}$/);
  expect(armNote({job, first_run: null})).toBe(`armed · in 30m (${when})`);
  expect(armNote({job, first_run: null, confirmation: 'in 30m: runs once at 2026-10-01 06:00 UTC'}))
    .toBe('armed · in 30m: runs once at 2026-10-01 06:00 UTC');
  expect(onceAt({run_at: 'not a date'})).toBe('');
  expect(onceAt({})).toBe('');
});
