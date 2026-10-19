/* One run of a report (/report-runs/:runId, and /shared-reports/:runId for company-shared ones).

   While the run is queued or running the page polls it and says honestly what is happening.
   The server stores a run `succeeded` before it talks to the mail server, so while its approved
   email is still on the way (`delivery_state` pending) the page keeps polling and says the
   report is being emailed, then shows to whom it went or why it was not sent — no reload needed
   (NWS-20). Polling stops once the run and its email are settled, when the page is left, and when
   the run answers 404 (its report was deleted, or the reader lost access, mid-run or mid-send): the
   page then drops the copy it last read and shows the not-found state, said once (R4-01).
   One always-mounted status region says each change once. A failed run says why in the chat's
   own words — the model's reason (`error_reason`) and the same next step (UX-23); an email that
   was not sent gives admins the mail server's own cause (what to check in the email settings)
   and members the plain sentence with "let an administrator know". A finished run shows the
   report rendered through the shared Markdown renderer with its citations, how and where it
   was produced (where, in words; the model id for admins; duration), and the ways to take it further: export as
   Markdown or a print-ready HTML page, print, share with the company, send by email. The page
   says honestly when the report was made but its email delivery failed, and when a share
   request is still waiting. The h1 is the report's name; the report's own "# Title" renders one
   level down, under it. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { getRun, runExportUrl } from '../../api/reports';
import type { Citation, ReportRunDetail } from '../../api/types';
import { ADMIN_FIXABLE_CODES, describeCode, describeError, errorCode, hintKey } from '../../app/errors';
import { useAsync, usePolling } from '../../app/hooks';
import { useUser } from '../../app/session';
import { useWorkspace } from '../../app/workspace';
import { useI18n } from '../../i18n';
import { navigate, useDocumentTitle } from '../../router';
import { Badge, Button, Card, EmptyState, LoadingBlock, Notice, PageHeader, Skeleton, Spinner, useToast } from '../../ui';
import { CompanyRequestDialog, EmailRequestDialog } from '../shared/ApprovalDialogs';
import { ButtonLink, DownloadLink } from '../shared/ButtonLink';
import { CitedMarkdown, SourcesList } from '../shared/CitedMarkdown';
import { LocalityChip } from '../shared/LocalityChip';
import { RUN_STATUS } from '../shared/labels';
import { SourceDrawer } from '../shared/SourceDrawer';
import { useApprovalReadiness } from '../shared/useApprovalReadiness';
import { isDeliveryPending, isRunActive, runDurationMs } from './schedule';
import { startRun } from './startRun';

export const RUN_POLL_MS = 2000;

export function runReportName(run: Pick<ReportRunDetail, 'report' | 'report_name' | 'report_id'>, fallback: string): string {
  return run.report?.name ?? run.report_name ?? fallback;
}

function RunMeta({ run }: { run: ReportRunDetail }) {
  const { t, fmt } = useI18n();
  const isAdmin = useUser().role === 'admin';
  const duration = runDurationMs(run);
  return (
    <dl className="ws-dl ws-run-meta">
      <dt>{t('run.field.status')}</dt>
      <dd><Badge tone={RUN_STATUS[run.status].tone} dot>{t(RUN_STATUS[run.status].label)}</Badge></dd>
      <dt>{t('run.field.trigger')}</dt><dd>{t(run.trigger === 'schedule' ? 'run.trigger.schedule' : 'run.trigger.manual')}</dd>
      {run.started_at && <><dt>{t('run.field.started')}</dt><dd>{fmt.dateTime(run.started_at)}</dd></>}
      {run.finished_at && <><dt>{t('run.field.finished')}</dt><dd>{fmt.dateTime(run.finished_at)}</dd></>}
      {duration !== null && <><dt>{t('run.field.duration')}</dt><dd>{fmt.durationMs(duration)}</dd></>}
      {/* A row of its own where the card is narrow (features.css), so the words never wrap (UX-22). */}
      {run.locality && <><dt className="ws-run-meta__wide">{t('run.field.where')}</dt><dd className="ws-run-meta__wide"><LocalityChip locality={run.locality} /></dd></>}
      {isAdmin && run.model && <><dt>{t('run.field.model')}</dt><dd className="ws-mono">{run.model}</dd></>}
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

/** An export button's label: the full words ("Exportă Markdown") are its accessible name at every
    width; under 480 px they are read but not shown, and the short form ("Markdown") is shown under
    the group's visible caption ("Exportă"), so no label wraps onto two lines on a phone (UX-21). */
function ExportLabel({ full, short }: { full: string; short: string }) {
  return (
    <>
      <span className="ws-export__full">{full}</span>
      <span className="ws-export__short" aria-hidden="true">{short}</span>
    </>
  );
}

/** Codes whose next step is the same as in the chat (the model was out, busy or too slow). */
const MODEL_HINTS: ReadonlySet<string> = new Set(['model_unavailable', 'model_policy_blocked', 'model_busy', 'model_timeout']);

/** The hub stopped mid-send: nobody knows whether the recipients got the email. */
const DELIVERY_INTERRUPTED = 'delivery_interrupted';

