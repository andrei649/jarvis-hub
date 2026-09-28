/* H273 — the ADMIN keys list names the layer each key came from (process
   environment, repo .env, data-home .env), from /api/admin/env/sources: names and
   layers only, never a value. */
import { expect, it } from 'vitest';
import { hydrateAdminKeys } from '../api/live';

const ENV = { OPENAI_API_KEY: 'sk-…ab', TELEGRAM_BOT_TOKEN: '****', PATH: '/usr/bin' };

it('names the layer each key came from, and nothing for a key it does not know', () => {
  const sources = { sources: [
    { key: 'OPENAI_API_KEY', layer: 'process', label: 'process environment', shadowed: ['repo_env'], masked: true },
  ] };
  const keys = hydrateAdminKeys(ENV, sources);
  expect(keys[0]).toEqual({ name: 'OPENAI_API_KEY', masked: 'sk-…ab', status: 'set', rotated: '',
    source: 'process environment, overriding repo .env' });
  expect(keys[1].name).toBe('TELEGRAM_BOT_TOKEN');
  expect('source' in keys[1]).toBe(false);
});

it('ignores a missing or malformed sources payload', () => {
  expect('source' in hydrateAdminKeys(ENV)[0]).toBe(false);
  expect('source' in hydrateAdminKeys(ENV, null)[0]).toBe(false);
  expect('source' in hydrateAdminKeys(ENV, { sources: 'nope' })[0]).toBe(false);
  expect('source' in hydrateAdminKeys(ENV, { sources: [{ key: 'OPENAI_API_KEY', label: 7 }] })[0]).toBe(false);
});

it('names every layer a key overrides, and only known layers', () => {
  const sources = { sources: [
    { key: 'OPENAI_API_KEY', layer: 'process', label: 'process environment', shadowed: ['repo_env', 'user_env', 'bogus'] },
    { key: 'TELEGRAM_BOT_TOKEN', layer: 'repo_env', label: 'repo .env', shadowed: [] },
  ] };
  const keys = hydrateAdminKeys(ENV, sources);
  expect(keys[0].source).toBe('process environment, overriding repo .env and data-home .env');
  expect(keys[1].source).toBe('repo .env');
});

it('says when the value a key was given in a .env file is not in effect', () => {
  const env = { NEO4J_PASSWORD: '****', OPENAI_API_KEY: 'sk-…ab' };
  const note = 'the hub reads it before the .env files are loaded: the .env value is not in effect, '
    + 'so set it in the process environment';
  const sources = { sources: [
    { key: 'NEO4J_PASSWORD', layer: 'repo_env', label: 'repo .env', shadowed: [], note },
    { key: 'OPENAI_API_KEY', layer: 'repo_env', label: 'repo .env', shadowed: [], note: '  ' },
  ] };
  const keys = hydrateAdminKeys(env, sources);
  expect(keys[0].source).toBe(`repo .env (${note})`);
  expect(keys[1].source).toBe('repo .env');
});
