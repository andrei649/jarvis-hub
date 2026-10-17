/* One run of a report (/report-runs/:runId, and /shared-reports/:runId for company-shared ones).

   While the run is queued or running the page polls it and says honestly what is happening;
   polling stops as soon as it finishes and when the page is left. A finished run shows the
   report rendered through the shared Markdown renderer with its citations, how and where it
   was produced (model, local or cloud, duration), and the ways to take it further: export as
   Markdown or a print-ready HTML page, print, share with the company, send by email. */
import React, { useEffect, useRef, useState } from 'react';
import { getRun, runExportUrl } from '../../api/reports';
import type { Citation, ReportRunDetail } from '../../api/types';
import { describeCode, describeError, errorCode } from '../../app/errors';
import { useAsync, usePolling } from '../../app/hooks';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { navigate, useDocumentTitle } from '../../router';
import { Badge, Button, Card, EmptyState, LoadingBlock, Notice, PageHeader, Skeleton, Spinner, useToast } from '../../ui';
import { CompanyRequestDialog, EmailRequestDialog } from '../shared/ApprovalDialogs';
import { ButtonLink, DownloadLink } from '../shared/ButtonLink';
import { CitedMarkdown, SourcesList } from '../shared/CitedMarkdown';
import { RUN_STATUS } from '../shared/labels';
import { SourceDrawer } from '../shared/SourceDrawer';
import { useApprovalReadiness } from '../shared/useApprovalReadiness';
import { isRunActive, runDurationMs } from './schedule';
import { startRun } from './startRun';

export const RUN_POLL_MS = 2000;

export function runReportName(run: Pick<ReportRunDetail, 'report' | 'report_name' | 'report_id'>, fallback: string): string {
  return run.report?.name ?? run.report_name ?? fallback;
}

function RunMeta({ run }: { run: ReportRunDetail }) {
  const { t, fmt } = useI18n();
  const duration = runDurationMs(run);
  return (
    <dl className="ws-dl ws-run-meta">
      <dt>{t('run.field.status')}</dt>
      <dd><Badge tone={RUN_STATUS[run.status].tone} dot>{t(RUN_STATUS[run.status].label)}</Badge></dd>
      <dt>{t('run.field.trigger')}</dt><dd>{t(run.trigger === 'schedule' ? 'run.trigger.schedule' : 'run.trigger.manual')}</dd>
      {run.started_at && <><dt>{t('run.field.started')}</dt><dd>{fmt.dateTime(run.started_at)}</dd></>}
      {run.finished_at && <><dt>{t('run.field.finished')}</dt><dd>{fmt.dateTime(run.finished_at)}</dd></>}
      {duration !== null && <><dt>{t('run.field.duration')}</dt><dd>{fmt.durationMs(duration)}</dd></>}
      {run.model && (
        <>
          <dt>{t('run.field.model')}</dt>
          <dd>
            <span className="ws-mono">{run.model}</span>
            {run.locality && <span className={`ws-locality ws-locality--${run.locality}`}>{t(`locality.${run.locality}`)}</span>}
          </dd>
        </>
      )}
      {run.delivered_to && run.delivered_to.length > 0 && <><dt>{t('run.field.deliveredTo')}</dt><dd>{run.delivered_to.join(', ')}</dd></>}
      {run.shared_company ? <><dt>{t('run.field.visibility')}</dt><dd><Badge tone="accent">{t('run.shared')}</Badge></dd></> : null}
    </dl>
  );
}

/** Where the report will appear; decorative, since the notice above already says what is happening. */
function ReportPlaceholder() {
  return (
    <div className="ws-loading-block" aria-hidden="true">
      {[70, 95, 88, 92, 60, 84].map((width, i) => <Skeleton key={i} width={`${width}%`} height={i === 0 ? 22 : 14} />)}
    </div>
  );
}

