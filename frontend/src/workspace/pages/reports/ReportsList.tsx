/* Reports of the sidebar's department: name, schedule, how the last run went, when the next
   one is due, and the email delivery state. "Run now" queues a run and opens it, where its
   progress is followed live. */
import React, { useState } from 'react';
import { deleteReport, listReports } from '../../api/reports';
import type { Report } from '../../api/types';
import { describeError } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { Link, navigate, useDocumentTitle } from '../../router';
import { Badge, Button, ConfirmDialog, EmptyState, IconButton, Menu, Notice, PageHeader, Table, useToast, type Column, type MenuEntry } from '../../ui';
import { DELIVERY_STATUS, RUN_STATUS } from '../shared/labels';
import { ReportForm } from './ReportForm';
import { scheduleSummary } from './schedule';
import { startRun } from './startRun';

export function ReportsList() {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  useDocumentTitle(t('nav.reports'));
  const { currentDepartment } = useWorkspace();
  const departmentId = currentDepartment?.id ?? null;
  const reports = useAsync(() => (departmentId === null ? Promise.resolve([] as Report[]) : listReports(departmentId)), [departmentId]);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Report | null>(null);
  const [deleting, setDeleting] = useState<Report | null>(null);
  const [runningId, setRunningId] = useState<number | null>(null);

  const run = async (report: Report) => {
    setRunningId(report.id);
    try {
      const started = await startRun(report.id);
      toast.info(t(started.alreadyRunning ? 'reports.run.alreadyRunning' : 'reports.run.started'));
      navigate(`/report-runs/${started.runId}`);
    } catch (err) {
      toast.error(describeError(i18n, err));
      setRunningId(null);
    }
  };

  const rowMenu = (report: Report): MenuEntry[] => {
    const entries: MenuEntry[] = [{ id: 'open', label: t('reports.action.open'), icon: 'eye', onSelect: () => navigate(`/reports/${report.id}`) }];
    if (report.can_edit !== false) {
      entries.push({ id: 'edit', label: t('reports.action.edit'), icon: 'edit', onSelect: () => setEditing(report) });
      entries.push({ kind: 'separator', id: 'sep' });
      entries.push({ id: 'delete', label: t('reports.action.delete'), icon: 'trash', danger: true, onSelect: () => setDeleting(report) });
    }
    return entries;
  };

  const columns: Column<Report>[] = [
    {
      key: 'name', header: t('reports.col.name'),
      render: (r) => (
        <span className="ws-cell-stack">
          <Link to={`/reports/${r.id}`} className="ws-strong">{r.name}</Link>
          <span className="ws-muted ws-small ws-clamp">{r.instructions}</span>
        </span>
      ),
    },
    {
      key: 'schedule', header: t('reports.col.schedule'), secondary: true,
      render: (r) => (
        <span className="ws-cell-stack">
          <span>{scheduleSummary(i18n, r)}</span>
          {r.schedule_kind !== 'manual' && <span className="ws-muted ws-small">{r.timezone}</span>}
        </span>
      ),
    },
    {
      key: 'last', header: t('reports.col.lastRun'),
      render: (r) => (r.last_run
        ? (
          <span className="ws-cell-stack">
            <Badge tone={RUN_STATUS[r.last_run.status].tone} dot>{t(RUN_STATUS[r.last_run.status].label)}</Badge>
            {r.last_run.finished_at && <Link to={`/report-runs/${r.last_run.id}`} className="ws-small">{fmt.relative(r.last_run.finished_at)}</Link>}
          </span>
        )
        : <span className="ws-muted">{t('reports.never')}</span>),
    },
    {
      key: 'next', header: t('reports.col.nextRun'), secondary: true,
      render: (r) => (r.next_run_at ? <span>{fmt.dateTimeIn(r.next_run_at, r.timezone)}</span> : <span className="ws-muted">{t('reports.manualOnly')}</span>),
    },
    {
      key: 'delivery', header: t('reports.col.delivery'), secondary: true,
      render: (r) => <Badge tone={DELIVERY_STATUS[r.delivery_status ?? 'none'].tone}>{t(DELIVERY_STATUS[r.delivery_status ?? 'none'].label)}</Badge>,
    },
    {
      key: 'actions', header: '', srHeader: t('common.actions'), align: 'end', width: '180px',
      render: (r) => (
        <span className="ws-row-actions">
          {r.can_run !== false && (
            <Button size="sm" icon="play" busy={runningId === r.id} onClick={() => void run(r)} aria-label={t('reports.action.runNamed', { name: r.name })}>
              {t('reports.action.run')}
            </Button>
          )}
          <Menu
            label={t('reports.actionsFor', { name: r.name })} items={rowMenu(r)}
            trigger={(trigger) => <IconButton icon="more" label={t('reports.actionsFor', { name: r.name })} {...trigger} />}
          />
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow={currentDepartment?.name} title={t('nav.reports')} description={t('reports.description')}
        actions={<Button variant="primary" icon="plus" onClick={() => setCreating(true)} disabled={departmentId === null}>{t('reports.new')}</Button>}
      />
      {reports.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void reports.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, reports.error)}
        </Notice>
      ) : (
        <Table
          caption={t('nav.reports')} columns={columns} rows={reports.data} rowKey={(r) => r.id} loading={reports.loading}
          empty={<EmptyState icon="chart" title={t('reports.empty')} body={t('reports.emptyBody')} action={<Button variant="primary" icon="plus" onClick={() => setCreating(true)}>{t('reports.new')}</Button>} />}
        />
      )}
      {(creating || editing) && departmentId !== null && (
        <ReportForm
          report={editing} defaultDepartmentId={departmentId}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={(saved, created) => {
            if (created) navigate(`/reports/${saved.id}`);
            else void reports.reload();
          }}
        />
      )}
      <ConfirmDialog
        open={deleting !== null} onClose={() => setDeleting(null)}
        title={t('reports.delete.title')} body={deleting ? t('reports.delete.body', { name: deleting.name }) : ''}
        confirmLabel={t('reports.action.delete')}
        onConfirm={async () => {
          if (!deleting) return;
          await deleteReport(deleting.id);
          toast.success(t('reports.delete.done'));
          reports.setData((rows) => rows?.filter((r) => r.id !== deleting.id) ?? null);
        }}
      />
    </>
  );
}
