/* ReplyFootnote: under a finished reply, where it was sent and what it called
   (PHASE_B_PLAN.md §5.3; gap-5 §7.1).

   Where it ran comes from E3's replyMarker() / replyMarkerWords() (signals/provenance.ts), the
   one derivation of the per-message marker: "Sent to …", never "Ran on …"; the least private of
   the reply's model pairs, plus "+N more", which opens the provenance modal (App's ProvModal,
   whose wording is kept); "No model call" only when the turn's usage basis is measured_zero;
   "Where it ran: not reported" without a receipt. A model id that names a cloud model carries
   its warning. What it called comes from the tool cards the stream reported (one per call) and
   from the hub's recorded tool accounting (TurnToolActivity, unchanged). */
import React from 'react';
import { Mark } from '../../frame/kit';
import type { MarkKind } from '../../frame/kit/marks';
import { plural } from '../../frame/strings';
import { replyMarker, replyMarkerWords } from '../../signals/provenance';
import type { ReplyMarkerKind } from '../../signals/types';
import type { ToolCard } from '../../turn-tools';
import { TurnToolActivity, type TurnOutcome } from '../../turn-outcome';
import { talkStrings } from './strings';
import { toolStateWord } from './WorkingReply';
import type { TalkMessage } from './types';

const WHERE_MARK: Partial<Record<ReplyMarkerKind, MarkKind>> = { localRunner: 'here', cloudName: 'attn', notReported: 'unknown' };
const TOOL_MARK: Record<ToolCard['state'], MarkKind> = { requested: 'idle', running: 'work', done: 'done', failed: 'problem', stopped: 'held' };

export interface ReplyFootnoteProps {
  message: TalkMessage;
  /** Opens the provenance modal with the reply's pairs (App's setProvModal). */
  onProv?: (prov: TalkMessage['prov']) => void;
  /** The turn's outcome, for the newest reply only (its usage basis says "no model call"). */
  outcome?: TurnOutcome | null;
  lang: string;
}

export function ReplyFootnote({ message, onProv, outcome, lang }: ReplyFootnoteProps) {
  const s = talkStrings(lang);
  const models = Array.isArray(message.prov?.models) ? message.prov!.models : [];
  const marker = replyMarker({ models, usageBasis: outcome?.usage_detail?.usage_basis ?? null });
  const words = replyMarkerWords(marker, lang);
  const mark = WHERE_MARK[marker.kind];
  const tools: readonly ToolCard[] = Array.isArray(message.tools) ? message.tools : [];
  return (
    <div className="n-footnote" data-footnote="" data-marker={marker.kind} role="group" aria-label={s.footnoteLabel}>
      <p className="n-footnote__line">
        <span className="n-footnote__where" title={s.whereTitle} data-basis={marker.basis}>
          {mark && <Mark kind={mark} size="sm" lang={lang} />}
          <span>{words.text}</span>
          {words.more && onProv && (
            <button type="button" className="n-link n-footnote__more" aria-label={plural(lang, s.allPairs, models.length)}
              onClick={() => onProv(message.prov)}>{words.more}</button>
          )}
        </span>
        {words.warning && (
          <span className="n-footnote__warn" title={words.warningWhy ?? undefined}>
            <Mark kind="attn" size="sm" lang={lang} /><span>{words.warning}</span>
          </span>
        )}
        {tools.length > 0 && (
          <span className="n-footnote__tools" data-footnote-tools="">
            <span>{plural(lang, s.toolCalls, tools.length)}</span>
            {tools.map((card) => (
              <span key={card.key} className="n-footnote__tool" data-state={card.state}>
                <Mark kind={TOOL_MARK[card.state]} size="sm" lang={lang} />
                <code>{card.tool}</code>
                <span>{toolStateWord(card.state, lang)}</span>
              </span>
            ))}
          </span>
        )}
      </p>
      <TurnToolActivity activity={message.toolActivity as TurnOutcome['tools']} lang={lang} />
    </div>
  );
}
