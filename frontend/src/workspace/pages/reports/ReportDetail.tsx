/* One report (/reports/:reportId): its definition, its email delivery state and recipients,
   and the history of its runs. The history refreshes itself while a run is still going, so a
   scheduled run that starts while the page is open shows up and finishes in place. */
import React, { useMemo, useState } from 'react';
import { listDocuments } from '../../api/documents';
import { deleteReport, getReport, listRuns } from '../../api/reports';
import type { Report, ReportRun } from '../../api/types';
import { describeError, errorCode } from '../../app/errors';
import { useAsync, usePolling } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { Link, navigate, useDocumentTitle } from '../../router';
import { Badge, Button, Card, ConfirmDialog, EmptyState, IconButton, LoadingBlock, Menu, Notice, PageHeader, Table, useToast, type Column } from '../../ui';
import { ButtonLink } from '../shared/ButtonLink';
import { DELIVERY_STATUS, RUN_STATUS } from '../shared/labels';
import { ReportForm } from './ReportForm';
import { isRunActive, runDurationMs, scheduleSummary } from './schedule';
import { startRun } from './startRun';

const HISTORY_POLL_MS = 4000;

function DocumentNames({ report }: { report: Report }) {
  const { t } = useI18n();
  const docs = useAsync(() => (report.document_ids.length ? listDocuments({ status: 'ready' }) : Promise.resolve([])), [report.document_ids.join(',')]);
  if (report.document_ids.length === 0) return <span>{t('reports.detail.allDocuments')}</span>;
  if (!docs.data) return <span className="ws-muted">{t('common.loading')}</span>;
  const titles = new Map(docs.data.map((d) => [d.id, d.title]));
  return (
    <span className="ws-badge-list">
      {report.document_ids.map((id) => <Badge key={id}>{titles.get(id) ?? t('reports.detail.documentGone')}</Badge>)}
    </span>
  );
}

