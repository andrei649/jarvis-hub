// Real shipped settings methods and HTML, with backend responses stubbed. No WebGL boot.
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, it } from 'vitest';
import { JSDOM } from 'jsdom';

const appRoot = path.resolve(import.meta.dirname, '../../apps/jarvis-os/public');
let dom, app, saved, status;

beforeEach(() => {
  dom = new JSDOM(fs.readFileSync(path.join(appRoot, 'index.html'), 'utf8'),
    { runScripts: 'outside-only', url: 'http://localhost:4719' });
  status = { ok: true, activeEngine: 'vault_rag', preferredProvider: 'auto',
    cloudConsent: false, providers: { anthropic: true, openai: true, gemini: true,
      openrouter: true, elevenlabs: true }, claudeSubscription: {}, ollama: {} };
  saved = [];
  dom.window.apiGet = async () => ({ json: async () => status });
  dom.window.apiPost = async (route, payload) => {
    saved.push({ route, payload });
    return { ok: true, json: async () => ({ ok: true }) };
  };
  dom.window.HUB = false;
  const source = fs.readFileSync(path.join(appRoot, 'js/main.js'), 'utf8')
    .replace(/^import .*;\r?\n/gm, '')
    .replace(/window.addEventListener\("DOMContentLoaded",[\s\S]*$/, 'window.App = JarvisOSApp;');
  dom.window.eval(source);
  app = Object.create(dom.window.App.prototype);
  app.dataset = { nodes: [] };
  app.loadServerBrain = async () => {};
});

afterEach(() => dom.window.close());

it('masks OpenRouter and the later voice key, then preserves masks on save', async () => {
  await app.refreshAIStatus();
  const doc = dom.window.document;
  for (const id of ['cfg-anthropic', 'cfg-openai', 'cfg-gemini', 'cfg-openrouter-key', 'cfg-elevenlabs']) {
    expect(doc.getElementById(id).value, id).toBe('***');
  }
  app._bindGlobalControls();
  doc.getElementById('cfg-save-btn').click();
  await Promise.resolve();
  expect(saved[0].payload.openrouterKey).toBe('***');
  expect(saved[0].payload.elevenlabsKey).toBe('***');
});

it('loads consent only from an exact boolean and saves the checked choice', async () => {
  await app.refreshAIStatus();
  const checkbox = dom.window.document.getElementById('cfg-cloud-consent');
  expect(checkbox).not.toBeNull();
  expect(checkbox.checked).toBe(false);
  status.cloudConsent = 'true';
  await app.refreshAIStatus();
  expect(checkbox.checked).toBe(false);
  status.cloudConsent = true;
  await app.refreshAIStatus();
  expect(checkbox.checked).toBe(true);
  app._bindGlobalControls();
  checkbox.checked = false;
  dom.window.document.getElementById('cfg-save-btn').click();
  await Promise.resolve();
  expect(saved[0].payload.cloudConsent).toBe(false);
});

it('renders a local default and warns what cloud consent sends', () => {
  const doc = dom.window.document;
  expect(doc.getElementById('cfg-preferred-provider').value).toBe('ollama');
  expect(doc.querySelector('label[for="cfg-cloud-consent"]').textContent)
    .toMatch(/prompts.*retrieved.*notes/i);
});

it('shows failed revocation save and retains the unchecked intent', async () => {
  status.cloudConsent = true;
  await app.refreshAIStatus();
  const doc = dom.window.document;
  app._bindGlobalControls();
  doc.getElementById('cfg-cloud-consent').checked = false;
  dom.window.apiPost = async () => ({ ok: false, json: async () => ({ ok: false, error: 'synthetic disk failure' }) });
  doc.getElementById('cfg-save-btn').click();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(doc.getElementById('cfg-status-msg').textContent).toMatch(/could not save/i);
  expect(doc.getElementById('cfg-status-msg').textContent).not.toMatch(/Saved!/);
  expect(doc.getElementById('cfg-cloud-consent').checked).toBe(false);
});
