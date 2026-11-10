// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { IntegrationsPanel } from './integrations';
import { CONSOLE_PANELS } from '../console-routes';

const SECRET = 'exa-typed-secret-0123456789-WXYZ';

const facts = (host, extra = {}) => ({ host, host_country: null, data_policy: 'unknown',
  data_policy_note: 'not verified', price_known: 'no', price_note: 'Nerva has no price', receives: 'your search queries', ...extra });
const row = (over) => ({
  id: 'search.exa', kind: 'search', name: 'exa', display_name: 'Exa', origin: 'hermes', status: 'not_set_up',
  key: { names: ['EXA_API_KEY'], name: 'EXA_API_KEY', set: false, source: null, hint: null, editable: true, own: true, shared_with: [] },
  facts: facts('api.exa.ai'), selectable: true, selected: false, choice_editable: true, models: [], last_test: null, ...over,
});

const listing = (rows) => ({
  integrations: rows,
  skills: { id: 'skills.hermes-catalog', kind: 'skills', origin: 'hermes', display_name: 'Hermes skills catalog',
    available: true, commit: '9c0560f8', installable: 125, status: 'active', where: 'skills-import' },
  search: { backend: 'auto', answers: 'tavily', choice_source: null },
  model: { selected: '' }, precedence: 'env',
});

const SET = row({ status: 'key_set', key: { names: ['EXA_API_KEY'], name: 'EXA_API_KEY', set: true, source: 'hub', hint: '…WXYZ', editable: true, own: true, shared_with: [] } });
const DEEPSEEK = row({ id: 'model.deepseek', kind: 'model', name: 'deepseek', display_name: 'DeepSeek', status: 'key_set',
  key: { names: ['DEEPSEEK_API_KEY'], name: 'DEEPSEEK_API_KEY', set: true, source: 'hub', hint: '…7788', editable: true, own: true, shared_with: [] },
  facts: facts('api.deepseek.com', { receives: 'your conversations (the prompts and replies of the turns it answers)' }),
  models: ['deepseek-v4-pro', 'deepseek-flash'] });
