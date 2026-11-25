/* All pages: the /v2/console site map (PHASE_B_PLAN.md §3.2).

   A link for every listed page of every area, grouped as the contents columns group them. It
   mounts no panel and asks nothing of the hub: it is a list of links, so it is safe to open
   anywhere. The notes beside Decisions, Payments and the Emergency stop come from `attention`
   when the caller has them (a live value only). */
import React, { useId } from 'react';
import { fmt, pick, type Lang } from '../frame/strings';
import { chordOf, displayChord, loadOverrides, type Overrides } from '../shortcuts';
import type { Attention } from '../signals/types';
import { AREAS, textOf } from './areas';
import { CONTENTS_STRINGS, contentsModel, pagesWord } from './contents-model';
import { PageLink } from './ContentsColumn';
import './contents.css';

export interface AllPagesProps {
  lang: Lang;
  navigate: (path: string) => void;
  attention?: Attention;
  overrides?: Overrides;
}

export function AllPages({ lang, navigate, attention, overrides }: AllPagesProps): React.JSX.Element {
  const s = pick(CONTENTS_STRINGS, lang);
  const uid = useId();
  const chord = displayChord(chordOf(overrides ?? loadOverrides(), 'session.palette'));
  const [before, after = ''] = fmt(s.allPagesNote, {}).split('{key}');
  return (
    <div className="n-allpages" data-frame="allpages">
      <p className="n-allpages-note">{before}<kbd className="n-kbd">{chord}</kbd>{after}</p>
      <div className="n-allpages-grid">
        {AREAS.map((area) => {
          const model = contentsModel(area, null);
          const headId = `${uid}-${area.id}`;
          return (
            <section key={area.id} className="n-allpages-area" data-area={area.id} aria-labelledby={headId}>
              <header className="n-allpages-head">
                <h2 id={headId} className="n-allpages-title">{textOf(area.label, lang)}</h2>
                <span className="n-contents-meta">{pagesWord(lang, model.total)}</span>
              </header>
              {model.groups.map((g) => {
                const items = [...g.primary, ...g.more].sort((a, b) => g.group.pages.indexOf(a.entry) - g.group.pages.indexOf(b.entry));
                const gid = `${headId}-${g.group.id}`;
                return (
                  <div key={g.group.id} className="n-allpages-group" data-group={g.group.id}>
                    {g.label && <div id={gid} className="n-toc-group">{textOf(g.label, lang)}</div>}
                    <ul aria-labelledby={g.label ? gid : headId} className="n-toc">
                      {items.map((item) => (
                        <li key={item.entry.key}>
                          <PageLink item={item} lang={lang} navigate={navigate} attention={attention} className="n-toc-link" />
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </section>
          );
        })}
      </div>
    </div>
  );
}
