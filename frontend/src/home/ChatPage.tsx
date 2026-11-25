/* The conversation page (PHASE_B_PLAN.md §2.1, §5.1):

     /v2/chat            Home › Conversation: an AreaPage of Home (its contents column on the
                         left) with the conversation register at full width
     floating (420×620)  the desktop window: its controls, the running head as marks (all eight
                         items; the approval mode read, not changed, and no page links in the
                         signals' popovers, since this window shows only the conversation), the
                         window's notices, the docket's one line ("⊛ N await your signature —
                         sign in the main window"; the window's own controls already carry "Open in
                         app"), then the conversation. No signing in the floating window in Phase B.

   The conversation register is TalkRegister (home/talk), the docket's line DocketLine
   (docket/Docket). App hands the page `talk` (TalkInput) and `turns`; the page sets the
   register's variant itself, so App never keeps a variant. */
import React from 'react';
import { DesktopControls } from '../desktop';
import { DocketLine } from '../docket/Docket';
import { AreaPage } from '../frame/AreaPage';
import { RunningHead } from '../frame/RunningHead';
import type { Lang } from '../frame/strings';
import type { RoutePage } from '../nav/routes';
import type { Attention, HubSnapshot, TabTurn } from '../signals/types';
import { TalkRegister } from './talk/TalkRegister';
import type { TalkInput } from './talk/types';
import './home.css';

type ChatPageCommon = {
  talk: TalkInput;
  turns: readonly TabTurn[];
  hub: HubSnapshot;
  lang: Lang;
  demo: boolean;
  navigate: (path: string) => void;
  /** A mid-turn question from this tab waits for the owner's answer (App's `question`). */
  awaitingAnswer?: boolean;
};

export type ChatPageProps = ChatPageCommon & (
  | { variant: 'chat'; page: RoutePage; attention: Attention; onFind: (filter?: 'panels') => void }
  /** `notices`: the window's own notices (safe mode, demo, failed actions), under the running head. */
  | { variant: 'floating'; notices?: React.ReactNode }
);

export function ChatPage(props: ChatPageProps) {
  const { talk, turns, hub, lang, demo, navigate, awaitingAnswer = false } = props;
  if (props.variant === 'floating') {
    return (
      <div className="n-chatpage n-chatpage--floating" data-chatpage="floating">
        <DesktopControls floating />
        <RunningHead hub={hub} lang={lang} demo={demo} variant="marks" links={false} />
        {props.notices}
        <DocketLine lang={lang} demo={demo} />
        <div className="n-chatpage__talk">
          <TalkRegister {...talk} variant="floating" turns={turns} awaitingAnswer={awaitingAnswer} />
        </div>
      </div>
    );
  }
  const { page, attention, onFind } = props;
  return (
    <AreaPage page={page} lang={lang} attention={attention} navigate={navigate} onFind={onFind}>
      <div className="n-chatpage n-chatpage__talk" data-chatpage="chat">
        <TalkRegister {...talk} variant="chat" turns={turns} awaitingAnswer={awaitingAnswer} />
      </div>
    </AreaPage>
  );
}