export function RunView({ runId, shared = false }: { runId: number; shared?: boolean }) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  const { departments } = useWorkspace();
  const run = useAsync(() => getRun(runId), [runId]);
  const data = run.data && run.data.id === runId ? run.data : null;
  const active = isRunActive(data);
  const [citation, setCitation] = useState<Citation | null>(null);
  const [emailing, setEmailing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const wasActive = useRef(false);

  usePolling(() => run.reload(), RUN_POLL_MS, active);

  useEffect(() => {
    if (wasActive.current && data && !active) {
      setAnnouncement(data.status === 'succeeded' ? t('run.live.done') : t('run.failed.title'));
    }
    wasActive.current = active;
  }, [active, data, t]);

  const name = data ? runReportName(data, t('reports.untitled', { id: String(data.report_id) })) : '';
  // Requests about a run are decided in the run's department when the caller works there; a
  // company-shared run of another department goes to the admins (the server's rule), so the
  // eligibility probe then asks without a department.
  const runDepartmentId = data?.report?.department_id ?? data?.department_id ?? null;
  const ownDepartment = departments.find((d) => d.id === runDepartmentId) ?? null;
  const departmentId = ownDepartment?.id ?? null;
  const departmentName = ownDepartment?.name ?? '';
  const canEmail = Boolean(data?.can_email && data.status === 'succeeded' && data.content_md);
  const email = useApprovalReadiness('email.send', departmentId, canEmail);
  const when = data?.finished_at ?? data?.started_at ?? data?.created_at;
  useDocumentTitle(name ? `${name} · ${t('nav.reports')}` : t('nav.reports'));

  const rerun = async () => {
    if (!data) return;
    setRerunning(true);
    try {
      const next = await startRun(data.report_id);
      if (next.alreadyRunning) toast.info(t('reports.run.alreadyRunning'));
      navigate(`/report-runs/${next.runId}`);
    } catch (err) {
      toast.error(describeError(i18n, err));
    } finally {
      setRerunning(false);
    }
  };

  const back = shared
    ? <ButtonLink to="/shared-reports" variant="ghost" size="sm" icon="chevronLeft">{t('nav.sharedReports')}</ButtonLink>
    : data && <ButtonLink to={`/reports/${data.report_id}`} variant="ghost" size="sm" icon="chevronLeft">{t('run.backToReport')}</ButtonLink>;

  if (!data) {
    return (
      <>
        <PageHeader title={t('nav.reports')} />
        {run.error
          ? (errorCode(run.error) === 'not_found'
            ? <EmptyState icon="chart" title={t('error.not_found')} action={<ButtonLink to={shared ? '/shared-reports' : '/reports'} variant="primary">{t(shared ? 'nav.sharedReports' : 'reports.back')}</ButtonLink>} />
            : <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void run.reload()}>{t('common.retry')}</Button>}>{describeError(i18n, run.error)}</Notice>)
          : <LoadingBlock label={t('common.loading')} lines={6} />}
      </>
    );
  }

  const content = data.content_md ?? '';
  return (
    <>
      <div className="ws-print-hide ws-backlink">{back}</div>
      <PageHeader
        eyebrow={name}
        title={when ? t('run.title', { date: fmt.dateTime(when) }) : t('run.titleQueued')}
        actions={data.status === 'succeeded' && (
          <div className="ws-run-actions ws-print-hide">
            <DownloadLink href={runExportUrl(data.id, 'md')} icon="download" size="sm">{t('run.export.md')}</DownloadLink>
            <DownloadLink href={runExportUrl(data.id, 'html')} icon="download" size="sm">{t('run.export.html')}</DownloadLink>
            <Button size="sm" icon="printer" onClick={() => window.print()}>{t('run.print')}</Button>
            {data.can_share && !data.shared_company && <Button size="sm" icon="globe" onClick={() => setSharing(true)}>{t('run.share')}</Button>}
            {canEmail && email.smtpReady !== false && <Button size="sm" icon="mail" onClick={() => setEmailing(true)}>{t('run.email')}</Button>}
          </div>
        )}
      />
      <p className="ws-sr-only" role="status" aria-live="polite">{announcement}</p>
      {active && (
        <Notice tone="accent" live="polite" title={t(data.status === 'queued' ? 'run.live.queued' : 'run.live.running')}>
          <span className="ws-run-live"><Spinner size={16} /> {t('run.live.note')}</span>
        </Notice>
      )}
      {data.status === 'failed' && (
        <Notice
          tone="danger" title={t('run.failed.title')}
          action={!shared ? <Button size="sm" icon="refresh" busy={rerunning} onClick={() => void rerun()}>{t('run.retry')}</Button> : undefined}
        >
          {describeCode(i18n, data.error_code)}
        </Notice>
      )}
      <div className="ws-grid ws-grid--main-aside ws-run">
        <Card className="ws-run__doc">
          {data.status === 'succeeded' && content
            ? <article className="ws-report"><CitedMarkdown text={content} citations={data.citations ?? []} onCite={setCitation} /></article>
            : data.status === 'succeeded' ? <p className="ws-muted">{t('run.empty')}</p>
              : data.status === 'failed' ? <p className="ws-muted">{t('run.failed.noReport')}</p> : <ReportPlaceholder />}
        </Card>
        <div className="ws-stack ws-print-hide">
          <Card title={t('run.details')}><RunMeta run={data} /></Card>
          {data.citations && data.citations.length > 0 && <Card><SourcesList citations={data.citations} onCite={setCitation} /></Card>}
        </div>
      </div>
      <SourceDrawer citation={citation} onClose={() => setCitation(null)} />
      {emailing && (
        <EmailRequestDialog
          onClose={() => setEmailing(false)} departmentId={departmentId} departmentName={departmentName}
          source={{ type: 'report_run', id: data.id }}
          defaultSubject={when ? `${name} — ${fmt.date(when)}` : name}
          defaultBody={content}
        />
      )}
      {sharing && (
        <CompanyRequestDialog
          onClose={() => setSharing(false)}
          kind="report.share_company" payload={{ run_id: data.id }} departmentId={departmentId}
          title={t('share.title')} body={t('share.body', { name })}
          adminNote={t('share.adminNow')} requestNote={t('share.needsAdmin')} adminSubmitLabel={t('share.submitNow')}
          doneText={t('share.done')} onDone={() => void run.reload()}
        />
      )}
    </>
  );
}
