// @ts-nocheck
/* The seven inline HUD findings that all lived inside shared files — DRA-08's governed-
   tools checkbox, DRA-23's network headline, DRA-52's refusal text, DRA-47's tile label,
   the WORLD button sitting on top of the mode rail, the wall's "no live decision feed",
   and the three registry agents the demo corpus never had.

   Each one is a place the HUD said something it could not back. They are tested together
   because they were fixed together, and because the shape of the mistake is the same in
   all seven: a surface that had a true thing available and rendered a convenient one. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SandboxPanel, NetworkMonitorPanel } from '../gap';
import { refusalReason } from '../panel-kit';
import { decisionCard } from '../api/loaders';
import { V2 } from '../data';
import { RAIL_RESERVED_PX, WORLD_BUTTON_HEIGHT, WORLD_BUTTON_INSET } from '../world_app';
import worldSource from '../world_app.tsx?raw';
import modesSource from '../modes2.tsx?raw';
import wallSource from '../wall.tsx?raw';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockRoutes(routes, statusFor = () => 200) {
  const fn = vi.fn().mockImplementation((url) => {
    const key = Object.keys(routes).find((p) => String(url).includes(p));
    const status = statusFor(String(url));
    return Promise.resolve({
      ok: status < 400,
      status,
      json: async () => (key ? routes[key] : {}),
    });
  });
  global.fetch = fn;
  return fn;
}

/* ── DRA-08 · the governed-tools checkbox ─────────────────────────────────── */

describe('SandboxPanel — the governed ToolRPC pipeline is reachable', () => {
  it('posts tools:true and shows what the governed run reported', async () => {
    const fn = mockRoutes({
      '/sandbox/status': { backend: 'docker', tool_rpc: { available: true, tools: ['notes.add'] } },
      '/sandbox/execute': { stdout: 'ok', stderr: '', exit_code: 0, tool_calls: 3, timed_out: false },
    });
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByLabelText(/governed tools/)).toBeTruthy());

    fireEvent.click(screen.getByLabelText(/governed tools/));
    fireEvent.change(screen.getByPlaceholderText('print("hello from the sandbox")'), { target: { value: 'print(1)' } });
    fireEvent.click(screen.getByText('execute'));

    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/sandbox/execute') && c[1]?.method === 'POST');
      expect(JSON.parse(post[1].body)).toEqual({ code: 'print(1)', language: 'python', tools: true });
    });
    // the two keys only a governed run returns
    await waitFor(() => expect(screen.getByText('3 tool calls')).toBeTruthy());
    expect(screen.getByText('completed')).toBeTruthy();
  });

  it('does not offer the checkbox as usable when the server has no governed runtime', async () => {
    // /sandbox/status says so up front, so the control is disabled with the reason
    // rather than offering a click that is guaranteed to come back 503.
    mockRoutes({ '/sandbox/status': { backend: 'docker', tool_rpc: { available: false, tools: [] } } });
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByLabelText(/governed tools/).disabled).toBe(true));
    expect(screen.getByText(/governed tools unavailable on this server/)).toBeTruthy();
  });

  it('renders no governed row at all for an ordinary run', async () => {
    // An absent `tool_calls` is a run that never went through the pipeline. "0 tool calls"
    // would read as governed-and-idle, which is a different and untrue claim.
    mockRoutes({
      '/sandbox/status': { backend: 'docker', tool_rpc: { available: true, tools: [] } },
      '/sandbox/execute': { stdout: 'plain', stderr: '', exit_code: 0 },
    });
    render(<SandboxPanel />);
    fireEvent.change(screen.getByPlaceholderText('print("hello from the sandbox")'), { target: { value: 'print(1)' } });
    fireEvent.click(screen.getByText('execute'));
    await waitFor(() => expect(screen.getByText(/plain/)).toBeTruthy());
    // the whole row, not just its numbers: an empty "governed" row would still assert
    // that this run went through the pipeline, which is the claim being avoided.
    expect(screen.queryByText('governed')).toBeNull();
    expect(screen.queryByText(/tool calls/)).toBeNull();
  });

  it('warns before a shell+tools run rather than letting the 422 be a surprise', async () => {
    mockRoutes({ '/sandbox/status': { backend: 'docker', tool_rpc: { available: true, tools: [] } } });
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByLabelText(/governed tools/)).toBeTruthy());
    fireEvent.click(screen.getByLabelText(/governed tools/));
    fireEvent.change(screen.getByDisplayValue('python'), { target: { value: 'shell' } });
    expect(screen.getByText(/refused 422 — the pipeline is python-only/)).toBeTruthy();
  });

  it('says a 503 was NOT quietly run ungoverned', async () => {
    // The route refuses rather than falling back to execute_python, because a fallback
    // would run the same code without the governance the checkbox asked for. The panel
    // has to say that, or a refusal reads like a transient outage.
    mockRoutes(
      { '/sandbox/status': { backend: 'docker', tool_rpc: { available: true, tools: [] } },
        '/sandbox/execute': { error: 'tool-rpc unavailable' } },
      (url) => (url.includes('/sandbox/execute') ? 503 : 200),
    );
    render(<SandboxPanel />);
    await waitFor(() => expect(screen.getByLabelText(/governed tools/)).toBeTruthy());
    fireEvent.click(screen.getByLabelText(/governed tools/));
    fireEvent.change(screen.getByPlaceholderText('print("hello from the sandbox")'), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('execute'));
    await waitFor(() => expect(screen.getByText(/tool-rpc unavailable — NOT run ungoverned as a fallback/)).toBeTruthy());
  });
});

