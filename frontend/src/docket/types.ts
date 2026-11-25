/* Docket types (PHASE_B_PLAN.md §5.4).

   The docket reads the Decision Inbox's own feed — GET /autonomy/tasks?status=blocked&limit=200
   (admin), groups included — and decides through api/decisions.ts only. These are the shapes
   the docket model (docket/model.ts) produces and the other modules read: AreaNav and Glance
   read the summary, the conversation's approval slip reads an entry's title (docket/links.ts).

   Honesty: titles are the hub's plain text, verbatim (never markup); a kind becomes words only
   through the fixed map in docket/kinds.ts; every optional row exists only when the hub sent its
   field, so the optional fields here stay optional and null means "not sent". Facts the hub
   words in English (approval_mode, asked_under, delegated_by) arrive here as facts; the docket
   words them from its own {en, ro} tables. */
import type { TierKey } from '../frame/kit/marks';

/** One blocked task as the feed sends it (routers/autonomy.py autonomy_list: the task, its
 *  approval and consent projections, and the mode projection). Only `id` is certain; read the
 *  rest defensively. */
export interface DocketTask {
  readonly id: number;
  readonly title?: string;
  readonly kind?: string;
  readonly agent?: string;
  readonly risk_tier?: number;
  readonly tier_name?: string;
  readonly created_at?: string;
  readonly approval_deadline_at?: string;
  /** H484: `{effective, source, global}`, the mode in force now (see DocketWhy). */
  readonly approval_mode?: unknown;
  /** H484: `{mode, source, global, by_mode}`, the mode recorded when the task was held. */
  readonly asked_under?: unknown;
  /** H400: a sub-agent asked, on behalf of an agent's turn. `label` is the hub's English line
   *  and holds model-written goal text: the docket does not show it (see DocketEntry). */
  readonly delegated_by?: {
    readonly spawn_id?: unknown;
    readonly parent?: unknown;
    readonly turn?: unknown;
    readonly label?: unknown;
  } | null;
  readonly pushed?: boolean | number;
  readonly reversible?: boolean;
  readonly payload?: Readonly<Record<string, unknown>>;
  readonly rollback?: { readonly description?: string; readonly limitations?: string } | null;
  readonly judge?: {
    readonly advisory?: boolean;
    readonly score?: number;
    readonly decision?: string;
    readonly rationale?: string;
    readonly judge?: { readonly provider?: string; readonly model?: string; readonly local?: boolean };
  } | null;
  readonly judge_pending?: boolean;
  /** A terminal consent offer (see DocketConsentOffer). */
  readonly consent_offer?: unknown;
  readonly [field: string]: unknown;
}

/** A hub group of identical requests, exactly as the feed's top-level `groups[]` sends it
 *  (queue.py `_group_projection_locked`). Task rows do not carry the snapshot: it comes only
 *  from here. Valid for the docket when, as in the inbox, there are at least two members, `count`
 *  equals them, none repeats, the leader is among them and every member is in `tasks` — and,
 *  because Reject group cannot be sent without it, `snapshot` is a 32-character string. A group
 *  that fails this is not a hub group on the docket (its members are drawn as single requests
 *  or an identical collapse). */
export interface DocketGroup {
  readonly id: string;
  readonly leader_id: number;
  /** In the hub's order (ascending task id, the leader first). Sent back unchanged. */
  readonly member_ids: readonly number[];
  readonly count: number;
  /** The membership snapshot. Reject group (POST /autonomy/tasks/groups/{id}/reject) sends
   *  `{snapshot, member_ids, reason?}` exactly as received; the hub refuses a changed snapshot or
   *  membership (409 "approval group changed"), and the docket then re-reads the feed. */
  readonly snapshot: string;
}

/** The friction a tier takes (confirm.tsx confirmStyle): tier 0 one click, tier 1 two steps,
 *  tiers 2–3 and any unknown tier a typed phrase. */
export type Friction = 'click' | 'two-step' | 'typed';

