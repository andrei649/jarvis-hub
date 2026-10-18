/* The model status chip in the top bar: Local, Cloud or Unavailable, from GET /model.

   The posture is the shell's shared read (app/workspace.tsx: polled every 30 s, re-read at once
   after any failed answer, report or model test), so an outage shows up before someone asks a
   question and the chip agrees with the result on screen. The popover explains the state in
   plain words; the engine, the route and the model id are technical, so only admins see them.
   Admins also get a shortcut to the model settings. */
import React, { useCallback } from 'react';
import type { ModelPosture } from '../api/types';
import { useUser } from '../app/session';
import { useWorkspace } from '../app/workspace';
import { useI18n, type MessageKey } from '../i18n';
import { Link } from '../router';
import { Popover, Skeleton } from '../ui';

export type ModelState = 'local' | 'cloud' | 'unverified' | 'unavailable';

export function modelState(posture: ModelPosture): ModelState {
  if (!posture.available) return 'unavailable';
  if (posture.locality === 'cloud') return 'cloud';
  if (posture.locality === 'local') return 'local';
  return 'unverified';
}

const STATE_LABEL: Record<ModelState, MessageKey> = {
  local: 'model.state.local', cloud: 'model.state.cloud', unverified: 'model.state.unverified', unavailable: 'model.state.unavailable',
};

/** A translated sentence for a posture `reason` code; unknown codes fall back to a generic line. */
export function useModelReason(): (reason: string | null) => string {
  const { t, has } = useI18n();
  return useCallback((reason: string | null) => {
    const key = `model.reason.${reason ?? ''}`;
    return reason && has(key) ? t(key) : t('model.reason.generic');
  }, [t, has]);
}

/** Where the answers are produced, in words: the company's own server or an approved cloud provider. */
export function useWhereText(): (posture: Pick<ModelPosture, 'locality' | 'route'>) => string | null {
  const { t } = useI18n();
  return useCallback((posture) => {
    const where = posture.locality ?? (posture.route === 'local' ? 'local' : posture.route === 'cloud' ? 'cloud' : null);
    if (where === 'local') return t('model.where.local');
    if (where === 'cloud') return t('model.where.cloud');
    return null;
  }, [t]);
}

export function ModelDetails({ posture, technical = false }: { posture: ModelPosture; technical?: boolean }) {
  const { t } = useI18n();
  const reasonText = useModelReason();
  const whereText = useWhereText();
  const state = modelState(posture);
  const where = whereText(posture);
  return (
    <dl className="ws-dl">
      <dt>{t('model.field.status')}</dt>
      <dd><span className={`ws-model-dot ws-model-dot--${state}`} aria-hidden="true" /> {t(STATE_LABEL[state])}</dd>
      {where && <><dt>{t('model.field.where')}</dt><dd>{where}</dd></>}
      {technical && posture.model && <><dt>{t('model.field.model')}</dt><dd className="ws-mono">{posture.model}</dd></>}
      {technical && posture.backend && <><dt>{t('model.field.backend')}</dt><dd className="ws-mono">{posture.backend}</dd></>}
      <dt>{t('model.field.policy')}</dt>
      <dd>{t(posture.policy === 'allow_cloud' ? 'org.policy.allow_cloud' : 'org.policy.local_only')}</dd>
      {!posture.available && <><dt>{t('model.field.reason')}</dt><dd>{reasonText(posture.reason)}</dd></>}
      {state === 'unverified' && <><dt>{t('model.field.note')}</dt><dd>{t('model.unverifiedNote')}</dd></>}
    </dl>
  );
}

export function ModelChip() {
  const { t } = useI18n();
  const user = useUser();
  const { posture, postureFailed: failed, refreshPosture: load } = useWorkspace();

  if (!posture && !failed) return <Skeleton width={96} height={28} radius={999} />;
  const state: ModelState = posture ? modelState(posture) : 'unavailable';
  const label = posture ? t(STATE_LABEL[state]) : t('model.state.unknown');

  return (
    <Popover
      label={t('model.title')}
      onOpenChange={(open) => { if (open) void load(); }}
      trigger={(props) => (
        <button type="button" className={`ws-chip ws-chip--${state}`} {...props} aria-label={t('model.chipLabel', { state: label })}>
          <span className={`ws-model-dot ws-model-dot--${state}`} aria-hidden="true" />
          <span className="ws-chip__label">{label}</span>
        </button>
      )}
    >
      {() => (
        <div className="ws-popover__body">
          <p className="ws-popover__title">{t('model.title')}</p>
          {posture ? <ModelDetails posture={posture} technical={user.role === 'admin'} /> : <p className="ws-muted">{t('model.loadFailed')}</p>}
          {user.role === 'admin' && (
            <p className="ws-popover__foot"><Link to="/admin/organisation">{t('model.adminLink')}</Link></p>
          )}
        </div>
      )}
    </Popover>
  );
}
