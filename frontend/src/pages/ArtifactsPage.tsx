/* Saved replies (/v2/artifacts): the Artifacts panel as a page of its own (PHASE_B_PLAN.md §6).

   It wraps ArtifactsPanel unchanged. "Discuss in chat" stages the project through App's handler
   and then goes to the conversation (/v2/cockpit), where the composer receives it. With no
   composer mounted, `onInspectBlend` returns false and the panel shows its own message. In demo
   there are no live saved replies, so the page says so instead of reading them. */
import React from 'react';
import { ArtifactsPanel } from '../artifacts';
import { SourceLabel } from '../frame/kit';
import { defineStrings, pick, type Lang } from '../frame/strings';
import { navigateHud } from '../hud-routing';
import type { WorkshopRef } from '../workshop-projects';
import './pages.css';

export const ARTIFACTS_STRINGS = defineStrings({
  en: { demoNote: 'Demo sample: saved replies are not read in demo mode.' },
  ro: { demoNote: 'Mostră demo: răspunsurile salvate nu sunt citite în modul demo.' },
});

export interface ArtifactsPageProps {
  lang: Lang | string;
  demo: boolean;
  refreshKey: number;
  onInspectBlend: (file: File) => boolean;
  onDiscussProject: (project: WorkshopRef) => void;
}

export function ArtifactsPage({ lang, demo, refreshKey, onInspectBlend, onDiscussProject }: ArtifactsPageProps) {
  const s = pick(ARTIFACTS_STRINGS, lang);
  if (demo) {
    return (
      <div className="n-artifacts" data-page="artifacts" data-demo="true">
        <p className="n-pgnote" data-demo-note=""><SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} /> {s.demoNote}</p>
      </div>
    );
  }
  return (
    <div className="n-artifacts" data-page="artifacts">
      <ArtifactsPanel refreshKey={refreshKey} lang={lang as string} exportAllowed={true} onInspectBlend={onInspectBlend}
        onDiscussProject={(project) => { onDiscussProject(project); navigateHud('/v2/cockpit'); }} />
    </div>
  );
}
