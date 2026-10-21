/* "Primii pași": what a pilot needs before colleagues can rely on it, for the admin who just set
   it up (UX-07). Five steps, each checked from real data — email configured, a department
   besides General, a colleague invited, a ready document, a model test that answered — each
   with a link to where it is done. The card sits at the top of Admin → Users (where setup
   lands), disappears once every step is done, and can be hidden earlier (per admin, in this
   browser). */
import React, { useState } from 'react';
import { listAudit, smtpConfigured } from '../../api/admin';
import type { AdminDepartment, AdminUser, SmtpSettings } from '../../api/types';
import { useAsync } from '../../app/hooks';
import { useUser } from '../../app/session';
import { readPref, writePref } from '../../app/storage';
import { useI18n, type MessageKey } from '../../i18n';
import { Link } from '../../router';
import { Button, Card, Icon } from '../../ui';

interface Step { id: string; label: MessageKey; hint: MessageKey; to: string; done: boolean }

export interface GettingStartedProps {
  users: AdminUser[] | null;
  departments: AdminDepartment[] | null;
  smtp: SmtpSettings | null;
  /** The invite step opens the invite dialog of the page it sits on. */
  onInvite?: () => void;
}

export function GettingStarted({ users, departments, smtp, onInvite }: GettingStartedProps) {
  const { t, tn } = useI18n();
  const me = useUser();
  const prefKey = `onboarding.hidden.${me.id}`;
  const [hidden, setHidden] = useState(() => readPref(prefKey) === '1');
  // The newest model test in the audit trail says whether the model has answered once.
  const lastTest = useAsync(() => listAudit({ action: 'model.tested', limit: 1 }), []);
  if (hidden || !users || !departments || !smtp || lastTest.loading) return null;

  const active = departments.filter((d) => !d.archived);
  const steps: Step[] = [
    { id: 'email', label: 'onboarding.email', hint: 'onboarding.email.hint', to: '/admin/email', done: smtpConfigured(smtp) },
    { id: 'departments', label: 'onboarding.departments', hint: 'onboarding.departments.hint', to: '/admin/departments', done: active.length > 1 },
    { id: 'invite', label: 'onboarding.invite', hint: 'onboarding.invite.hint', to: '/admin/users', done: users.length > 1 },
    {
      id: 'documents', label: 'onboarding.documents', hint: 'onboarding.documents.hint', to: '/documents',
      done: active.some((d) => (d.ready_document_count ?? d.document_count ?? 0) > 0),
    },
    {
      id: 'model', label: 'onboarding.model', hint: 'onboarding.model.hint', to: '/admin/organisation',
      done: lastTest.data?.items?.[0]?.details?.ok === true,
    },
  ];
  const left = steps.filter((s) => !s.done).length;
  if (left === 0) return null;

  const hide = () => { writePref(prefKey, '1'); setHidden(true); };
  return (
    <Card
      className="ws-onboarding" title={t('onboarding.title')} description={tn('onboarding.left', left)}
      actions={<Button size="sm" variant="ghost" onClick={hide}>{t('onboarding.hide')}</Button>}
    >
      <ol className="ws-onboarding__steps">
        {steps.map((step) => (
          <li key={step.id} className={['ws-onboarding__step', step.done && 'is-done'].filter(Boolean).join(' ')}>
            <span className="ws-onboarding__mark" aria-hidden="true">{step.done ? <Icon name="check" size={14} /> : null}</span>
            <span className="ws-onboarding__text">
              {step.done
                ? <span className="ws-onboarding__label">{t(step.label)}<span className="ws-sr-only"> — {t('onboarding.done')}</span></span>
                : step.id === 'invite' && onInvite
                  ? <button type="button" className="ws-linklike ws-onboarding__label" onClick={onInvite}>{t(step.label)}</button>
                  : <Link to={step.to} className="ws-onboarding__label">{t(step.label)}</Link>}
              {!step.done && <span className="ws-muted ws-small">{t(step.hint)}</span>}
            </span>
          </li>
        ))}
      </ol>
    </Card>
  );
}