export function ReportDetail({ reportId }: { reportId: number }) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  const { departments } = useWorkspace();
  const report = useAsync(() => getReport(reportId), [reportId]);
  const runs = useAsync(() => listRuns(reportId), [reportId]);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [starting, setStarting] = useState(false);
  const data = report.data && report.data.id === reportId ? report.data : null;
  useDocumentTitle(data ? `${data.name} · ${t('nav.reports')}` : t('nav.reports'));

  const sortedRuns = useMemo(() => [...(runs.data ?? [])].sort((a, b) => b.created_at - a.created_at), [runs.data]);
  const live = sortedRuns.some((r) => isRunActive(r));
  usePolling(async () => { await runs.reload(); }, HISTORY_POLL_MS, live);

  const runNow = async () => {
    setStarting(true);
    try {
      const started = await startRun(reportId);
      toast.info(t(started.alreadyRunning ? 'reports.run.alreadyRunning' : 'reports.run.started'));
      navigate(`/report-runs/${started.runId}`);
    } catch (err) {
      toast.error(describeError(i18n, err));
      setStarting(false);
    }
  };

  if (!data) {
    return (
      <>
        <PageHeader title={t('nav.reports')} />
        {report.error
          ? (errorCode(report.error) === 'not_found'
            ? <EmptyState icon="chart" title={t('error.not_found')} action={<ButtonLink to="/reports" variant="primary">{t('reports.back')}</ButtonLink>} />
            : <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void report.reload()}>{t('common.retry')}</Button>}>{describeError(i18n, report.error)}</Notice>)
          : <LoadingBlock label={t('common.loading')} lines={6} />}
      </>
    );
  }

  const department = departments.find((d) => d.id === data.department_id)?.name ?? `#${data.department_id}`;
  const delivery = DELIVERY_STATUS[data.delivery_status ?? 'none'];
  const columns: Column<ReportRun>[] = [
    {
      key: 'when', header: t('run.field.started'),
      render: (r) => <Link to={`/report-runs/${r.id}`}>{fmt.dateTime(r.started_at ?? r.created_at)}</Link>,
    },
    { key: 'status', header: t('run.field.status'), render: (r) => <Badge tone={RUN_STATUS[r.status].tone} dot>{t(RUN_STATUS[r.status].label)}</Badge> },
    { key: 'trigger', header: t('run.field.trigger'), secondary: true, render: (r) => t(r.trigger === 'schedule' ? 'run.trigger.schedule' : 'run.trigger.manual') },
    {
      key: 'duration', header: t('run.field.duration'), secondary: true, align: 'end',
      render: (r) => { const ms = runDurationMs(r); return ms === null ? <span className="ws-muted">—</span> : <span className="ws-num">{fmt.durationMs(ms)}</span>; },
    },
    {
      key: 'model', header: t('run.field.model'), secondary: true,
      render: (r) => (r.model ? <span className="ws-cell-stack"><span className="ws-mono ws-small">{r.model}</span>{r.locality && <span className={`ws-locality ws-locality--${r.locality}`}>{t(`locality.${r.locality}`)}</span>}</span> : <span className="ws-muted">—</span>),
    },
    { key: 'shared', header: t('run.field.visibility'), secondary: true, render: (r) => (r.shared_company ? <Badge tone="accent">{t('run.shared')}</Badge> : <span className="ws-muted">—</span>) },
  ];

  return (
    <>
      <div className="ws-backlink"><ButtonLink to="/reports" variant="ghost" size="sm" icon="chevronLeft">{t('reports.back')}</ButtonLink></div>
      <PageHeader
        eyebrow={department} title={data.name}
        actions={(
          <>
            {data.can_run !== false && <Button variant="primary" icon="play" busy={starting} onClick={() => void runNow()}>{t('reports.action.run')}</Button>}
            {data.can_edit !== false && (
              <Menu
                label={t('reports.actionsFor', { name: data.name })}
                items={[
                  { id: 'edit', label: t('reports.action.edit'), icon: 'edit', onSelect: () => setEditing(true) },
                  { kind: 'separator', id: 'sep' },
                  { id: 'delete', label: t('reports.action.delete'), icon: 'trash', danger: true, onSelect: () => setDeleting(true) },
                ]}
                trigger={(trigger) => <IconButton variant="secondary" icon="more" label={t('reports.actionsFor', { name: data.name })} {...trigger} />}
              />
            )}
          </>
        )}
      />
      <div className="ws-grid ws-grid--main-aside ws-grid--start">
        <Card title={t('reports.detail.instructions')}>
          <p className="ws-prewrap">{data.instructions}</p>
        </Card>
        <Card title={t('reports.detail.about')}>
          <dl className="ws-dl">
            <dt>{t('reports.detail.schedule')}</dt>
            <dd>{scheduleSummary(i18n, data)}{data.schedule_kind !== 'manual' && <span className="ws-muted ws-small"> · {data.timezone}</span>}</dd>
            <dt>{t('reports.detail.nextRun')}</dt><dd>{data.next_run_at ? fmt.dateTimeIn(data.next_run_at, data.timezone) : t('reports.manualOnly')}</dd>
            <dt>{t('reports.detail.lastRun')}</dt><dd>{data.last_run_at ? fmt.dateTime(data.last_run_at) : t('reports.never')}</dd>
            <dt>{t('reports.detail.documents')}</dt><dd><DocumentNames report={data} /></dd>
            <dt>{t('reports.detail.delivery')}</dt><dd><Badge tone={delivery.tone}>{t(delivery.label)}</Badge></dd>
            {(data.delivery_emails ?? []).length > 0 && <><dt>{t('reports.detail.recipients')}</dt><dd>{data.delivery_emails.join(', ')}</dd></>}
          </dl>
          {data.delivery_status === 'pending' && <Notice tone="warning">{t('reports.detail.deliveryPending')}</Notice>}
          {data.delivery_status === 'rejected' && <Notice tone="danger">{t('reports.detail.deliveryRejected')}</Notice>}
        </Card>
      </div>
      <section className="ws-stack" aria-labelledby="ws-run-history">
        <h2 id="ws-run-history" className="ws-section-title">{t('reports.detail.history')}</h2>
        {runs.error ? (
          <Notice tone="danger" action={<Button size="sm" icon="refresh" onClick={() => void runs.reload()}>{t('common.retry')}</Button>}>{describeError(i18n, runs.error)}</Notice>
        ) : (
          <Table
            caption={t('reports.detail.history')} columns={columns} rows={runs.data ? sortedRuns : null} rowKey={(r) => r.id} loading={runs.loading}
            empty={<EmptyState compact icon="clock" title={t('reports.detail.historyEmpty')} body={t('reports.detail.historyEmptyBody')} />}
          />
        )}
      </section>
      {editing && (
        <ReportForm
          report={data} defaultDepartmentId={data.department_id} onClose={() => setEditing(false)}
          onSaved={() => void report.reload()}
        />
      )}
      <ConfirmDialog
        open={deleting} onClose={() => setDeleting(false)}
        title={t('reports.delete.title')} body={t('reports.delete.body', { name: data.name })}
        confirmLabel={t('reports.action.delete')}
        onConfirm={async () => {
          await deleteReport(data.id);
          toast.success(t('reports.delete.done'));
          navigate('/reports');
        }}
      />
    </>
  );
}
