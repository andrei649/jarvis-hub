import { describe, expect, it } from 'vitest';
import { attentionFrom, tickerWarnings, type AttentionInput } from './attention';
import { calmObserver, checking, empty, intactChain, live, offlineReading, refused, stale, unknown } from './test-support';

const summary = (entries: number) => ({ entries, requests: entries, friction: { typed: 0, twoStep: 0, click: entries } });
const base = (over: Partial<AttentionInput> = {}): AttentionInput => ({
  docket: empty(summary(0)), payments: empty(0), observer: live(calmObserver), audit: live(intactChain), killSwitch: live({ halted: false }), ...over,
});

describe('attentionFrom', () => {
  it('has only the stop\'s word when nothing needs the owner', () => {
    expect(attentionFrom(base())).toEqual({ killSwitch: { key: 'killSwitch', state: 'armed' } });
  });

  it('notes the docket, the payments and the services only for a live positive count', () => {
    const a = attentionFrom(base({
      docket: live(summary(9)), payments: live(1),
      observer: live({ ...calmObserver, unhealthy: [{ key: 'service.qdrant', detail: 'x', severity: 'WARN', since: null }, { key: 'service.n8n', detail: 'y', severity: 'WARN', since: null }] }),
    }));
    expect(a.docket).toEqual({ key: 'docket', count: 9 });
    expect(a.payments).toEqual({ key: 'payments', count: 1 });
    expect(a.services).toEqual({ key: 'services', count: 2 });
  });

  it('never makes a note from a count that is unknown, refused, offline, stale or still being asked for', () => {
    for (const reading of [unknown(), refused(), offlineReading(), checking(), stale(summary(9))]) {
      const a = attentionFrom(base({ docket: reading as any, payments: reading as any }));
      expect(a.docket, reading.state).toBeUndefined();
      expect(a.payments, reading.state).toBeUndefined();
    }
    expect(attentionFrom(base({ docket: live(summary(0)), payments: live(0) }))).toEqual({ killSwitch: { key: 'killSwitch', state: 'armed' } });
  });

  it('services: the observer when it answered; the ticker\'s warnings only when it cannot be read', () => {
    const hub = { ticker: [{ verb: 'WARNING', text: 'docker down' }, { verb: 'ALERT', text: 'disk full' }, { verb: 'INFO', text: 'ok' }, { verb: 'WARNING', text: '  ' }] };
    expect(tickerWarnings(hub.ticker)).toBe(2);
    expect(attentionFrom(base({ observer: refused(), hub })).services).toEqual({ key: 'services', count: 2 });
    expect(attentionFrom(base({ observer: live({ enabled: false, probes: null, tracked: null, unhealthy: null }), hub })).services).toEqual({ key: 'services', count: 2 });
    expect(attentionFrom(base({ observer: live(calmObserver), hub })).services).toBeUndefined();   // the observer says nothing is down
    expect(attentionFrom(base({ observer: refused(), hub: { ticker: [] } })).services).toBeUndefined();   // an empty ticker proves nothing, and says nothing
    expect(attentionFrom(base({ observer: refused() })).services).toBeUndefined();
  });

  it('record: only when the chain is live and broken, with the entry when known', () => {
    expect(attentionFrom(base({ audit: live({ ...intactChain, valid: false, firstInvalidId: 412 }) })).record).toEqual({ key: 'record', brokenAt: 412 });
    expect(attentionFrom(base({ audit: live({ ...intactChain, valid: false, firstInvalidId: null }) })).record).toEqual({ key: 'record', brokenAt: null });
    expect(attentionFrom(base({ audit: refused() })).record).toBeUndefined();
    expect(attentionFrom(base({ audit: stale({ ...intactChain, valid: false, firstInvalidId: 1 }) })).record).toBeUndefined();
  });

  it('the stop: Armed, Halted, or Unknown — its word is always there', () => {
    expect(attentionFrom(base({ killSwitch: live({ halted: true }) })).killSwitch).toEqual({ key: 'killSwitch', state: 'halted' });
    for (const reading of [unknown(), refused(), offlineReading(), checking(), stale({ halted: false })]) {
      expect(attentionFrom(base({ killSwitch: reading as any })).killSwitch, reading.state).toEqual({ key: 'killSwitch', state: 'unknown' });
    }
  });
});
