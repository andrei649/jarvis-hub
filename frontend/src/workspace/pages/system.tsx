/* Whole-screen states outside the signed-in shell: the boot splash, "Workspace is not
   enabled", "server unreachable", and the in-shell 404 page. */
import React from 'react';
import { useI18n } from '../i18n';
import { Link, useDocumentTitle } from '../router';
import { BrandMark, Button, EmptyState, PageHeader, Spinner } from '../ui';

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="ws-centered">{children}</div>;
}

export function SplashScreen() {
  const { t } = useI18n();
  return (
    <Centered>
      <BrandMark size={40} />
      <Spinner label={t('common.loading')} />
    </Centered>
  );
}

export function DisabledScreen() {
  const { t } = useI18n();
  useDocumentTitle(t('system.disabled.title'));
  return (
    <Centered>
      <main className="ws-system-card">
        <BrandMark size={40} />
        <h1 className="ws-system-card__title">{t('system.disabled.title')}</h1>
        <p className="ws-system-card__body">{t('system.disabled.body')}</p>
      </main>
    </Centered>
  );
}

export function UnreachableScreen({ onRetry }: { onRetry: () => void }) {
  const { t } = useI18n();
  useDocumentTitle(t('system.unreachable.title'));
  return (
    <Centered>
      <main className="ws-system-card">
        <BrandMark size={40} />
        <h1 className="ws-system-card__title">{t('system.unreachable.title')}</h1>
        <p className="ws-system-card__body">{t('system.unreachable.body')}</p>
        <Button variant="primary" icon="refresh" onClick={onRetry}>{t('common.retry')}</Button>
      </main>
    </Centered>
  );
}

export function NotFoundPage() {
  const { t } = useI18n();
  useDocumentTitle(t('system.notFound.title'));
  return (
    <>
      <PageHeader title={t('system.notFound.title')} />
      <EmptyState
        icon="search"
        title={t('system.notFound.lead')}
        body={t('system.notFound.body')}
        action={<Link to="/assistant" className="ws-btn ws-btn--primary ws-btn--md"><span className="ws-btn__content"><span className="ws-btn__label">{t('system.notFound.home')}</span></span></Link>}
      />
    </>
  );
}
