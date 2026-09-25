/* H318 (review-H318b M-2) — the skill changes the agent proposed, in the Decision Inbox.

   `skill_propose` (and the background review, and /refine) record a change to a skill's
   SKILL.md as a pending proposal with one approval card bound to it. The owner decides
   it here, seeing the whole change: GET /api/skills/proposals (admin) builds each diff
   from the proposal ledger against the live SKILL.md, never from the card's own text, so
   a card cannot show one change and apply another. Nothing is cut.

   Beside the diff: whether the skill changed on disk since the proposal (approving then
   applies nothing), and what the change does beyond its text (a rename, a bundled skill
   that cannot be changed here). Approve and reject decide the proposal's own card
   (POST /api/actions/{card}/decide); the answer says what happened to the skill — applied
   and shown, applied but sandboxed, refused and why — instead of a bare "approved". */
import React, { useState } from 'react';
import { Row, Tag, actA, arr, mono, refusalReason } from '../panel-kit';

export const SKILL_CHANGES_PATH = '/api/skills/proposals';
export const SKILL_CHANGES_SHOWN = 5;

type Proposal = {
  id?: string; skill?: string; origin?: string; card?: string | null; diff?: string;
  drifted?: boolean; flags?: string[];
};

/** Who proposed it, in words: the agent's own tool, the background review or /refine. */
export function originLabel(origin: unknown): string {
  const text = String(origin || '');
  if (text.startsWith('agent:')) return `agent ${text.slice(6) || '?'}`;
  if (text === 'refine') return '/refine';
  if (text === 'background_review') return 'background review';
  return text || 'unknown';
}

/** A change the hub will refuse whatever the decision (a bundled skill, a rename): it
    offers reject only (review-H318c n-7). */
export function refusedByHub(p: { flags?: string[] }): boolean {
  return (p.flags || []).some((f) => /bundled skill|renames the skill/.test(String(f)));
}

/** What a decision did, from the decide route's answer, for one proposal. */
export function decisionOutcome(reply: any, proposalId: string, approved: boolean): string {
  const action = reply && reply.action;
  if (action && typeof action.note === 'string' && action.note) return action.note;
  if (!approved) return 'rejected · the skill is unchanged';
  const outcomes = arr(action && action.applied, 'outcomes');
  const mine = outcomes.find((o: any) => o && o.proposal_id === proposalId);
  if (!mine) return 'approved · not applied yet';
  if (mine.ok) return `applied · the skill is ${mine.state || 'updated'}`;
  const why: Record<string, string> = {
    drifted_since_proposal: 'the skill changed since the proposal',
    bundled_skill: 'a bundled skill cannot be changed here',
    renames_skill: 'the change renames the skill',
    write_failed: 'the file could not be written',
    skill_missing: 'the skill is gone',
    changed_during_apply: 'the skill\'s files changed while it was applied: nothing was kept',
    standing_not_renewed: 'its signature or approval could not be renewed: nothing was kept',
    signing_key_missing: 'its signing key is not configured: it waits until the key is back',
    rollback_failed: 'its signature or approval could not be renewed and the old text could not be put back: the new text stays, the old one is in the backup',
    signature_not_restored: 'its signature or approval could not be renewed: the old text is back, but not its old signature, so the skill stays untrusted until it is signed again',
    unreadable_skill: 'the skill cannot be read',
    unreadable_signature: 'its signature could not be read just now: it is tried again at the next pass',
    apply_error: 'the change could not be applied',
  };
  return `not applied · ${why[mine.reason] || mine.reason || 'refused'}`;
}

function ChangeDiff({ text }: { text: string }) {
  const color = (l: string) => l.startsWith('@@') ? 'var(--accent-light)'
    : (l.startsWith('+') && !l.startsWith('+++')) ? 'var(--green)'
    : (l.startsWith('-') && !l.startsWith('---')) ? 'var(--red)' : 'var(--ink-3)';
  return <pre data-testid="skill-change-diff" style={{ ...mono, fontSize: 10.5, lineHeight: 1.45, whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere', maxHeight: 320, overflow: 'auto', margin: '6px 0 0', padding: 8,
    background: 'var(--surface)', border: '1px solid var(--panel-line)', borderRadius: 4 }}>
    {text.split('\n').map((l, i) => <div key={i} style={{ color: color(l) }}>{l || ' '}</div>)}
  </pre>;
}

export function SkillChangesInbox({ reply, error, onDecided }:
  { reply: any; error?: string | null; onDecided?: () => void }) {
  const [outcome, setOutcome] = useState<Record<string, string>>({});
  if (error) {
    return <div style={{ ...mono, fontSize: 10, color: 'var(--amber)', marginTop: 8 }}>
      skill changes could not be read · {error}
    </div>;
  }
  const rows: Proposal[] = arr(reply, 'proposals');
  if (!rows.length) return null;
  // The hub sends at most a page of proposals and counts the rest (review-H318c n-2).
  const total = rows.length + (Number(reply && reply.more) || 0);
  const decide = (p: Proposal, approved: boolean) => {
    const id = String(p.id || '');
    setOutcome((o) => ({ ...o, [id]: approved ? 'applying…' : 'rejecting…' }));
    actA(`/api/actions/${encodeURIComponent(String(p.card))}/decide`, { approved },
      (r: any) => { setOutcome((o) => ({ ...o, [id]: decisionOutcome(r, id, approved) })); if (onDecided) onDecided(); },
      (err: any) => setOutcome((o) => ({ ...o, [id]: 'refused · ' + refusalReason(err) })));
  };
  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', letterSpacing: 1 }}>
        SKILL CHANGES · {total} awaiting you
      </div>
      {rows.slice(0, SKILL_CHANGES_SHOWN).map((p, i) => (
        <div key={p.id || i} data-testid="skill-change">
          <Row>
            <span style={{ ...mono, color: 'var(--ink-2)' }}>change to skill '{p.skill}'</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              <Tag>{originLabel(p.origin)}</Tag>
              {(p.flags || []).map((f) => <Tag key={f} c="var(--red)">{f}</Tag>)}
              {p.drifted && <Tag c="var(--amber)">the skill changed since · approving applies nothing</Tag>}
              <button className="tool-btn" title={refusedByHub(p) ? 'the hub will refuse this change: reject it'
                : 'approve skill change'} disabled={!p.card || refusedByHub(p)}
                onClick={() => decide(p, true)}>✓</button>
              <button className="tool-btn" title="reject skill change" disabled={!p.card}
                onClick={() => decide(p, false)}>✕</button>
            </span>
          </Row>
          {!p.card && <div style={{ ...mono, fontSize: 10, color: 'var(--amber)' }}>
            no approval card could be queued for it: reload to try again
          </div>}
          <ChangeDiff text={String(p.diff || '')} />
          {outcome[String(p.id || '')] && <div role="status" style={{ ...mono, fontSize: 10, marginTop: 4 }}>
            {outcome[String(p.id || '')]}
          </div>}
        </div>
      ))}
      {total > SKILL_CHANGES_SHOWN && <div style={{ ...mono, fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>
        {total - Math.min(rows.length, SKILL_CHANGES_SHOWN)} more after these are decided
      </div>}
    </div>
  );
}
