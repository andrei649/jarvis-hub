import {expect, it} from 'vitest';
import {armNote} from '../panels/jobs';

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
