/* H378 — a model choice the hub's selection guards ask about.

   Every surface that picks a model (the Settings panel, a job's model pin) sends the choice
   as it is; the hub runs its guards before storing it (agents/core/llm/selection_guards.py)
   and answers 409 `selection_guard` with what it asks: a model whose output costs at least
   the owner's line needs `confirm_expensive`, a model or route whose vendor may train on the
   prompts needs `acknowledge_training` (written to the audit log as the owner's consent).
   Here the answer is shown — the prices, the vendor's policy — and the owner types the
   model's name to choose it anyway; the choice is then sent again with the flags. Cancel
   keeps the edit unsaved. Nothing here decides: only the hub stores a choice. */
import React, { useState } from 'react';
import { ConfirmAction, RISK_TIER } from './confirm';
import { mono } from './panel-kit';

export type GuardFinding = { guard: string; needs: string; setting: string; provider: string; model: string; message: string; detail?: any };
export type GuardRefusal = { needs: string[]; guards: GuardFinding[] };
export type GuardFlags = { confirm_expensive?: true; acknowledge_training?: true };

/** The hub's selection-guard refusal carried by a failed request, or null. */
export function guardRefusal(err: any): GuardRefusal | null {
  const body = err && err.body;
  if (!err || err.status !== 409 || !body || body.error !== 'selection_guard' || !Array.isArray(body.guards)) return null;
  return { needs: Array.isArray(body.needs) ? body.needs : [], guards: body.guards };
}

/** Every flag the findings ask for: the hub needs them all on the resend. */
export function guardFlags(refusal: GuardRefusal): GuardFlags {
  const flags: GuardFlags = {};
  for (const g of refusal.guards) {
    if (g.needs === 'confirm_expensive') flags.confirm_expensive = true;
    if (g.needs === 'acknowledge_training') flags.acknowledge_training = true;
  }
  return flags;
}

type Resend = (flags: GuardFlags) => void | Promise<unknown>;

export function SelectionGuardConfirm({ refusal, onConfirm, onCancel }: {
  refusal: GuardRefusal; onConfirm: Resend; onCancel: () => void;
}) {
  const cost = refusal.guards.some((g) => g.guard === 'cost');
  const training = refusal.guards.some((g) => g.needs === 'acknowledge_training');
  const phrase = refusal.guards.find((g) => g.model)?.model || 'allow';
  return (
    <div role="alertdialog" aria-label="confirm the model choice" style={{ marginTop: 8, padding: 8, border: '1px solid var(--amber)', borderRadius: 4, background: 'var(--surface)' }}>
      <div style={{ ...mono, fontSize: 10.5, color: 'var(--amber)', marginBottom: 4 }}>this model choice needs your say-so</div>
      <ul style={{ margin: '0 0 6px 16px', padding: 0, fontSize: 11 }}>
        {refusal.guards.map((g, i) => <li key={i}>{g.guard === 'cost' ? 'cost' : 'data policy'} · {g.message}</li>)}
      </ul>
      {training && <div style={{ fontSize: 10.5, color: 'var(--ink-2)', marginBottom: 6 }}>Your acknowledgement is written to the audit log.</div>}
      <ConfirmAction tier={cost ? RISK_TIER.IRREVERSIBLE_OR_MONEY : RISK_TIER.EXTERNAL} armed onCancel={onCancel} phrase={phrase}
        label="choose it anyway" armedLabel="choose it anyway" block
        onConfirm={() => onConfirm(guardFlags(refusal))} />
    </div>
  );
}

/** A request that may meet the selection guards: `catchGuard(retry, fallback)` wraps an error
 *  handler — a guard refusal opens the confirmation (`view`), whose confirm calls `retry`
 *  with the flags; any other error goes to `fallback`. */
export function useSelectionGuard() {
  const [pending, setPending] = useState<{ refusal: GuardRefusal; retry: Resend } | null>(null);
  const catchGuard = (retry: Resend, fallback: (err: any) => void) => (err: any) => {
    const refusal = guardRefusal(err);
    if (refusal) setPending({ refusal, retry });
    else fallback(err);
  };
  const view = pending
    ? <SelectionGuardConfirm refusal={pending.refusal} onCancel={() => setPending(null)}
        onConfirm={(flags) => { const { retry } = pending; setPending(null); return retry(flags); }} />
    : null;
  return { catchGuard, view, cancel: () => setPending(null) };
}