/* ── DRA-23 · the network headline ────────────────────────────────────────── */

describe('NetworkMonitorPanel — the headline accounts for model egress', () => {
  const snapshot = (over) => ({
    plugins: { 'llm:gemini': { total: 12, allowed: 12, blocked: 0, external: 12 } },
    external_egress_total: 12,
    model_egress_total: 12,
    local_only_violations: [],
    clean: true,
    ...over,
  });

  it('does not say "local-only ✓" above twelve model calls', async () => {
    // The exact regression: `clean` is derived from local_only_violations, and model
    // traffic can never be in that list — LLM backends have no manifest gate, so those
    // rows record what left and never a block. The old headline read local-only ✓ here.
    mockRoutes({ '/api/admin/network/calls': snapshot() });
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText(/12 model calls left the box/)).toBeTruthy());
    expect(screen.queryByText('local-only ✓')).toBeNull();
  });

  it('still says local-only when nothing left', async () => {
    mockRoutes({ '/api/admin/network/calls': snapshot({ plugins: {}, external_egress_total: 0, model_egress_total: 0 }) });
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('local-only ✓')).toBeTruthy());
  });

  it('a policy violation still outranks everything', async () => {
    mockRoutes({ '/api/admin/network/calls': snapshot({ local_only_violations: ['frigga'], clean: false }) });
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText('VIOLATION')).toBeTruthy());
  });

  it('an older backend with no model figure reads as unmeasured, never as zero', async () => {
    const older = snapshot();
    delete older.model_egress_total;
    mockRoutes({ '/api/admin/network/calls': older });
    render(<NetworkMonitorPanel />);
    await waitFor(() => expect(screen.getByText(/model egress unmeasured/)).toBeTruthy());
    expect(screen.getByText('model —')).toBeTruthy();
  });
});

/* ── DRA-52 · the server's own refusal reason ─────────────────────────────── */

describe('refusalReason — the backend already said why', () => {
  it('reads all three refusal dialects the backend actually speaks', () => {
    expect(refusalReason({ status: 422, body: { error: 'tool_rpc_pipeline_python_only' } })).toBe('tool_rpc_pipeline_python_only');
    expect(refusalReason({ status: 429, body: { ok: false, reason: 'concurrency_cap' } })).toBe('concurrency_cap');
    expect(refusalReason({ status: 400, body: { detail: 'prompt is empty' } })).toBe('prompt is empty');
  });

  it('never returns the request line as the reason', () => {
    // This is the whole finding: `err.message` is "POST /api/x -> 400", and printing it
    // as an explanation told an operator nothing while looking like it told them something.
    const err = Object.assign(new Error('POST /api/subagents/spawn -> 429'), {
      status: 429, body: { ok: false, reason: 'concurrency_cap' },
    });
    expect(refusalReason(err, 'spawn failed')).toBe('concurrency_cap');
    expect(refusalReason(err, 'spawn failed')).not.toMatch(/POST|->/);
  });

  it('falls back honestly when the body carries no reason', () => {
    expect(refusalReason({ status: 500, body: null }, 'rollback failed')).toBe('rollback failed');
    expect(refusalReason({ status: 500 })).toBe('500');
    expect(refusalReason({})).toBe('error');
    // an empty or whitespace-only `error` is not a reason
    expect(refusalReason({ status: 400, body: { error: '   ' } }, 'save failed')).toBe('save failed');
  });

  it('keeps a structured validation detail rather than dropping it', () => {
    const out = refusalReason({ status: 422, body: { detail: [{ loc: ['body', 'code'], msg: 'too long' }] } });
    expect(out).toMatch(/too long/);
  });
});

/* ── DRA-47 · the redactions tile ─────────────────────────────────────────── */

describe('the resilience tile label matches what is counted', () => {
  it('no longer attributes a mixed total to PII alone', () => {
    // guardrails.stats().redactions counts redaction EVENTS across every scanner —
    // secrets and PII together. "PII redactions" was a smaller number wearing a
    // different number's name.
    expect(modesSource).not.toMatch(/>PII redactions</);
    expect(modesSource).toMatch(/Redactions · secrets \+ PII/);
    // and the caveat the payload's own note carries is on the element, not just in prose
    expect(modesSource).toMatch(/resets on restart/);
  });
});

/* ── the WORLD button vs the mode rail ────────────────────────────────────── */

