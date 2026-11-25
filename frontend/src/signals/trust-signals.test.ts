import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { initialHubSnapshot } from '../frame/types';
import { T0, at, checking, hubOf, intactChain, live, refused, offlineReading, unknown } from './test-support';
import { TRUST_SIGNAL_STRINGS, trustSignals, type TrustSignalsInput } from './trust-signals';
import { SIGNAL_IDS, type SignalView } from './types';

const input = (over: Partial<TrustSignalsInput> = {}): TrustSignalsInput => ({ hub: hubOf(), now: T0, audit: live(intactChain, T0), ...over });
const by = (views: SignalView[], id: string) => views.find((v) => v.id === id) as SignalView;
const texts = (views: SignalView[]) => views.flatMap((v) => [v.label.long, v.label.short, v.value.long, v.value.short, v.value.marks, v.ident ?? '', ...v.detail]);

describe('trust signal strings', () => {
  it('are complete in English and Romanian', () => expect(stringProblems(TRUST_SIGNAL_STRINGS)).toEqual([]));
});

describe('trustSignals', () => {
  it('returns the six signals in running-head order, each with a mark, a basis line and a checked line', () => {
    const views = trustSignals(input());
    expect(views.map((v) => v.id)).toEqual([...SIGNAL_IDS]);
    for (const v of views) {
      expect(v.label.long, v.id).not.toBe('');
      expect(v.value.long, v.id).not.toBe('');
      expect(v.detail.some((line) => /^Checked at \d\d:\d\d$|^Not checked yet$/.test(line)), v.id).toBe(true);
    }
  });

  describe('egress', () => {
    it('says "No cloud model configured", declared — never that nothing can leave', () => {
      const v = by(trustSignals(input()), 'egress');
      expect(v.value.long).toBe('No cloud model configured');
      expect(v.value.short).toBe('No cloud model');
      expect(v.basis).toBe('declared');
      expect(v.mark).toBe('ok');
      expect(String(v.detail)).toContain('A setting, not a network measurement; plugins such as weather can still reach the internet.');
      expect(v.detail).toContain('Basis: declared, not measured');
    });

    it('dates the ledger window when it did not start today (the tallies count from the first row ever stored)', () => {
      const old = { external: 42, models: 0, since: new Date(2026, 9, 1, 11, 20).getTime() };
      const long = by(trustSignals(input({ egress: live(old) })), 'egress').value.long;
      expect(long).toMatch(/42 requests left this machine since .*1.*Oct.* 11:20/);
      expect(long).not.toMatch(/since 11:20/);
      expect(by(trustSignals(input({ egress: live({ ...old, since: at(10, 20) }) })), 'egress').value.long).toContain('since 10:20');
      expect(by(trustSignals(input({ egress: live(old) }), 'ro'), 'egress').value.long).toMatch(/din .*oct.* 11:20/i);
    });

    it('adds the measured ledger count only when the admin ledger answered', () => {
      const ledger = { external: 42, models: 0, since: at(10, 20) };
      const withLedger = by(trustSignals(input({ egress: live(ledger) })), 'egress');
      expect(withLedger.value.long).toBe('No cloud model configured · 42 requests left this machine since 10:20, 0 from models');
      expect(withLedger.value.short).toBe('No cloud model');
      expect(withLedger.detail).toContain('The request count is measured by the hub\'s egress ledger.');
      for (const egress of [refused(), checking(), unknown(), offlineReading(), null, undefined]) {
        expect(by(trustSignals(input({ egress: egress as any })), 'egress').value.long, String(egress && (egress as any).state)).toBe('No cloud model configured');
      }
      expect(by(trustSignals(input({ egress: live({ external: 1, models: null, since: null }) })), 'egress').value.long).toBe('No cloud model configured · 1 request left this machine');
    });

    it('names a configured cloud model, and says the strict-local flag is not proof', () => {
      const hub = hubOf({ trust: { mic: 'on', strictLocal: true, cloudAvailable: true, claudeAvailable: true } });
      const v = by(trustSignals(input({ hub })), 'egress');
      expect(v.value.long).toBe('Cloud model configured · Anthropic, Gemini or compatible');
      expect(v.mark).toBe('attn');
      expect(String(v.detail)).toContain('not proof that no cloud route is used');
      expect(by(trustSignals(input({ hub: hubOf({ trust: { mic: 'on', strictLocal: false, cloudAvailable: false, claudeAvailable: true } }) })), 'egress').value.long)
        .toBe('Cloud model configured · Anthropic');
    });

    it('is unknown when trust status did not answer, and says so', () => {
      const v = by(trustSignals(input({ hub: hubOf({ trust: null }) })), 'egress');
      expect([v.state, v.mark, v.value.long]).toEqual(['unknown', 'unknown', 'Unknown — trust status did not answer']);
      expect(by(trustSignals(input({ hub: initialHubSnapshot(false) })), 'egress').value.long).toBe('Checking…');
    });
  });

  describe('local route', () => {
    it('is a count with its window and basis, never a bare percentage', () => {
      const v = by(trustSignals(input()), 'localRoute');
      expect(v.label.long).toBe('Sent to local runners');
      expect(v.label.short).toBe('Local route');
      expect(v.value.long).toBe('115 of 121 runs · all time · by route');
      expect(v.value.short).toBe('115 of 121 · by route');
      expect(v.value.marks).toBe('115/121');
      expect(v.basis).toBe('declared');
      expect(String(v.detail)).toContain('not where the model computed');
      expect(String(v.detail)).toContain('6 runs recorded no route and are not counted as local.');
      expect(v.detail).toContain('Local includes runners on your home network.');
    });

    it('with no routed run is derived from configuration and shows no number', () => {
      const hub = hubOf({ locality: { local_pct: null, local: 0, cloud: 0, unknown: 0, total: 0 } });
      const v = by(trustSignals(input({ hub })), 'localRoute');
      expect(v.value.long).toBe('No runs recorded · derived from configuration');
      expect(v.basis).toBe('derived');
      expect(v.value.long).not.toMatch(/\d/);
    });

    it('says one thing, not two, when runs exist but none recorded a route', () => {
      const v = by(trustSignals(input({ hub: hubOf({ locality: { local_pct: null, local: 0, cloud: 0, unknown: 6, total: 6 } }) })), 'localRoute');
      expect(v.value.long).toBe('No run recorded a route · derived from configuration');
      expect(String(v.detail)).toContain('6 runs recorded no route');
      expect(String(v.detail)).not.toContain('No run has been recorded yet');
    });

    it('is stale, not live, on every snapshot-based reading once the snapshot has gone stale', () => {
      const views = trustSignals(input({ now: T0 + 100_000 }));
      for (const id of ['egress', 'localRoute', 'microphone', 'model'] as const) expect([id, by(views, id).state]).toEqual([id, 'stale']);
      expect(by(trustSignals(input()), 'egress').state).toBe('live');
    });

    it('flags a run that went to the cloud and is unknown when locality did not answer', () => {
      const hub = hubOf({ locality: { local_pct: 50, local: 1, cloud: 1, unknown: 0, total: 2 } });
      expect(by(trustSignals(input({ hub })), 'localRoute').mark).toBe('attn');
      const none = by(trustSignals(input({ hub: hubOf({ locality: null }) })), 'localRoute');
      expect([none.state, none.value.long, none.basis]).toEqual(['unknown', 'Unknown — locality did not answer', 'unknown']);
    });
  });

  describe('microphone', () => {
    it('reads the hub\'s permission: On, Muted, Unknown — and "listening now" only while it is', () => {
      const mic = (m: 'on' | 'off' | 'unknown') => hubOf({ trust: { mic: m, strictLocal: true, cloudAvailable: false, claudeAvailable: false } });
      expect(by(trustSignals(input({ hub: mic('on') })), 'microphone').value.long).toBe('On');
      expect(by(trustSignals(input({ hub: mic('off') })), 'microphone').value.long).toBe('Muted');
      expect(by(trustSignals(input({ hub: mic('unknown') })), 'microphone').value.long).toBe('Unknown');
      expect(by(trustSignals(input({ hub: mic('on'), voiceStatus: 'listening' })), 'microphone').detail).toContain('Listening now.');
      expect(by(trustSignals(input({ hub: mic('off'), voiceStatus: 'listening' })), 'microphone').detail).not.toContain('Listening now.');
      expect(by(trustSignals(input({ hub: mic('on'), voiceStatus: 'idle' })), 'microphone').detail).not.toContain('Listening now.');
      expect(by(trustSignals(input({ hub: hubOf({ trust: null }) })), 'microphone').value.long).toBe('Unknown');
    });
  });

  describe('model', () => {
    it('is the model id in mono plus its backend', () => {
      const v = by(trustSignals(input()), 'model');
      expect(v.ident).toBe('gemma-4-31b');
      expect(v.value.long).toBe('· ollama');
      expect(v.mark).toBe('ok');
      expect(v.detail).toContain('Configured model: gemma-4-31b (a setting, not a measurement).');
      expect(v.href).toBe('/v2/console/model-setup');
    });

    it('says what is wrong when there is no model or no backend, and Unknown when it did not say', () => {
      const m = (state: 'ready' | 'no_model' | 'offline' | 'unknown') => by(trustSignals(input({ hub: hubOf({ llm: { state, model: null, residents: [] } }) })), 'model');
      expect(m('no_model').value.long).toBe('No model loaded');
      expect(m('no_model').mark).toBe('problem');
      expect(m('offline').value.long).toBe('No local backend reachable');
      expect(m('unknown').value.long).toBe('Unknown');
      expect(m('ready').value.long).toBe('Model loaded · ollama');
      expect(by(trustSignals(input({ hub: hubOf({ backend: 'none' }) })), 'model').value.long).toBe('');
    });

    it('is not asked of a hub that did not answer', () => {
      expect(by(trustSignals(input({ hub: hubOf({ state: 'offline', serverUp: false }) })), 'model').value.long).toBe('Unknown');
    });
  });

  describe('data on screen', () => {
    it('is Live · checked, Stale · checked, Offline · last good reading, Checking…', () => {
      expect(by(trustSignals(input()), 'data').value.long).toBe('Live · checked 10:50');
      expect(by(trustSignals(input({ now: T0 + 100_000 })), 'data').value.long).toBe('Stale · checked 10:50');
      const off = by(trustSignals(input({ hub: hubOf({ state: 'offline', serverUp: false, lastGoodAt: at(10, 44) }) })), 'data');
      expect([off.state, off.value.long]).toEqual(['offline', 'Offline · last good reading 10:44']);
      expect(by(trustSignals(input({ hub: initialHubSnapshot(false) })), 'data').value.long).toBe('Checking…');
    });
  });

  describe('audit chain', () => {
    it('is Intact · N sealed · verified, with its short form', () => {
      const v = by(trustSignals(input()), 'chain');
      expect(v.value.long).toBe('Intact · 921 sealed · verified 10:50');
      expect(v.value.short).toBe('Intact');
      expect(v.mark).toBe('chain');
      expect(v.label.short).toBe('Chain');
      expect(String(v.detail)).toContain('with a key');
    });

    it('says an unkeyed chain is not tamper evidence', () => {
      const v = by(trustSignals(input({ audit: live({ ...intactChain, tamperEvident: false }) })), 'chain');
      expect(String(v.detail)).toContain('not tamper evidence');
    });

    it('is Broken at entry N', () => {
      const v = by(trustSignals(input({ audit: live({ ...intactChain, valid: false, firstInvalidId: 412 }) })), 'chain');
      expect([v.mark, v.value.long]).toEqual(['problem', 'Broken at entry 412']);
    });

    it('is Unknown when it could not verify, and says why when refused or still checking', () => {
      expect(by(trustSignals(input({ audit: unknown() })), 'chain').value.long).toBe('Unknown — could not verify');
      expect(by(trustSignals(input({ audit: refused() })), 'chain').value.long).toBe('Unknown — needs the owner credential');
      expect(by(trustSignals(input({ audit: checking() })), 'chain').value.long).toBe('Checking…');
      expect(by(trustSignals(input({ audit: offlineReading() })), 'chain').state).toBe('offline');
    });

    it('keeps the last good verdict, drawn as stale, when the hub went away', () => {
      const v = by(trustSignals(input({ audit: offlineReading(intactChain) })), 'chain');
      expect([v.state, v.mark]).toEqual(['offline', 'stale']);
    });
  });
});

