// H262 review F13 — the /admin (v1) settings save when the hub refuses a category's write.
// A retention write the approval queue cannot take answers 503 and writes nothing of that
// category, not even its other keys: the page keeps every dirty key of that category and
// names them all as not saved, with the hub's reason (its `reason`, then its `error`).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function backend() {
  const json = (body, status = 200) => Promise.resolve({ json: async () => body, ok: status < 400, status });
  return vi.fn((url) => {
    if (url === '/api/admin/settings') {
      return json({
        general: [{ key: 'timezone', label: 'Timezone', kind: 'select', value: 'UTC', opts: ['UTC', 'Europe/Bucharest'] }],
        security: [
          { key: 'scan_input', label: 'Scan input', kind: 'toggle', value: true },
          { key: 'scan_output', label: 'Scan output', kind: 'toggle', value: true },
        ],
      });
    }
    if (url === '/api/admin/settings/security') {        // e.g. a gated key the queue could not take
      return json({ error: 'retention_needs_approval', reason: 'approval_queue_unavailable',
                    gated: ['security.scan_input'] }, 503);
    }
    if (url.startsWith('/api/admin/settings/')) return json({ updated: 1 });
    return json({});
  });
}

describe('v1 admin — a refused category save keeps the whole category dirty', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('lists every key of the refused category as not saved and keeps them for another try', async () => {
    const fetch = backend();
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], fetch, lang: 'ro' });
    await env.flush();
    const root = env.document.getElementById('root');
    env.click([...root.querySelectorAll('.admin-nav button')].find((b) => b.textContent.includes('Configurări Globale')));
    await env.flush();
    const boxes = [...root.querySelectorAll('.admin-row input[type=checkbox]')];
    expect(boxes.length).toBe(2);
    for (const box of boxes) env.toggle(box);
    await env.flush();
    const saveBtn = () => [...root.querySelectorAll('button')].find((b) => /salv|save/i.test(b.textContent));
    env.click(saveBtn());
    await env.flush();
    await env.flush();
    expect(fetch).toHaveBeenCalledWith('/api/admin/settings/security', expect.objectContaining({ method: 'PUT' }));
    const text = root.textContent;
    expect(text).toContain('scan_input');
    expect(text).toContain('scan_output');
    expect(text).toContain('approval_queue_unavailable');
    expect(text).not.toContain('salvați cu succes');
    expect(saveBtn(), 'the refused edits are still unsaved').toBeTruthy();
  });
});

// H262 review round 2 — the hub judges each settings write against what is stored, never a
// waiting approval card, so a save that carries both sends `retention` first and `memory`
// (archiving on, which may go to Approvals) only after it. The v1 page lists neither a
// retention key nor memory.auto_archive_days today, so the order is pinned on the helper
// the save uses; a save still sends every category it has.
describe('v1 admin — retention is saved before memory', () => {
  let env;
  afterEach(() => env && env.cleanup());

  it('orders retention, then memory, then the rest as they came', () => {
    env = loadHud({ files: ['i18n', 'data', 'components', 'admin'], fetch: backend(), lang: 'ro',
                    expose: ['settingsSaveOrder'] });
    const order = env.hud.settingsSaveOrder;
    expect(typeof order).toBe('function');
    expect(order(['memory', 'security', 'retention', 'general'])).toEqual(['retention', 'memory', 'security', 'general']);
    expect(order(['general', 'memory'])).toEqual(['memory', 'general']);
    expect(order(['security', 'general'])).toEqual(['security', 'general']);
  });
});
