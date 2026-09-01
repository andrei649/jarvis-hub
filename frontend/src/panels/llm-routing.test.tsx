// @ts-nocheck
/* LLM ROUTING panel — POST /api/llm/moe/route (admin). fetch is mocked, like
   src/test/model-info-panel.test.tsx.

   The two cases that carry the honesty burden:
   · thinking:false has TWO causes (model outside the MoE registry vs. a simple prompt) and
     they must render as two DIFFERENT lines, never one merged sentence;
   · apiPost throws on 4xx, so a pydantic 422 array and the admin guard's 401 string must
     each reach the screen VERBATIM — and never as a success or a default "/no_think". */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { LlmRoutingPanel } from './llm-routing';

function mockFetch(res) {
  const fn = vi.fn().mockResolvedValue({
    ok: (res.status || 200) < 400,
    status: res.status || 200,
    json: async () => res.body,
  });
  global.fetch = fn;
  return fn;
}

function typeAndPreview(prompt, model) {
  fireEvent.change(screen.getByPlaceholderText(/prompt to route/), { target: { value: prompt } });
  if (model !== undefined) {
    fireEvent.change(screen.getByPlaceholderText('gpt-oss-20b'), { target: { value: model } });
  }
  fireEvent.click(screen.getByText('PREVIEW ROUTE'));
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('LlmRoutingPanel — the MoE routing decision is reachable and reads its own answer', () => {
  it('POSTs /api/llm/moe/route and renders the thinking decision from the payload', async () => {
    const fn = mockFetch({
      status: 200,
      body: { model: 'gpt-oss-20b', thinking: true, max_tokens: 8192, directive: '/think', collapses_tiers: true },
    });
    render(<LlmRoutingPanel />);
    typeAndPreview('explain why the deep tier was chosen');

    await waitFor(() => expect(screen.getByText('/think')).toBeTruthy());
    const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/llm/moe/route'));
    expect(call).toBeTruthy();
    expect(String(call[1].method).toUpperCase()).toBe('POST');
    expect(JSON.parse(call[1].body)).toEqual({
      prompt: 'explain why the deep tier was chosen',
      model: 'gpt-oss-20b',
    });
    expect(screen.getByText('max_tokens: 8192')).toBeTruthy();
    expect(screen.getByText('thinking: true')).toBeTruthy();
    expect(screen.getByText(/thinking mode on for this prompt/)).toBeTruthy();
  });

  it('says an unsupported model FORCED /no_think — not that the prompt was simple', async () => {
    mockFetch({
      status: 200,
      body: { model: 'llama3.1:8b', thinking: false, max_tokens: 1024, directive: '/no_think', collapses_tiers: false },
    });
    render(<LlmRoutingPanel />);
    typeAndPreview('explain why the deep tier was chosen', 'llama3.1:8b');

    await waitFor(() => expect(screen.getByText(/has no thinking mode for/)).toBeTruthy());
    expect(screen.getByText(/forced to \/no_think whatever the prompt says/)).toBeTruthy();
    // The other cause must NOT be on screen: the model was never eligible.
    expect(screen.queryByText(/judged THIS prompt simple/)).toBeNull();
  });

  it('renders a pydantic 422 detail array verbatim and shows no decision at all', async () => {
    mockFetch({
      status: 422,
      body: { detail: [{ loc: ['body', 'prompt'], msg: 'String should have at most 8000 characters', type: 'string_too_long' }] },
    });
    render(<LlmRoutingPanel />);
    typeAndPreview('x'.repeat(20));

    await waitFor(() => expect(screen.getByText('body.prompt: String should have at most 8000 characters')).toBeTruthy());
    expect(screen.getByText(/refused · HTTP 422/)).toBeTruthy();
    // A refused request has no decision — nothing may default to /no_think or 1024.
    expect(screen.queryByText(/^max_tokens:/)).toBeNull();
    expect(screen.queryByText('/no_think')).toBeNull();
  });

  it("renders the admin guard's 401 detail string verbatim", async () => {
    // A user token is present so the client's 401 retry path does not reach window.prompt.
    try { localStorage.setItem('hud.user_token', 'u-tok'); } catch { /* ignore */ }
    mockFetch({ status: 401, body: { detail: 'admin token required' } });
    render(<LlmRoutingPanel />);
    typeAndPreview('explain the routing decision');

    await waitFor(() => expect(screen.getByText('admin token required')).toBeTruthy());
    expect(screen.getByText(/refused · HTTP 401/)).toBeTruthy();
    expect(screen.queryByText(/thinking mode on for this prompt/)).toBeNull();
  });
});