/** What the owner can do with an entry. No verb is ever bound to a key.
 *  sign                the tier's friction, then POST …/decision {action:'accept'}
 *  preview             read only: GET /api/autonomy/tasks/{id}/preview
 *  edit                edit the payload, then sign at the same friction ({action:'edit', payload})
 *  defer               one click ({action:'defer'})
 *  reject              one click, with an optional reason ({action:'reject', reason})
 *  rejectGroup         a hub group: two steps, then api/decisions.ts rejectGroup(entry.group, reason)
 *  rejectAllIdentical  a display collapse: two steps, N sequential rejects, partial results reported
 *  openInDecisions     special kinds: <a href={decisionsHref(id)}> + openDecisionsCard(id)
 *                      (docket/links.ts; never navigateHud with that href) */
export type Verb = 'sign' | 'preview' | 'edit' | 'defer' | 'reject' | 'rejectGroup' | 'rejectAllIdentical' | 'openInDecisions';

/** The approval modes the hub knows (agents/core/autonomy/mode.py). */
export type ApprovalMode = 'auto' | 'ask' | 'off';

/** The Why row's facts (H484), read fail-closed as loaders.ts approvalModeNote() reads them:
 *  only the three exact mode words survive, anything else is null and the row says nothing about
 *  the mode. The docket words them from its own {en, ro} table; approvalModeNote() is
 *  English-only and stays the inbox's. Exists only when `approval_mode` or `asked_under` was sent. */
export interface DocketWhy {
  /** `approval_mode.effective`: the mode in force now for the task's agent. */
  readonly modeNow: ApprovalMode | null;
  /** `approval_mode.source`: the agent's own override, or the global mode. */
  readonly modeNowSource: 'agent' | 'global' | null;
  /** `asked_under`: the mode recorded when the task was held; null when not recorded. */
  readonly askedUnder: {
    readonly mode: ApprovalMode;
    readonly source: 'agent' | 'global';
    /** `by_mode`: the mode itself is why it waits ("Held because the approval mode was ask…");
     *  false: its risk tier, a money cap or a safety check is. */
    readonly byMode: boolean;
  } | null;
}

/** A terminal consent offer (routers/autonomy.py `_consent_projection`): a special kind, decided
 *  in Decisions. Exists only when the hub sent a well-formed offer. */
export interface DocketConsentOffer {
  /** 64 hex characters; Decisions sends it back with the choice. */
  readonly revision: string;
  /** The requests the offer covers. */
  readonly count: number;
  readonly choices: readonly ('session' | 'always' | 'deny')[];
  /** The hub's own descriptions (reviewed text), verbatim. */
  readonly categories: readonly { readonly description: string; readonly permanent: boolean }[];
}

