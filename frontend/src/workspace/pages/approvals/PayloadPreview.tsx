/* What approving a request will actually do, per kind, so nobody approves blind:
   the email exactly as it will be sent (recipients, subject, rendered body), the recipients a
   report will be delivered to, the run or document that becomes visible company-wide. The
   payload is server data, so every field is read defensively. */
import React from 'react';
import type { Approval } from '../../api/types';
import { useI18n } from '../../i18n';
import { Badge } from '../../ui';
import { ButtonLink } from '../shared/ButtonLink';
import { CitedMarkdown } from '../shared/CitedMarkdown';

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function list(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

function id(value: unknown): number | null {
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : null;
}

function Recipients({ emails }: { emails: string[] }) {
  return <span className="ws-badge-list">{emails.map((email) => <Badge key={email}>{email}</Badge>)}</span>;
}

function EmailPreview({ payload }: { payload: Record<string, unknown> }) {
  const { t } = useI18n();
  const source = (payload.source && typeof payload.source === 'object' ? payload.source : {}) as Record<string, unknown>;
  const runId = source.type === 'report_run' ? id(source.id) : null;
  return (
    <div className="ws-email-preview">
      <dl className="ws-dl ws-email-preview__head">
        <dt>{t('approvals.preview.email.to')}</dt><dd><Recipients emails={list(payload.to)} /></dd>
        <dt>{t('approvals.preview.email.subject')}</dt><dd className="ws-strong">{text(payload.subject)}</dd>
        {typeof source.type === 'string' && (
          <>
            <dt>{t('approvals.preview.email.source')}</dt>
            <dd>
              {source.type === 'report_run' ? t('approvals.preview.source.report_run') : t('approvals.preview.source.message')}
              {runId !== null && <ButtonLink to={`/report-runs/${runId}`} variant="ghost" size="sm">{t('approvals.preview.openReport')}</ButtonLink>}
            </dd>
          </>
        )}
      </dl>
      <div className="ws-email-preview__body" aria-label={t('approvals.preview.email.body')} role="group">
        <CitedMarkdown text={text(payload.body_markdown)} citations={[]} onCite={() => undefined} />
      </div>
    </div>
  );
}

function DeliveryPreview({ payload }: { payload: Record<string, unknown> }) {
  const { t } = useI18n();
  const reportId = id(payload.report_id);
  return (
    <div className="ws-stack">
      <p>{t('approvals.preview.delivery')}</p>
      <Recipients emails={list(payload.emails)} />
      {reportId !== null && <div><ButtonLink to={`/reports/${reportId}`} size="sm" icon="chart">{t('approvals.preview.openReport')}</ButtonLink></div>}
    </div>
  );
}

function SharePreview({ payload }: { payload: Record<string, unknown> }) {
  const { t } = useI18n();
  const runId = id(payload.run_id);
  return (
    <div className="ws-stack">
      <p>{t('approvals.preview.share')}</p>
      {runId !== null && <div><ButtonLink to={`/report-runs/${runId}`} size="sm" icon="chart">{t('approvals.preview.openReport')}</ButtonLink></div>}
    </div>
  );
}

function PublishPreview({ payload }: { payload: Record<string, unknown> }) {
  const { t } = useI18n();
  const documentId = id(payload.document_id);
  return (
    <div className="ws-stack">
      <p>{t('approvals.preview.publish')}</p>
      {documentId !== null && <div><ButtonLink to={`/documents/${documentId}`} size="sm" icon="file">{t('approvals.preview.openDocument')}</ButtonLink></div>}
    </div>
  );
}

export function PayloadPreview({ approval }: { approval: Approval }) {
  const payload = approval.payload ?? {};
  if (approval.kind === 'email.send') return <EmailPreview payload={payload} />;
  if (approval.kind === 'report.delivery') return <DeliveryPreview payload={payload} />;
  if (approval.kind === 'report.share_company') return <SharePreview payload={payload} />;
  if (approval.kind === 'document.company_publish') return <PublishPreview payload={payload} />;
  return <pre className="ws-payload">{JSON.stringify(payload, null, 2)}</pre>;
}

function firstList(result: Approval['result'], keys: string[]): string[] {
  if (!result) return [];
  for (const key of keys) {
    const emails = list(result[key]);
    if (emails.length) return emails;
  }
  return [];
}

/** Recipients the server reports as sent to, under whichever key the effect used. */
export function sentTo(result: Approval['result']): string[] {
  return firstList(result, ['sent_to', 'recipients', 'delivered_to', 'to']);
}

/** The recipients an approved report delivery snapshotted (`report.delivery` result). */
export function approvedRecipients(result: Approval['result']): string[] {
  return firstList(result, ['approved_recipients']);
}
