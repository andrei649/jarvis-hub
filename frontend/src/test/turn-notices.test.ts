import { describe, expect, it } from 'vitest';
import { noticeMessages, noticesFrom } from '../turn-notices';

const deferred = { code: 'compaction_deferred', text: 'The conversation summary is taking longer than usual.' };

describe('turn notices (H674)', () => {
  it('reads the notices an end event carries', () => {
    expect(noticesFrom({ type: 'end', notices: [deferred] })).toEqual([deferred]);
  });

  it('shows each as a system line under the reply', () => {
    expect(noticeMessages({ type: 'end', notices: [deferred] }, '12:00')).toEqual([
      { role: 'agent', who: 'system', role_label: '', ts: '12:00', text: 'ℹ ' + deferred.text, notice: 'compaction_deferred' },
    ]);
  });

  it('says nothing for an event with none, or an older server that sends no field', () => {
    expect(noticeMessages({ type: 'end', notices: [] }, '12:00')).toEqual([]);
    expect(noticeMessages({ type: 'end' }, '12:00')).toEqual([]);
    expect(noticeMessages(null, '12:00')).toEqual([]);
  });

  it('drops malformed entries and repeats, and bounds what it shows', () => {
    const noisy = [deferred, deferred, { code: 7, text: 'x' }, { code: 'a' }, 'text', null,
      { code: 'long', text: 'y'.repeat(2000) }, ...Array.from({ length: 9 }, (_, i) => ({ code: `c${i}`, text: 't' }))];
    const got = noticesFrom({ notices: noisy });
    expect(got.map((n) => n.code)).toEqual(['compaction_deferred', 'long', 'c0', 'c1', 'c2']);
    expect(got[1].text.length).toBe(400);
    expect(noticesFrom({ notices: 'not a list' })).toEqual([]);
    expect(noticesFrom({ notices: { code: 'x', text: 'an object, not a list' } })).toEqual([]);
    expect(noticesFrom({ notices: [{ code: 'blank', text: '   ' }] })).toEqual([]);
  });
});