/** One line of the docket. */
export interface DocketEntry {
  /** Unique within a model: 'task:<id>', 'group:<group.id>' or 'same:<leaderId>'. */
  readonly key: string;
  /** single: one request · group: a hub group · identical: a display collapse of identical
   *  requests (same kind, title, agent and stable payload hash), shown as "×N identical". */
  readonly kind: 'single' | 'group' | 'identical';
  /** The request this entry signs: groups and collapses are signed one request at a time. */
  readonly taskId: number;
  /** The hub group, exactly as the feed sent it: set for kind 'group', null otherwise. Reject
   *  group uses it (id, snapshot, member_ids); nothing else may stand in for it. */
  readonly group: DocketGroup | null;
  /** Every request the entry stands for (the leader first). */
  readonly memberIds: readonly number[];
  /** The hub's title, verbatim, as plain text. */
  readonly title: string;
  /** The hub's kind word, unchanged (for the detail); its words come from docket/kinds.ts. */
  readonly nativeKind: string | null;
  readonly tier: TierKey;
  readonly friction: Friction;
  /** The phrase a typed signature needs (tiers 2–3; docket/phrases.ts); null otherwise. */
  readonly phrase: string | null;
  readonly agent: string | null;
  /** Epoch ms, when the hub sent them. */
  readonly createdAt: number | null;
  readonly deadlineAt: number | null;
  /** The verbs this entry offers, in order. */
  readonly verbs: readonly Verb[];
  /** A kind that opens in Decisions instead of being signed here (image proposal, consent
   *  offer, retention, voice command, guardian verdict). */
  readonly special: boolean;
  /** Which special kind (docket/special.ts), when `special`. */
  readonly specialKind?: 'image' | 'consent' | 'retention' | 'voice' | 'guardian' | null;
  // Optional rows — present only when the hub sent the field.
  /** The Why row (approval_mode / asked_under). */
  readonly why?: DocketWhy | null;
  /** "asked by a sub-agent of <parent>" (delegated_by.parent; spawnId for the detail). */
  readonly delegatedBy?: { readonly parent: string; readonly spawnId: string | null } | null;
  readonly pushed?: boolean | null;
  readonly rollback?: { readonly description: string; readonly limitations: string | null } | null;
  readonly tainted?: boolean;
  /** The judge's opinion. `advisory` false is a guardian's terminal verdict (`verdict`: the
   *  hub's word, 'deny' or 'escalate'); `flagged` and `truncated` are the judge's own caveats. */
  readonly opinion?: {
    readonly score: number | null; readonly provider: string | null; readonly model: string | null; readonly local: boolean | null;
    readonly advisory?: boolean; readonly verdict?: 'deny' | 'escalate' | null; readonly flagged?: boolean; readonly truncated?: boolean;
  } | null;
  readonly consentOffer?: DocketConsentOffer | null;
  /** What each member acts on (payload service / target / url / to / recipient / path / file /
   *  channel), aligned with `memberIds`; null where the member names none. Groups and
   *  collapses only. */
  readonly memberTargets?: readonly (string | null)[];
  /** The raw task, for the preview and the payload editor. */
  readonly task: DocketTask;
}

/** GET /api/autonomy/tasks/{id}/preview (agents/core/autonomy/dry_run.py), read defensively.
 *  The preview's own reversibility verdict and its English summary are not kept: the entry
 *  shows only the tier's verdict (PHASE_B_PLAN.md §7 B7). */
export interface DocketPreview {
  /** The payload's target (target, url, to or recipient), when it named one. */
  readonly target: string | null;
  /** The effects the dry run reports, in its order: a field name and its value as text. After
   *  B1 these include `cmd` and `service`. */
  readonly effects: readonly { readonly field: string; readonly value: string }[];
  /** `would_execute`: true when submitting it would run without approval. */
  readonly wouldExecute: boolean | null;
  /** A channel reply's pending question (`prompt`): its text and choices, or unavailable. */
  readonly prompt: { readonly available: true; readonly text: string; readonly choices: readonly string[] }
    | { readonly available: false } | null;
}

/** The counts the masthead, Glance and the docket head read. */
export interface DocketSummary {
  /** Docket lines (a group or a collapse is one entry). */
  readonly entries: number;
  /** Requests behind them. */
  readonly requests: number;
  /** The friction mix: "a typed · b two-step · c one click" — the entries signed here, by how —
   *  and `inDecisions`, the special kinds, which are not signed here but open in Decisions
   *  (optional in the type so a reader's fixtures may leave it out; the model always sets it). */
  readonly friction: { readonly typed: number; readonly twoStep: number; readonly click: number; readonly inDecisions?: number };
}

/** The docket as drawn: entries in order (tier descending, then the soonest deadline, then the
 *  oldest), the summary, and the things waiting elsewhere (counts only when their feeds are live).
 *  Hub groups are reachable through their entries (`entry.group`). */
export interface DocketModel {
  readonly entries: readonly DocketEntry[];
  readonly summary: DocketSummary;
  readonly elsewhere: { readonly payments: number | null; readonly skillChanges: number | null };
}

/** The feed the docket reads (the Decision Inbox's own). */
export const DOCKET_FEED_PATH = '/autonomy/tasks?status=blocked&limit=200';
