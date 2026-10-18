/* Admin → Usage: headline numbers, daily activity and the per-department breakdown, for a
   chosen period. Every number comes from GET /admin/stats; a department column appears only
   for metrics the server actually reports, so nothing is padded with zeros it did not send.
   Days are the reader's calendar days: the browser's time zone goes to the server as `tz`, so a
   question asked at 00:30 in Bucharest counts on today's bar, not on yesterday's UTC one. */
import React, { useMemo, useState } from 'react';
import { getUsage, listAdminDepartments } from '../../api/admin';
import type { UsageDepartmentRow, UsageStats } from '../../api/types';
import { describeError, errorField } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useI18n, type MessageKey } from '../../i18n';
import { Button, Card, EmptyState, LoadingBlock, Notice, Select, Skeleton, Table, type Column } from '../../ui';
import { browserTimeZone } from '../reports/schedule';
import { DailyBarChart } from './DailyBarChart';

const PERIODS = [7, 30, 90] as const;

const DEPARTMENT_METRICS: { keys: string[]; label: MessageKey }[] = [
  { keys: ['members', 'member_count', 'users'], label: 'usage.metric.members' },
  { keys: ['documents', 'document_count'], label: 'usage.metric.documents' },
  { keys: ['conversations', 'conversation_count'], label: 'usage.metric.conversations' },
  { keys: ['questions'], label: 'usage.metric.questions' },
  { keys: ['reports', 'report_count'], label: 'usage.metric.reports' },
  { keys: ['report_runs'], label: 'usage.metric.reportRuns' },
  { keys: ['feedback_up'], label: 'usage.metric.feedbackUp' },
  { keys: ['feedback_down'], label: 'usage.metric.feedbackDown' },
];

function metricValue(row: UsageDepartmentRow, keys: string[]): number | null {
  for (const key of keys) if (typeof row[key] === 'number') return row[key] as number;
  return null;
}

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="ws-kpi">
      <p className="ws-kpi__label">{label}</p>
      <p className="ws-kpi__value">{value}</p>
      {sub && <p className="ws-kpi__sub">{sub}</p>}
    </div>
  );
}

function Kpis({ stats }: { stats: UsageStats }) {
  const { t, tn, fmt } = useI18n();
  const { totals } = stats;
  const rated = totals.feedback_up + totals.feedback_down;
  return (
    <div className="ws-kpis">
      <Kpi label={t('usage.kpi.users')} value={fmt.number(totals.users)} sub={tn('usage.kpi.active7d', totals.active_users_7d)} />
      <Kpi label={t('usage.kpi.questions')} value={fmt.number(totals.questions)} sub={tn('usage.kpi.conversations', totals.conversations)} />
      <Kpi label={t('usage.kpi.documents')} value={fmt.number(totals.documents)} />
      <Kpi label={t('usage.kpi.reports')} value={fmt.number(totals.reports)} sub={tn('usage.kpi.runs', totals.report_runs)} />
      <Kpi label={t('usage.kpi.approvals')} value={fmt.number(totals.approvals_pending)} />
      <Kpi
        label={t('usage.kpi.feedback')} value={rated ? fmt.percent(totals.feedback_up / rated) : '—'}
        sub={rated ? `${tn('usage.kpi.helpful', totals.feedback_up)} · ${tn('usage.kpi.notHelpful', totals.feedback_down)}` : t('usage.kpi.noFeedback')}
      />
    </div>
  );
}