describe('the WORLD button does not sit on the mode rail', () => {
  it('reserves at least its own footprint at the bottom of the rail', () => {
    // jsdom performs no layout, so an overlap assertion between two fixed elements would
    // compare zero-sized rectangles and pass whatever the CSS said. The arithmetic below
    // is what actually frees the pixels: the reserved strip must cover the button's
    // height plus the inset above and below it.
    expect(RAIL_RESERVED_PX).toBeGreaterThanOrEqual(WORLD_BUTTON_HEIGHT + WORLD_BUTTON_INSET * 2);
  });

  it('applies that reservation to the rail itself, and pins the button to the same numbers', () => {
    // the reservation is a real rule against `.rail`, not a comment
    expect(worldSource).toMatch(/<style>\{`\.rail \{ padding-bottom: \$\{RAIL_RESERVED_PX\}px; \}`\}<\/style>/);
    // and the button's own geometry comes from the same constants the reservation uses,
    // so the two cannot drift apart in a later edit
    expect(worldSource).toMatch(/left: WORLD_BUTTON_INSET, bottom: WORLD_BUTTON_INSET/);
    expect(worldSource).toMatch(/height: WORLD_BUTTON_HEIGHT/);
    expect(worldSource).not.toMatch(/left: 16, bottom: 16/);
  });
});

/* ── the wall's decision provenance ───────────────────────────────────────── */

describe('the briefing wall stops claiming there is no decision feed', () => {
  it('maps a pending approval without inventing a word of it', () => {
    const card = decisionCard({ id: 7, agent: 'ultron', kind: 'comms.send', title: 'Send the LinkedIn draft', reversible: false });
    expect(card.body).toBe('Send the LinkedIn draft');       // the task's own title, verbatim
    expect(card.who).toBe('ULTRON');
    expect(card.kindLabel).toBe('Needs approval · irreversible');
    // ONE action, and it is the only thing pressing it does. An "Approve" button here
    // would dismiss the card and decide nothing, which is the worst lie this surface
    // could tell: the operator would believe they had approved something.
    expect(card.actions).toEqual([{ l: 'Dismiss' }]);
    expect(JSON.stringify(card)).not.toMatch(/Approve|Reject/);
  });

  it('falls back to the kind when a task carries no agent, rather than to a person', () => {
    const card = decisionCard({ id: 1, kind: 'file.write', title: 'Write notes.md', reversible: true });
    expect(card.who).toBe('FILE.WRITE');
    expect(card.kindLabel).toBe('Needs approval · reversible');
  });

  it('reads its evidence from sources.decisions, not from the array', () => {
    // The old line was `provDecisions = decisionEvidence ? 'seeded' : null` with the
    // comment "no live decision feed exists". The feed is admin-guarded, so a 401 must
    // leave the cell UNKNOWN — an empty array from a refusal rendering as "0 pending"
    // is an all-clear nobody measured.
    expect(wallSource).toMatch(/const decisionsLive = !!\(sources && sources\.decisions === true\)/);
    expect(wallSource).not.toMatch(/no live decision feed exists/);
    expect(wallSource).toMatch(/approvals feed/);
  });
});

/* ── the three registry agents the demo corpus never had ──────────────────── */

describe('the demo roster covers the whole registry', () => {
  const REGISTRY_ONLY = ['argus', 'hestia', 'howard'];

  it('gives argus, hestia and howard a roster row and a dossier', () => {
    for (const id of REGISTRY_ONLY) {
      const row = V2.AGENTS.find((a) => a.id === id);
      expect(row, `${id} is active in agents.yaml and must be in the demo roster`).toBeTruthy();
      expect(row.tier).toBeTruthy();
      expect(row.role).toBeTruthy();
      const dossier = V2.DOSSIER[id];
      expect(dossier, `${id} opened a blank dossier card`).toBeTruthy();
      expect(dossier.archetype).toBeTruthy();
      expect(dossier.soul).toBeTruthy();
    }
  });

  it('copies their registry facts rather than inventing them', () => {
    // Every field below is in agents/_system/agents.yaml. If one is edited here without
    // the registry agreeing, this is the test that notices.
    expect(V2.DOSSIER.argus.channel).toBe('web-dashboard');
    expect(V2.DOSSIER.argus.plugins).toEqual(['worldview', 'cloud-llm']);
    expect(V2.DOSSIER.hestia.policy).toBe('local');
    expect(V2.DOSSIER.hestia.plugins).toEqual(['homebridge', 'iot-control']);
    expect(V2.DOSSIER.howard.heartbeat).toBe('no');
    expect(V2.DOSSIER.howard.plugins).toEqual([]);
  });

  it('still leaves them to the neutral glyph', () => {
    // glyphFor's fallback is the designed answer for a registry agent with no
    // hand-drawn mark; adding seed glyphs here would quietly retire that decision.
    for (const id of REGISTRY_ONLY) {
      expect(V2.GLYPHS[id]).toBeUndefined();
      expect(V2.glyphFor(id)).toBe(V2.FALLBACK_GLYPH);
    }
  });

  it('edges them into the collaboration graph so they are not isolated nodes', () => {
    for (const id of REGISTRY_ONLY) {
      expect(V2.COLLAB.some((e) => e[0] === id || e[1] === id), `${id} has no collab edge`).toBe(true);
    }
  });
});
