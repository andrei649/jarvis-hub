import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { PROVENANCE_STRINGS, namesCloudModel, providerName, replyMarker, replyMarkerWords } from './provenance';

const pair = (provider: string, model: string) => ({ provider, model });
const words = (m: ReturnType<typeof replyMarker>, lang = 'en') => replyMarkerWords(m, lang);

describe('provenance strings', () => {
  it('are complete in English and Romanian', () => expect(stringProblems(PROVENANCE_STRINGS)).toEqual([]));
});

describe('replyMarker: every row of gap-5 §7.1', () => {
  it('CLOUD · <provider>: a cloud adapter is measured at the first hop', () => {
    const m = replyMarker({ models: [pair('anthropic', 'claude-sonnet-4-5')] });
    expect(m).toEqual({ kind: 'cloud', basis: 'measured', provider: 'anthropic', model: 'claude-sonnet-4-5', more: 0, verified: false });
    expect(words(m).text).toBe('Sent to Anthropic (cloud) · claude-sonnet-4-5');
    expect(words(m).warning).toBeNull();
    expect(words(replyMarker({ models: [pair('gemini', 'gemini-2.5')] })).text).toBe('Sent to Gemini (cloud) · gemini-2.5');
    expect(words(replyMarker({ models: [pair('some-new-adapter', 'm')] })).text).toBe('Sent to some-new-adapter (cloud) · m');
  });

  it('LOCAL RUNNER: Ollama or LM Studio, measured at the first hop and never verified', () => {
    for (const provider of ['ollama', 'lm-studio', 'lmstudio', 'OLLAMA']) {
      const m = replyMarker({ models: [pair(provider, 'gemma-4-31b')] });
      expect([m.kind, m.basis, m.verified], provider).toEqual(['localRunner', 'measured', false]);
    }
    expect(words(replyMarker({ models: [pair('ollama', 'gemma-4-31b')] })).text)
      .toBe('Sent to Ollama on this computer · gemma-4-31b · where it ran is not verified');
    expect(words(replyMarker({ models: [pair('lm-studio', 'q')] })).text).toContain('LM Studio on this computer');
  });

  it('RUNNER → CLOUD: a model id that says cloud is a warning, by name, whatever the route', () => {
    for (const model of ['nemotron-3-ultra:cloud', 'gpt-oss:120b-cloud', 'Qwen3:CLOUD']) {
      const m = replyMarker({ models: [pair('ollama', model)] });
      expect([m.kind, m.basis, m.model], model).toEqual(['cloudName', 'derived', model]);
      expect(words(m).warning).toBe(`⚠ ${model} names a cloud model`);
      expect(words(m).warningWhy).toContain('may have forwarded the prompt off this machine');
      expect(words(m).text).not.toContain('not verified');
    }
    expect(namesCloudModel('cloudflare-llama')).toBe(false);
    expect(namesCloudModel('my-cloudy:7b')).toBe(false);
    expect(namesCloudModel('llama3:8b')).toBe(false);
  });

  it('THIS MACHINE · enforced is never produced: the receipt carries no such flag, and the suffix is not parsed', () => {
    for (const model of ['gemma:local', 'test:latest:local', 'x:local']) {
      const m = replyMarker({ models: [pair('ollama', model)] });
      expect(m.kind, model).toBe('localRunner');
      expect(m.verified).toBe(false);
      expect(JSON.stringify(words(m)).toLowerCase()).not.toMatch(/this machine|enforced|runs on this/);
    }
    const kinds = ['anthropic', 'ollama', 'lm-studio'].map((p) => replyMarker({ models: [pair(p, 'm:local')] }).kind);
    expect(kinds).not.toContain('thisMachine');
  });

  it('no model call: the turn\'s usage basis is measured_zero', () => {
    const m = replyMarker({ models: [], usageBasis: 'measured_zero' });
    expect(m).toEqual({ kind: 'noModelCall', basis: 'measured', provider: null, model: null, more: 0, verified: false });
    expect(words(m).text).toBe('No model call');
    expect(replyMarker({ usageBasis: 'measured_zero' }).kind).toBe('noModelCall');
  });

  it('not reported: no receipt', () => {
    for (const input of [undefined, null, {}, { models: [] }, { models: null }, { models: [], usageBasis: 'estimated' }]) {
      const m = replyMarker(input as any);
      expect([m.kind, m.basis], JSON.stringify(input)).toEqual(['notReported', 'unknown']);
    }
    expect(words(replyMarker(null)).text).toBe('Where it ran: not reported');
  });

  it('a receipt wins over the usage basis when both are present', () => {
    expect(replyMarker({ models: [pair('ollama', 'm')], usageBasis: 'measured_zero' }).kind).toBe('localRunner');
  });

  it('ignores malformed pairs rather than guessing', () => {
    const m = replyMarker({ models: [{ provider: '', model: 'x' }, { provider: 'ollama', model: '' }, null as any, { provider: 3 as any, model: 'y' }, pair('ollama', 'ok')] });
    expect([m.kind, m.model, m.more]).toEqual(['localRunner', 'ok', 0]);
    expect(replyMarker({ models: [{ provider: '', model: 'x' }] }).kind).toBe('notReported');
  });
});

describe('replyMarker: several pairs', () => {
  it('shows the least private one and counts the rest', () => {
    const m = replyMarker({ models: [pair('ollama', 'a'), pair('anthropic', 'b'), pair('lm-studio', 'c')] });
    expect([m.kind, m.provider, m.model, m.more]).toEqual(['cloud', 'anthropic', 'b', 2]);
    expect(words(m).more).toBe('+2 more');
    expect(words(m, 'ro').more).toBe('+2 în plus');
  });

  it('ranks a cloud name above a plain local runner, and a cloud adapter above both', () => {
    expect(replyMarker({ models: [pair('ollama', 'a'), pair('ollama', 'b:cloud')] })).toMatchObject({ kind: 'cloudName', model: 'b:cloud', more: 1 });
    expect(replyMarker({ models: [pair('ollama', 'b:cloud'), pair('gemini', 'g')] })).toMatchObject({ kind: 'cloud', model: 'g' });
  });

  it('keeps the first of equals, and reads at most eight pairs', () => {
    expect(replyMarker({ models: [pair('ollama', 'first'), pair('ollama', 'second')] })).toMatchObject({ model: 'first', more: 1 });
    expect(replyMarker({ models: Array.from({ length: 12 }, (_, i) => pair('ollama', `m${i}`)) }).more).toBe(7);
  });
});

describe('provider names and Romanian', () => {
  it('names the known adapters and keeps an unknown id as sent', () => {
    expect([providerName('ollama'), providerName('lm-studio'), providerName('anthropic'), providerName('mystery')]).toEqual(['Ollama', 'LM Studio', 'Anthropic', 'mystery']);
  });
  it('speaks Romanian', () => {
    expect(words(replyMarker({ models: [pair('anthropic', 'c')] }), 'ro').text).toBe('Trimis către Anthropic (cloud) · c');
    expect(words(replyMarker({ models: [pair('ollama', 'g')] }), 'ro').text).toContain('unde a rulat nu este verificat');
    expect(words(replyMarker(null), 'ro').text).toBe('Unde a rulat: neraportat');
  });
});