function DataTable({ stats }: { stats: UsageStats }) {
  const { t, fmt } = useI18n();
  return (
    <details className="ws-details">
      <summary>{t('usage.table.show')}</summary>
      <div className="ws-table-scroll">
        <table className="ws-table ws-table--compact">
          <caption className="ws-sr-only">{t('usage.table.caption')}</caption>
          <thead><tr><th scope="col">{t('usage.table.day')}</th><th scope="col" className="is-end">{t('usage.metric.questions')}</th><th scope="col" className="is-end">{t('usage.metric.reportRuns')}</th></tr></thead>
          <tbody>
            {stats.daily.map((d) => (
              <tr key={d.date}><td>{fmt.day(d.date)}</td><td className="is-end ws-num">{fmt.number(d.questions)}</td><td className="is-end ws-num">{fmt.number(d.report_runs)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function UsageSection() {
  const i18n = useI18n();
  const { t, tn, fmt } = i18n;
  const [days, setDays] = useState<number>(30);
  const [zone] = useState(browserTimeZone);
  // A zone the server does not know (an exotic browser setting) falls back to its default.
  const stats = useAsync(async () => {
    try {
      return await getUsage(days, zone);
    } catch (err) {
      if (zone && errorField(err) === 'tz') return getUsage(days);
      throw err;
    }
  }, [days, zone]);
  const departments = useAsync(listAdminDepartments, []);
  const names = useMemo(() => new Map((departments.data ?? []).map((d) => [d.id, d.name])), [departments.data]);

  const rows = stats.data?.per_department ?? null;
  const shown = DEPARTMENT_METRICS.filter((m) => (rows ?? []).some((r) => metricValue(r, m.keys) !== null));
  const nameOf = (row: UsageDepartmentRow) => row.name ?? names.get(Number(row.department_id ?? row.id)) ?? row.slug ?? `#${row.department_id ?? row.id ?? '?'}`;
  const columns: Column<UsageDepartmentRow>[] = [
    { key: 'name', header: t('usage.table.department'), render: (r) => <span className="ws-strong">{nameOf(r)}</span> },
    ...shown.map((m) => ({
      key: m.label, header: t(m.label), align: 'end' as const,
      render: (r: UsageDepartmentRow) => {
        const v = metricValue(r, m.keys);
        return v === null ? <span className="ws-muted">—</span> : <span className="ws-num">{fmt.number(v)}</span>;
      },
    })),
  ];

  return (
    <div className="ws-stack ws-stack--loose">
      <div className="ws-toolbar">
        <Select
          className="ws-toolbar__filter" label={t('usage.period')} value={String(days)} onChange={(e) => setDays(Number(e.target.value))}
          options={PERIODS.map((p) => ({ value: String(p), label: tn('usage.lastDays', p) }))}
        />
        <div className="ws-toolbar__end">
          <Button variant="ghost" icon="refresh" onClick={() => void stats.reload()} disabled={stats.loading}>{t('common.refresh')}</Button>
        </div>
      </div>
      {stats.error && (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void stats.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, stats.error)}
        </Notice>
      )}
      {!stats.error && !stats.data && (
        <>
          <div className="ws-kpis">{Array.from({ length: 6 }, (_, i) => <div key={i} className="ws-kpi"><Skeleton width="50%" /><Skeleton width="40%" height={28} /></div>)}</div>
          <Card><LoadingBlock label={t('common.loading')} /></Card>
        </>
      )}
      {stats.data && (
        <>
          <Kpis stats={stats.data} />
          <Card title={t('usage.activity')} description={tn('usage.activityDesc', days, { zone: (stats.data.timezone || zone || 'Europe/Bucharest').replace(/_/g, ' ') })}>
            {stats.data.daily.length === 0 ? (
              <EmptyState compact icon="activity" title={t('usage.chart.none')} />
            ) : (
              <>
                <div className="ws-grid ws-grid--2">
                  <DailyBarChart title={t('usage.metric.questions')} days={stats.data.daily} value={(d) => d.questions} describe={(n) => tn('usage.count.questions', n)} />
                  <DailyBarChart title={t('usage.metric.reportRuns')} days={stats.data.daily} value={(d) => d.report_runs} describe={(n) => tn('usage.count.runs', n)} />
                </div>
                <DataTable stats={stats.data} />
              </>
            )}
          </Card>
          <Card title={t('usage.byDepartment')}>
            <Table
              caption={t('usage.byDepartment')} columns={columns} rows={rows} rowKey={(r) => String(r.department_id ?? r.id ?? r.slug ?? r.name)}
              empty={<EmptyState compact icon="layers" title={t('usage.noDepartments')} />}
            />
          </Card>
        </>
      )}
    </div>
  );
}