describe('what the running head never says', () => {
  const hubs = {
    healthy: hubOf(),
    cloud: hubOf({ trust: { mic: 'off', strictLocal: false, cloudAvailable: true, claudeAvailable: false } }),
    noRuns: hubOf({ locality: { local_pct: null, local: 0, cloud: 0, unknown: 0, total: 0 } }),
    allLocal: hubOf({ locality: { local_pct: 100, local: 41, cloud: 0, unknown: 0, total: 41 } }),
    nothing: hubOf({ trust: null, locality: null, llm: { state: 'unknown', model: null, residents: [] }, backend: null }),
    checking: initialHubSnapshot(false),
    offline: hubOf({ state: 'offline', serverUp: false, trust: null, locality: null }),
    demo: hubOf({ demo: true, state: 'demo' }),
  };
  const audits = [live(intactChain), refused(), checking(), unknown()];

  it.each(['en', 'ro'])('never "Sealed — nothing can leave", never a bare %%, in %s', (lang) => {
    for (const [name, hub] of Object.entries(hubs)) {
      for (const audit of audits) {
        const all = texts(trustSignals({ hub, audit: audit as any, now: T0, egress: live({ external: 42, models: 0, since: T0 }) }, lang)).join('\n');
        expect(all, name).not.toMatch(/sealed\s*[—-]\s*nothing|nothing can leave|nimic nu poate/i);
        expect(all, name).not.toMatch(/\d\s*%/);
        expect(all, name).not.toMatch(/\bSEALED\b/);
      }
    }
  });

  it('never draws 0 for a reading that is unknown', () => {
    const views = trustSignals({ hub: hubs.nothing, audit: checking() as any, now: T0 });
    for (const v of views.filter((x) => x.state === 'unknown')) {
      expect(`${v.value.long} ${v.value.short} ${v.value.marks}`, v.id).not.toMatch(/(^|\D)0(\D|$)/);
    }
    const route = by(views, 'localRoute');
    expect([route.state, route.value.long]).toEqual(['unknown', 'Unknown — locality did not answer']);
  });

  it('says Demo sample for every signal in demo and invents nothing', () => {
    const views = trustSignals({ hub: hubs.demo, audit: live(intactChain) as any, now: T0 });
    for (const v of views) expect([v.state, v.value.long, v.basis], v.id).toEqual(['demo', 'Demo sample', 'seeded']);
    // the narrower forms say Demo; the popover's first line says the whole word
    for (const v of views) expect([v.value.short, v.value.marks, v.detail[0]], v.id).toEqual(['Demo', 'Demo', 'Demo sample']);
  });

  it('speaks Romanian with diacritics', () => {
    const views = trustSignals(input(), 'ro');
    expect(by(views, 'egress').value.long).toBe('Niciun model cloud configurat');
    expect(by(views, 'localRoute').value.long).toBe('115 din 121 rulări · tot timpul · după rută');
    expect(by(views, 'chain').value.long).toBe('Intact · 921 sigilate · verificat la 10:50');
    expect(by(views, 'data').value.long).toBe('În direct · actualizat la 10:50');
  });
});
