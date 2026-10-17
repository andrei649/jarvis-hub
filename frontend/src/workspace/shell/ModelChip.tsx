/* The model status chip in the top bar: Local, Cloud or Unavailable, from GET /model.

   It polls once a minute so an outage shows up before someone asks a question, and the popover
   explains the state in plain words (which model, which route, why it is unavailable). Admins
   get a shortcut to the model settings. */
import React, { useCallback, useState } from 'react';
import { getModelPosture } from '../api/account';
import type { ModelPosture } from '../api/types';
import { usePolling } from '../app/hooks';
import { useUser } from '../app/session';
import { useI18n, type MessageKey } from '../i18n';
import { Link } from '../router';
import { Popover, Skeleton } from '../ui';

const POLL_MS = 60_000;

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

export function ModelDetails({ posture }: { posture: ModelPosture }) {
  const { t } = useI18n();
  const reasonText = useModelReason();
  const state = modelState(posture);
  return (
    <dl className="ws-dl">
      <dt>{t('model.field.status')}</dt>
      <dd><span className={`ws-model-dot ws-model-dot--${state}`} aria-hidden="true" /> {t(STATE_LABEL[state])}</dd>
      {posture.model && <><dt>{t('model.field.model')}</dt><dd className="ws-mono">{posture.model}</dd></>}
      {posture.backend && <><dt>{t('model.field.backend')}</dt><dd className="ws-mono">{posture.backend}</dd></>}
      {posture.route && <><dt>{t('model.field.route')}</dt><dd className="ws-mono">{posture.route}</dd></>}
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
  const [posture, setPosture] = useState<ModelPosture | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setPosture(await getModelPosture());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);
  usePolling(load, POLL_MS);

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
          {posture ? <ModelDetails posture={posture} /> : <p className="ws-muted">{t('model.loadFailed')}</p>}
          {user.role === 'admin' && (
            <p className="ws-popover__foot"><Link to="/admin/organisation">{t('model.adminLink')}</Link></p>
          )}
        </div>
      )}
    </Popover>
  );
}
