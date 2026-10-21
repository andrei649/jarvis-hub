/* Reports (/reports, /reports/:reportId, /report-runs/:runId): the department's report list,
   one report with its run history, and one run. */
import React from 'react';
import { useI18n } from '../../i18n';
import { useDocumentTitle } from '../../router';
import { EmptyState, PageHeader } from '../../ui';
import { ButtonLink } from '../shared/ButtonLink';
import { routeId } from '../shared/routeId';
import type { PageProps } from '../types';
import { ReportDetail } from './ReportDetail';
import { ReportsList } from './ReportsList';
import { RunView } from './RunView';
import '../../features.css';

function BadLink() {
  const { t } = useI18n();
  useDocumentTitle(t('nav.reports'));
  return (
    <>
      <PageHeader title={t('nav.reports')} />
      <EmptyState icon="chart" title={t('error.not_found')} action={<ButtonLink to="/reports" variant="primary">{t('reports.back')}</ButtonLink>} />
    </>
  );
}

export function ReportsPage({ params }: PageProps) {
  if (params.runId !== undefined) {
    const id = routeId(params.runId);
    return id === null ? <BadLink /> : <RunView key={id} runId={id} />;
  }
  if (params.reportId !== undefined) {
    const id = routeId(params.reportId);
    return id === null ? <BadLink /> : <ReportDetail key={id} reportId={id} />;
  }
  return <ReportsList />;
}
