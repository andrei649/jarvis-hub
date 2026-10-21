/* Shared reports (/shared-reports, /shared-reports/:runId): report runs shared with the whole
   company, readable by everyone whatever their department. */
import React from 'react';
import { listSharedReports } from '../../api/reports';
import type { ReportRunDetail } from '../../api/types';
import { describeError } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { Link, useDocumentTitle } from '../../router';
import { Button, EmptyState, Notice, PageHeader, Table, type Column } from '../../ui';
import { runReportName, RunView } from '../reports/RunView';
import { LocalityChip } from '../shared/LocalityChip';
import { routeId } from '../shared/routeId';
import type { PageProps } from '../types';
import '../../features.css';

function SharedList() {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  useDocumentTitle(t('nav.sharedReports'));
  const { departments } = useWorkspace();
  const runs = useAsync(listSharedReports, []);
  // The server names the department: a shared run is mostly read from other departments, which
  // the reader's own department list does not contain. That list is only the fallback.
  const deptName = (run: ReportRunDetail) => {
    if (run.department_name) return run.department_name;
    const id = run.report?.department_id ?? run.department_id;
    return id === undefined ? '—' : departments.find((d) => d.id === id)?.name ?? '—';
  };
  const sorted = runs.data ? [...runs.data].sort((a, b) => (b.finished_at ?? b.created_at) - (a.finished_at ?? a.created_at)) : null;

  const columns: Column<ReportRunDetail>[] = [
    {
      key: 'report', header: t('shared.col.report'),
      render: (run) => <Link to={`/shared-reports/${run.id}`} className="ws-strong">{runReportName(run, t('reports.untitled', { id: String(run.report_id) }))}</Link>,
    },
    { key: 'department', header: t('shared.col.department'), secondary: true, render: (run) => deptName(run) },
    {
      key: 'finished', header: t('shared.col.finished'), nowrap: true,
      render: (run) => {
        const when = run.finished_at ?? run.created_at;
        return <span title={fmt.dateTime(when)}>{fmt.date(when)}</span>;
      },
    },
    {
      key: 'model', header: t('run.field.where'), secondary: true,
      render: (run) => (run.locality ? <LocalityChip locality={run.locality} short /> : <span className="ws-muted">—</span>),
    },
  ];

  return (
    <>
      <PageHeader title={t('nav.sharedReports')} description={t('shared.description')} />
      {runs.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void runs.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, runs.error)}
        </Notice>
      ) : (
        <Table
          caption={t('nav.sharedReports')} columns={columns} rows={sorted} rowKey={(run) => run.id} loading={runs.loading}
          empty={<EmptyState icon="share" title={t('shared.empty')} body={t('shared.emptyBody')} />}
        />
      )}
    </>
  );
}

export function SharedReportsPage({ params }: PageProps) {
  const { t } = useI18n();
  if (params.runId === undefined) return <SharedList />;
  const id = routeId(params.runId);
  if (id === null) {
    return (
      <>
        <PageHeader title={t('nav.sharedReports')} />
        <EmptyState icon="share" title={t('error.not_found')} />
      </>
    );
  }
  return <RunView key={id} runId={id} shared />;
}