/** Where a run stands for the live page: being written, ready with its email on the way, or done. */
type RunPhase = 'active' | 'delivering' | 'settled';

function runPhase(run: ReportRunDetail): RunPhase {
  if (isRunActive(run)) return 'active';
  return isDeliveryPending(run) ? 'delivering' : 'settled';
}

export function RunView({ runId, shared = false }: { runId: number; shared?: boolean }) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  const isAdmin = useUser().role === 'admin';
  const { departments, posture, refreshPosture } = useWorkspace();
  const run = useAsync(() => getRun(runId), [runId]);
  // A run that answers 404 is gone: a reload that fails keeps the last copy it read, which would
  // keep a deleted run "being emailed" and polled forever (R4-01).
  const gone = errorCode(run.error) === 'not_found';
  const data = !gone && run.data && run.data.id === runId ? run.data : null;
  const phase = data ? runPhase(data) : null;
  const active = phase === 'active';
  const delivering = phase === 'delivering';
  const [citation, setCitation] = useState<Citation | null>(null);
  const [emailing, setEmailing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const lastPhase = useRef<RunPhase | null>(null);
  const exportCaption = `ws-export-${useId().replace(/:/g, '')}`;

  // The run is followed until it is written AND its email has an outcome (NWS-20).
  usePolling(() => run.reload(), RUN_POLL_MS, active || delivering);

  const deliveryFailed = data?.status === 'succeeded' && data.error === 'delivery_failed';
  const deliveryUnknown = deliveryFailed && data?.error_code === DELIVERY_INTERRUPTED;
  // Why the run failed, as the chat says it: the code's sentence plus the model's reason.
  const failureText = data?.status === 'failed' ? describeCode(i18n, data.error_code, data.error_reason) : '';
  // Why its email was not sent. The mail server's precise cause says what to check in the email
  // settings, which is for the admins who can; a member reads the plain sentence, and the hint
  // under it says to let an admin know.
  const deliveryText = data && deliveryFailed ? describeCode(i18n, data.error_code, isAdmin ? data.error_reason : null) : '';

  // One always-mounted status region says what happens (a region inserted together with its
  // text is often not read): "running" or "being emailed" when the page opens on a live run,
  // then each change once — ready, the email's outcome, or why it failed.
  useEffect(() => {
    if (!data || phase === null) return;
    const previous = lastPhase.current;
    lastPhase.current = phase;
    if (previous === phase) return;
    if (phase === 'active') {
      if (previous === null) setAnnouncement(t(data.status === 'queued' ? 'run.live.queued' : 'run.live.running'));
      return;
    }
    if (phase === 'delivering') {
      setAnnouncement(t('run.live.sending'));
      return;
    }
    // Opened on a finished run: the page itself says everything, nothing changed to announce.
    if (previous === null) return;
    const said: string[] = [];
    if (data.status === 'failed') said.push(t('run.live.failed', { reason: failureText }));
    else if (previous === 'active') said.push(t('run.live.done'));
    if (deliveryFailed) said.push(t(deliveryUnknown ? 'run.live.deliveryUnknown' : 'run.live.deliveryFailed', { reason: deliveryText }));
    else if (data.status === 'succeeded' && data.delivered_to.length > 0) said.push(t('run.live.sent', { recipients: data.delivered_to.join(', ') }));
    if (said.length > 0) setAnnouncement(said.join(' '));
    // A run the model failed has just marked a dead model server down: show it in the chip too;
    // one it wrote while the chip still says "unavailable" has just marked the server up again.
    if (data.status === 'failed' && data.error_code && MODEL_HINTS.has(data.error_code)) void refreshPosture();
    if (data.status === 'succeeded' && posture && !posture.available) void refreshPosture();
  }, [phase, data, t, failureText, deliveryText, deliveryFailed, deliveryUnknown, posture, refreshPosture]);

  // A run the live page was following has gone: say so once, in place of the stale "running" or
  // "being emailed" sentence (the not-found state itself is not a live region).
  useEffect(() => {
    if (!gone || lastPhase.current === null) return;
    lastPhase.current = null;
    setAnnouncement(t('error.not_found'));
  }, [gone, t]);

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

  const status = data ? t(RUN_STATUS[data.status].label) : '';
  const subtitle = data && (when ? t('run.subtitle', { date: fmt.dateTime(when), status }) : t('run.subtitleQueued', { status }));
  const content = data?.content_md ?? '';
  // The chat's own next steps for the same model failure: per code and reason, then per code.
  const modelFailure = data?.status === 'failed' && data.error_code !== null && MODEL_HINTS.has(data.error_code);
  const failureHint = modelFailure ? hintKey(i18n, 'chat.hint', data?.error_code, data?.error_reason) : null;
  const adminFixable = modelFailure && isAdmin && ADMIN_FIXABLE_CODES.has(data?.error_code ?? '');
  const adminHint = adminFixable ? hintKey(i18n, 'chat.hint.admin', data?.error_code, data?.error_reason) : null;

  // The same PageHeader element while loading and once loaded: the h1 that took focus after
  // the navigation stays in the document, so focus is never dropped to <body> (WCAG 2.4.3).
  return (
    <>
      <div className="ws-print-hide ws-backlink">{back}</div>
      <PageHeader
        eyebrow={data ? data.department_name ?? departmentName : undefined}
        title={data ? name : t('nav.reports')}
        description={subtitle || undefined}
        actions={data?.status === 'succeeded' && (
          <div className="ws-run-actions ws-print-hide">
            <div className="ws-export">
              <span className="ws-export__caption" id={exportCaption}>{t('run.exportGroup')}</span>
              <div className="ws-btn-group" role="group" aria-labelledby={exportCaption}>
                <DownloadLink href={runExportUrl(data.id, 'md')} icon="download" size="sm"><ExportLabel full={t('run.export.md')} short={t('run.export.mdShort')} /></DownloadLink>
                <DownloadLink href={runExportUrl(data.id, 'html')} icon="download" size="sm"><ExportLabel full={t('run.export.html')} short={t('run.export.htmlShort')} /></DownloadLink>
                <Button size="sm" icon="printer" onClick={() => window.print()}>{t('run.print')}</Button>
              </div>
            </div>
            {data.can_share && !data.shared_company && <Button size="sm" icon="globe" onClick={() => setSharing(true)}>{t('run.share')}</Button>}
            {canEmail && email.smtpReady !== false && <Button size="sm" icon="mail" onClick={() => setEmailing(true)}>{t('run.email')}</Button>}
          </div>
        )}
      />
      <p className="ws-sr-only" role="status" aria-live="polite">{announcement}</p>
      {!data && (run.error
        ? (errorCode(run.error) === 'not_found'
          ? <EmptyState icon="chart" title={t('error.not_found')} action={<ButtonLink to={shared ? '/shared-reports' : '/reports'} variant="primary">{t(shared ? 'nav.sharedReports' : 'reports.back')}</ButtonLink>} />
          : <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void run.reload()}>{t('common.retry')}</Button>}>{describeError(i18n, run.error)}</Notice>)
        : <LoadingBlock label={t('common.loading')} lines={6} />)}
      {data && active && (
        <Notice tone="accent" title={t(data.status === 'queued' ? 'run.live.queued' : 'run.live.running')}>
          <span className="ws-run-live"><Spinner size={16} /> {t('run.live.note')}</span>
        </Notice>
      )}
      {data && delivering && (
        <Notice tone="accent" title={t('run.delivery.sendingTitle')}>
          <span className="ws-run-live"><Spinner size={16} /> {t('run.delivery.sendingNote')}</span>
        </Notice>
      )}
      {data?.status === 'failed' && (
        <Notice
          tone="danger" title={t('run.failed.title')}
          action={!shared ? <Button size="sm" icon="refresh" busy={rerunning} onClick={() => void rerun()}>{t('run.retry')}</Button> : undefined}
        >
          <p>{failureText}</p>
          {failureHint && <p className="ws-small">{t(failureHint)}</p>}
          {adminHint && <p className="ws-small">{t(adminHint)}</p>}
          {adminFixable && <div className="ws-run-fix"><ButtonLink to="/admin/organisation" variant="ghost" size="sm">{t('chat.adminLink')}</ButtonLink></div>}
        </Notice>
      )}
      {deliveryFailed && (
        <Notice tone="warning" title={t(deliveryUnknown ? 'run.delivery.interruptedTitle' : 'run.delivery.failedTitle')}>
          <p>{deliveryText}</p>
          <p className="ws-small">{t(deliveryUnknown ? 'run.delivery.interruptedHint' : isAdmin ? 'run.delivery.failedHintAdmin' : 'run.delivery.failedHint')}</p>
        </Notice>
      )}
      {data?.share_pending && !data.shared_company && (
        <Notice tone="accent" title={t('run.sharePending')}>{t('run.sharePendingNote')}</Notice>
      )}
      {data && (
        <div className="ws-grid ws-grid--main-aside ws-run">
          <Card className="ws-run__doc">
            {data.status === 'succeeded' && content
              ? <article className="ws-report"><CitedMarkdown text={content} citations={data.citations ?? []} onCite={setCitation} headingOffset={1} /></article>
              : data.status === 'succeeded' ? <p className="ws-muted">{t('run.empty')}</p>
                : data.status === 'failed' ? <p className="ws-muted">{t('run.failed.noReport')}</p> : <ReportPlaceholder />}
          </Card>
          <div className="ws-stack ws-print-hide">
            <Card title={t('run.details')}><RunMeta run={data} /></Card>
            {data.citations && data.citations.length > 0 && <Card><SourcesList citations={data.citations} onCite={setCitation} /></Card>}
          </div>
        </div>
      )}
      <SourceDrawer citation={citation} context="report" onClose={() => setCitation(null)} />
      {data && emailing && (
        <EmailRequestDialog
          onClose={() => setEmailing(false)} departmentId={departmentId} departmentName={departmentName}
          source={{ type: 'report_run', id: data.id }}
          defaultSubject={when ? `${name} — ${fmt.date(when)}` : name}
          defaultBody={content}
        />
      )}
      {data && sharing && (
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