const ENV = row({ id: 'search.parallel', name: 'parallel', display_name: 'Parallel', status: 'key_set',
  key: { names: ['PARALLEL_API_KEY'], name: 'PARALLEL_API_KEY', set: true, source: 'env', hint: null, editable: false, own: true, shared_with: [] },
  facts: facts('api.parallel.ai') });

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    calls.push({ url: String(url), method, body: init.body ? JSON.parse(init.body) : undefined });
    const answer = routes(String(url), method, init.body ? JSON.parse(init.body) : undefined, calls);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
  });
  return calls;
}

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('Integrations panel', () => {
  it('is registered as a console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'integrations', label: 'Integrations', group: 'Start', component: 'IntegrationsPanel' });
  });

  it('lists kind, origin, status, host and data facts, and links the skills catalog', async () => {
    hub(() => ({ status: 200, body: listing([row({}), { ...DEEPSEEK, status: 'active', selected: true }, ENV,
      row({ id: 'search.tavily', name: 'tavily', display_name: 'Tavily', origin: 'native', status: 'error', facts: facts('api.tavily.com') })]) }));
    render(<IntegrationsPanel />);
    const exa = (await screen.findByText('Exa')).closest('li');
    expect(within(exa).getByText('search')).toBeTruthy();
    expect(within(exa).getByText('from Hermes')).toBeTruthy();
    expect(within(exa).getByText('not set up')).toBeTruthy();
    expect(within(exa).getByText(/api\.exa\.ai/)).toBeTruthy();
    expect(within(exa).getByText(/data not verified · price unknown/)).toBeTruthy();
    const ds = screen.getByText('DeepSeek').closest('li');
    expect(within(ds).getByText('active')).toBeTruthy();
    expect(within(ds).getByText('in use')).toBeTruthy();
    expect(within(screen.getByText('Tavily').closest('li')).getByText('native')).toBeTruthy();
    expect(within(screen.getByText('Tavily').closest('li')).getByText('error')).toBeTruthy();
    expect(screen.getByText(/125 installable/)).toBeTruthy();
    expect(screen.getByText('open the catalog')).toBeTruthy();
    fireEvent.click(screen.getByText('models'));
    expect(screen.queryByText('Exa')).toBeNull();
    expect(screen.getByText('DeepSeek')).toBeTruthy();
  });

  it('saves a key through a labelled password field and never shows it back', async () => {
    let saved = false;
    const calls = hub((url, method) => {
      if (method === 'PUT') { saved = true; return { status: 200, body: { ok: true, applied: 'now' } }; }
      return { status: 200, body: listing([saved ? SET : row({})]) };
    });
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'set up Exa' }));
    const input = screen.getByLabelText(/API key for Exa/);
    expect(input.getAttribute('type')).toBe('password');
    fireEvent.change(input, { target: { value: SECRET } });
    expect(input.value).toBe(SECRET);
    fireEvent.click(screen.getByText('save key'));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    const put = calls.find((c) => c.method === 'PUT');
    expect(put.url).toContain('/api/admin/integrations/search.exa/key');
    expect(put.body).toEqual({ value: SECRET });
    await screen.findByText(/key saved · in effect now/);
    await screen.findByText('(…WXYZ)');
    expect(document.body.textContent).not.toContain(SECRET);
    expect(screen.getByLabelText(/Replace the key for Exa/).value).toBe('');
    fireEvent.click(screen.getByText('remove key'));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/search.exa/key'))).toBe(true));
  });

  it('a key set in .env cannot be edited here', async () => {
    hub(() => ({ status: 200, body: listing([ENV]) }));
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'manage Parallel' }));
    expect(screen.queryByLabelText(/key for Parallel/)).toBeNull();
    expect(screen.getByText(/edit it there/)).toBeTruthy();
  });

  it('a key or search choice the administrator pinned is shown as managed and read-only (G1)', async () => {
    const pinned = { ...ENV, key: { ...ENV.key, source: 'managed' } };
    hub(() => ({ status: 200, body: { ...listing([pinned]), search: { backend: 'tavily', answers: 'tavily', choice_source: 'managed' } } }));
    render(<IntegrationsPanel />);
    expect(await screen.findByText(/\(🔒 managed by your administrator\)/)).toBeTruthy();
    expect(screen.queryByText('choose automatically')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'manage Parallel' }));
    expect(screen.queryByLabelText(/key for Parallel/)).toBeNull();
    expect(screen.getByTestId('key-managed').textContent).toContain('managed by your administrator');
  });

  it('the test button shows the hub plain-language answer', async () => {
    const calls = hub((url, method) => (method === 'POST' && url.endsWith('/test')
      ? { status: 200, body: { test: { ok: false, verdict: 'auth_failed', message: 'The provider rejected the key. Check that it was copied whole and is still valid.' } } }
      : { status: 200, body: listing([DEEPSEEK]) }));
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'manage DeepSeek' }));
    fireEvent.click(screen.getByRole('button', { name: 'test DeepSeek' }));
    await screen.findByText(/The provider rejected the key/);
    expect(calls.filter((c) => c.url.endsWith('/test')).map((c) => c.url)).toEqual(['/api/admin/integrations/model.deepseek/test']);
  });

  it('one consent card with the facts and one action sends exactly the acknowledgements asked', async () => {
    const guards = [
      { guard: 'data_policy', needs: 'acknowledge_training', setting: 'llm.compatible_model', provider: 'deepseek', model: 'deepseek-v4-pro', message: 'deepseek-v4-pro on DeepSeek: how this vendor handles your prompts has not been verified' },
      { guard: 'cost', needs: 'confirm_expensive', setting: 'llm.compatible_model', provider: 'deepseek', model: 'deepseek-v4-pro', message: 'Nerva has no price for this model' },
    ];
    const calls = hub((url, method, body) => {
      if (method === 'POST' && url.endsWith('/use')) {
        if (!body.acknowledge_training) return { status: 409, body: { error: 'selection_guard', needs: ['acknowledge_training', 'confirm_expensive'], guards } };
        return { status: 200, body: { ok: true, applied: 'now' } };
      }
      return { status: 200, body: listing([DEEPSEEK]) };
    });
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'manage DeepSeek' }));
    expect(screen.getByLabelText('Model').value).toBe('deepseek-v4-pro');
    fireEvent.click(screen.getByText('use this provider'));
    const card = await screen.findByRole('alertdialog');
    expect(within(card).getByText(/your conversations/)).toBeTruthy();
    expect(within(card).getByText(/DeepSeek \(api\.deepseek\.com\)/)).toBeTruthy();
    expect(within(card).getByText('not recorded')).toBeTruthy();
    expect(within(card).getByText('not verified')).toBeTruthy();
    expect(within(card).getByText(/unknown · Nerva has no price/)).toBeTruthy();
    expect(within(card).getByText(/audit log/)).toBeTruthy();
    const first = calls.filter((c) => c.url.endsWith('/use'));
    expect(first).toHaveLength(1);
    expect(first[0].body).toEqual({ model: 'deepseek-v4-pro' });
    fireEvent.click(within(card).getByText('I understand, use it'));
    await screen.findByText(/in use now · deepseek-v4-pro/);
    const uses = calls.filter((c) => c.url.endsWith('/use'));
    expect(uses[1].body).toEqual({ model: 'deepseek-v4-pro', acknowledge_training: true, confirm_expensive: true });
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('cancel on the consent card sends nothing more', async () => {
    const calls = hub((url, method) => (method === 'POST'
      ? { status: 409, body: { error: 'selection_guard', needs: ['acknowledge_training'], guards: [{ guard: 'data_policy', needs: 'acknowledge_training', setting: 'JARVIS_WEB_BACKEND', provider: 'exa', model: '', message: 'Exa receives your search queries' }] } }
      : { status: 200, body: listing([SET]) }));
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'manage Exa' }));
    fireEvent.click(screen.getByText('use for searches'));
    const card = await screen.findByRole('alertdialog');
    fireEvent.click(within(card).getByText('Cancel'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
  });

  it('every control is a labelled, keyboard-reachable element', async () => {
    hub(() => ({ status: 200, body: listing([SET]) }));
    render(<IntegrationsPanel />);
    const toggle = await screen.findByRole('button', { name: 'manage Exa' });
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(toggle.tabIndex).toBe(0);
    fireEvent.click(toggle);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByLabelText('Find')).toBeTruthy();
    for (const el of document.querySelectorAll('input')) {
      expect(document.querySelector(`label[for="${el.id}"]`)).toBeTruthy();
    }
  });

  it('a key set for a sibling shows as shared, not as this provider key', async () => {
    const cn = row({ id: 'model.alibaba-cn', kind: 'model', name: 'alibaba-cn', display_name: 'Alibaba Cloud DashScope (China)',
      status: 'shared', facts: facts('dashscope.aliyuncs.com', { host_country: 'China (mainland)' }),
      key: { names: ['DASHSCOPE_API_KEY'], name: 'DASHSCOPE_API_KEY', set: true, source: 'hub', hint: '…0001', editable: true,
        own: false, shared_with: ['model.alibaba'] } });
    hub(() => ({ status: 200, body: listing([cn]) }));
    render(<IntegrationsPanel />);
    const line = (await screen.findByText('Alibaba Cloud DashScope (China)')).closest('li');
    expect(within(line).getByText('shared key')).toBeTruthy();
    fireEvent.click(within(line).getByRole('button', { name: /Alibaba Cloud DashScope \(China\)/ }));
    expect(screen.getByText(/was set for model\.alibaba/)).toBeTruthy();
    expect(screen.queryByText('remove key')).toBeNull();
  });

  it('a shared key name asks once whether it is the same key, then resends with that answer', async () => {
    const calls = hub((url, method, body) => {
      if (method === 'PUT') {
        if (!body.same_key) return { status: 409, body: { error: 'shared_key', detail: 'DASHSCOPE_API_KEY is also read by Alibaba Cloud DashScope (China).' } };
        return { status: 200, body: { ok: true, applied: 'now' } };
      }
      return { status: 200, body: listing([row({ id: 'model.alibaba', kind: 'model', name: 'alibaba', display_name: 'Alibaba', facts: facts('dashscope-intl.aliyuncs.com') })]) };
    });
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'set up Alibaba' }));
    fireEvent.change(screen.getByLabelText(/API key for Alibaba/), { target: { value: SECRET } });
    fireEvent.click(screen.getByText('save key'));
    await screen.findByText(/also read by Alibaba Cloud DashScope \(China\)/);
    expect(document.body.textContent).not.toContain(SECRET);
    fireEvent.click(screen.getByText('yes, it is the same key'));
    await screen.findByText(/key saved · in effect now/);
    const puts = calls.filter((c) => c.method === 'PUT');
    expect(puts.map((c) => c.body)).toEqual([{ value: SECRET }, { value: SECRET, same_key: true }]);
  });

  it('a provider used as soon as its key is set asks for consent when the key is saved', async () => {
    const gemini = row({ id: 'model.gemini', kind: 'model', name: 'gemini', display_name: 'Google Gemini', origin: 'native',
      selectable: false, facts: facts('generativelanguage.googleapis.com', { receives: 'your conversations' }),
      key: { names: ['GEMINI_API_KEY'], name: 'GEMINI_API_KEY', set: false, source: null, hint: null, editable: true, own: false, shared_with: [] } });
    const calls = hub((url, method, body) => {
      if (method === 'PUT') {
        if (!body.acknowledge_training) return { status: 409, body: { error: 'selection_guard', needs: ['acknowledge_training'],
          guards: [{ guard: 'data_policy', needs: 'acknowledge_training', setting: 'GEMINI_API_KEY', provider: 'gemini', model: '', message: 'Google Gemini answers as soon as this key is set' }] } };
        return { status: 200, body: { ok: true, applied: 'now' } };
      }
      return { status: 200, body: listing([gemini]) };
    });
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'set up Google Gemini' }));
    fireEvent.change(screen.getByLabelText(/API key for Google Gemini/), { target: { value: SECRET } });
    fireEvent.click(screen.getByText('save key'));
    const card = await screen.findByRole('alertdialog');
    expect(within(card).getByText(/answers as soon as this key is set/)).toBeTruthy();
    fireEvent.click(within(card).getByText('I understand, use it'));
    await screen.findByText(/key saved · in effect now/);
    expect(calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([
      { value: SECRET }, { value: SECRET, acknowledge_training: true }]);
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it('offers to remove an older stored copy when .env took the key over', async () => {
    const calls = hub(() => ({ status: 200, body: listing([{ ...ENV, key: { ...ENV.key, stored_copy: true } }]) }));
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'manage Parallel' }));
    fireEvent.click(screen.getByText('remove the stored copy'));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.includes('/search.parallel/key'))).toBe(true));
  });

  it('chooses a video provider through the consent card and can turn video off (G19)', async () => {
    const FAL = row({ id: 'video.fal', kind: 'video', name: 'fal', display_name: 'FAL (video)', status: 'key_set',
      key: { names: ['FAL_KEY'], name: 'FAL_KEY', set: true, source: 'hub', hint: null, editable: true, own: true, shared_with: [] },
      facts: facts('queue.fal.run', { receives: 'your video prompts and the images you ask it to animate',
        price_known: 'some', price_note: 'paid per second of video' }), models: ['pixverse-v6'] });
    const guards = [
      { guard: 'data_policy', needs: 'acknowledge_training', setting: 'JARVIS_VIDEO_PROVIDER', provider: 'fal', model: '', message: 'FAL (video) receives your video prompts' },
      { guard: 'cost', needs: 'confirm_expensive', setting: 'JARVIS_VIDEO_PROVIDER', provider: 'fal', model: '', message: 'billed per second of video' },
    ];
    let chosen = false;
    const calls = hub((url, method, body) => {
      if (method === 'POST' && url.endsWith('/use')) {
        if (!body.acknowledge_training) return { status: 409, body: { error: 'selection_guard', needs: ['acknowledge_training', 'confirm_expensive'], guards } };
        chosen = true;
        return { status: 200, body: { ok: true, applied: 'now' } };
      }
      if (method === 'DELETE') { chosen = false; return { status: 200, body: { ok: true } }; }
      return { status: 200, body: { ...listing([chosen ? { ...FAL, status: 'active', selected: true } : FAL]),
        video: { provider: chosen ? 'fal' : null, choice_source: chosen ? 'hub' : null } } };
    });
    render(<IntegrationsPanel />);
    fireEvent.click(await screen.findByText('video'));
    fireEvent.click(await screen.findByRole('button', { name: 'manage FAL (video)' }));
    fireEvent.click(screen.getByText('use for videos'));
    const card = await screen.findByRole('alertdialog');
    expect(within(card).getByText(/your video prompts and the images/)).toBeTruthy();
    fireEvent.click(within(card).getByText('I understand, use it'));
    await screen.findByText(/videos use it now/);
    const uses = calls.filter((c) => c.url.endsWith('/video.fal/use'));
    expect(uses[1].body).toEqual({ acknowledge_training: true, confirm_expensive: true });
    fireEvent.click(await screen.findByText('turn video off'));
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url.endsWith('/video-choice'))).toBe(true));
  });
});
