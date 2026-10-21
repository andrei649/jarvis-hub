/* The two ways a screen asks for a consequential action (spec §7 approvals):

   EmailRequestDialog — "Trimite pe email": recipients, subject and body prefilled from the
   answer or report, sent as an `email.send` request that a department approver must accept.
   CompanyRequestDialog — publish a document or share a report run with the whole company; an
   admin's own request of these admin-rule kinds executes immediately, so the dialog says so
   and reports the outcome instead of "sent for approval".

   Both check first who could decide the request and explain, before anything is sent, when
   nobody can — a request nobody can approve would only sit there until it expires. Both are
   mounted only while open, so every opening starts from the prefilled values — except that the
   email request keeps what was typed as a draft for its source (app/drafts.ts): a session that
   ends under the person does not lose the recipients and the edited text, and reopening
   „Trimite pe email" on the same answer or run brings them back until sent or cancelled. */
import React, { useEffect, useRef, useState } from 'react';
import { requestApproval, type ApprovalKind } from '../../api/approvals';
import { WorkspaceApiError } from '../../api/client';
import type { Approval } from '../../api/types';
import { draftText, useDraftMirror, useRestoredDraft } from '../../app/drafts';
import { describeCode, describeError, errorCode, errorField } from '../../app/errors';
import { useUser } from '../../app/session';
import { useI18n } from '../../i18n';
import { Button, Dialog, focusFirstInvalid, LoadingBlock, Notice, TextArea, TextField, useToast } from '../../ui';
import { ButtonLink } from './ButtonLink';
import { CitedMarkdown } from './CitedMarkdown';
import { MAX_RECIPIENTS, parseRecipients } from './recipients';
import { useApprovalReadiness, type ApprovalReadiness } from './useApprovalReadiness';

const SUBJECT_MAX = 200;
const EMAIL_BODY_MAX = 30_000;

/** Who can decide, or why nobody can; `noApprover` names the role the request is missing. */
function ReadinessNotice({ readiness, noApprover }: { readiness: ApprovalReadiness; noApprover: string }) {
  const i18n = useI18n();
  const { t, tn } = i18n;
  if (readiness.loading) return <LoadingBlock label={t('request.checking')} lines={1} />;
  if (readiness.error) {
    return (
      <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void readiness.reload()}>{t('common.retry')}</Button>}>
        {describeError(i18n, readiness.error)}
      </Notice>
    );
  }
  if (readiness.smtpReady === false) return <Notice tone="warning">{t('error.smtp_not_configured')}</Notice>;
  if (readiness.count === 0) {
    return (
      <Notice tone="warning" title={t('request.noApprover.title')}>{noApprover}</Notice>
    );
  }
  if (readiness.count !== null) return <p className="ws-muted ws-small">{tn('request.eligible', readiness.count)}</p>;
  return null;
}

/** The waiting request a `409 already_requested` points at, so the dialog can link to it. */
function existingRequestId(err: unknown): number | null {
  if (!(err instanceof WorkspaceApiError) || err.code !== 'already_requested') return null;
  const id = Number(err.extra.approval_id);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function canSubmit(readiness: ApprovalReadiness): boolean {
  return !readiness.loading && !readiness.error && readiness.smtpReady !== false && (readiness.count ?? 0) > 0;
}

export interface EmailSource { type: 'message' | 'report_run'; id: number }

export interface EmailRequestDialogProps {
  onClose: () => void;
  /** The deciding department; null when admins decide (a shared run of another department). */
  departmentId: number | null;
  departmentName: string;
  source: EmailSource;
  defaultSubject: string;
  defaultBody: string;
}

type EmailErrors = { to?: string; subject?: string; body?: string };
interface EmailDraft { to: string; subject: string; body: string }

export function EmailRequestDialog({ onClose, departmentId, departmentName, source, defaultSubject, defaultBody }: EmailRequestDialogProps) {
  const i18n = useI18n();
  const { t } = i18n;
  const readiness = useApprovalReadiness('email.send', departmentId);
  const userId = useUser().id;
  const prefilledSubject = defaultSubject.slice(0, SUBJECT_MAX);
  const draftKey = `email.${source.type}.${source.id}`;
  const restored = useRestoredDraft<EmailDraft>(userId, draftKey);
  const [to, setTo] = useState(draftText(restored?.to, ''));
  const [subject, setSubject] = useState(draftText(restored?.subject, prefilledSubject).slice(0, SUBJECT_MAX));
  const [body, setBody] = useState(draftText(restored?.body, defaultBody));
  const [errors, setErrors] = useState<EmailErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [existingId, setExistingId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<{ approval: Approval; emails: string[] } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const pristine = !to.trim() && subject === prefilledSubject && body === defaultBody;
  const clearDraft = useDraftMirror<EmailDraft>(userId, draftKey, { to, subject, body }, pristine);
  /** Cancel, Escape or the close button: the person gave up on the request, so is its draft. */
  const cancel = () => { clearDraft(); onClose(); };
  useEffect(() => {
    if (!Object.keys(errors).length) return;
    // A body error must be seen in the editor, not behind the preview.
    if (errors.body) setPreviewing(false);
    focusFirstInvalid(formRef.current);
  }, [errors]);

  const validate = (): { found: EmailErrors; emails: string[] } => {
    const found: EmailErrors = {};
    const { emails, invalid } = parseRecipients(to);
    if (invalid) found.to = t('emailRequest.error.invalid', { email: invalid });
    else if (emails.length === 0) found.to = t('emailRequest.error.to');
    else if (emails.length > MAX_RECIPIENTS) found.to = t('emailRequest.error.tooMany', { max: MAX_RECIPIENTS });
    if (!subject.trim()) found.subject = t('emailRequest.error.subject');
    if (!body.trim()) found.body = t('emailRequest.error.body');
    else if (body.length > EMAIL_BODY_MAX) found.body = t('common.tooLong', { max: EMAIL_BODY_MAX });
    return { found, emails };
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const { found, emails } = validate();
    setErrors(found);
    setFormError(null);
    setExistingId(null);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const approval = await requestApproval({
        kind: 'email.send',
        payload: { to: emails, subject: subject.trim(), body_markdown: body, source },
      });
      clearDraft();
      setSent({ approval, emails });
    } catch (err) {
      const field = errorField(err);
      const message = describeError(i18n, err);
      if (field === 'to' || errorCode(err) === 'recipient_not_allowed') setErrors({ to: message });
      else if (field === 'subject') setErrors({ subject: message });
      else if (field === 'body_markdown') setErrors({ body: message });
      else setFormError(message);
      setExistingId(existingRequestId(err));
      if (errorCode(err) === 'no_eligible_approver' || errorCode(err) === 'smtp_not_configured') void readiness.reload();
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <Dialog
        open onClose={onClose} title={t('emailRequest.done.title')}
        footer={(
          <>
            <ButtonLink to={`/approvals/${sent.approval.id}`} onClick={onClose}>{t('request.viewRequest')}</ButtonLink>
            <Button variant="primary" onClick={onClose}>{t('common.done')}</Button>
          </>
        )}
      >
        <Notice tone="success" live="polite">{t('emailRequest.done.body', { recipients: sent.emails.join(', ') })}</Notice>
      </Dialog>
    );
  }

  return (
    <Dialog
      open onClose={cancel} title={t('emailRequest.title')} description={t('emailRequest.desc')} busy={busy} size="lg"
      footer={(
        <>
          <Button onClick={cancel} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" type="submit" form="ws-email-request" icon="send" busy={busy} disabled={!canSubmit(readiness)}>{t('emailRequest.submit')}</Button>
        </>
      )}
    >
      {restored && <Notice tone="accent">{t('draft.restoredSend')}</Notice>}
      <ReadinessNotice
        readiness={readiness}
        noApprover={departmentId === null ? t('request.noApprover.admin') : t('request.noApprover.department', { department: departmentName })}
      />
      {formError && (
        <Notice
          tone="danger" live="assertive"
          action={existingId !== null ? <ButtonLink to={`/approvals/${existingId}`} size="sm" onClick={cancel}>{t('request.viewRequest')}</ButtonLink> : undefined}
        >
          {formError}
        </Notice>
      )}
      <form id="ws-email-request" ref={formRef} className="ws-form" onSubmit={submit} noValidate>
        <TextField
          label={t('emailRequest.to')} hint={t('emailRequest.toHint')} value={to} error={errors.to} inputMode="email"
          onChange={(e) => setTo(e.target.value)} autoComplete="off" spellCheck={false} data-autofocus="true"
        />
        <TextField label={t('emailRequest.subject')} value={subject} maxLength={SUBJECT_MAX} error={errors.subject} onChange={(e) => setSubject(e.target.value)} />
        <div className="ws-stack">
          {previewing ? (
            <section className="ws-email-preview" aria-labelledby="ws-email-preview-title">
              <p className="ws-email-preview__head ws-strong" id="ws-email-preview-title">{t('emailRequest.previewTitle')}</p>
              <div className="ws-email-preview__body">
                <CitedMarkdown text={body} citations={[]} onCite={() => undefined} headingOffset={2} />
              </div>
            </section>
          ) : (
            <TextArea
              label={t('emailRequest.body')} hint={t('emailRequest.bodyHint')} value={body} rows={10} error={errors.body}
              onChange={(e) => setBody(e.target.value)}
            />
          )}
          <div>
            <Button size="sm" variant="ghost" icon={previewing ? 'edit' : 'eye'} aria-pressed={previewing} onClick={() => setPreviewing((on) => !on)}>
              {t('emailRequest.preview')}
            </Button>
          </div>
        </div>
      </form>
    </Dialog>
  );
}

export interface CompanyRequestDialogProps {
  onClose: () => void;
  kind: Extract<ApprovalKind, 'document.company_publish' | 'report.share_company'>;
  payload: Record<string, unknown>;
  departmentId: number | null;
  title: string;
  body: string;
  /** Shown to admins (the action applies at once) and to everyone else (it needs an admin). */
  adminNote: string;
  requestNote: string;
  adminSubmitLabel: string;
  /** Toast once the action has really been applied. */
  doneText: string;
  onDone: (approval: Approval) => void;
}

export function CompanyRequestDialog(props: CompanyRequestDialogProps) {
  const { onClose, kind, payload, departmentId, title, body, adminNote, requestNote, adminSubmitLabel, doneText, onDone } = props;
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const isAdmin = useUser().role === 'admin';
  const readiness = useApprovalReadiness(kind, departmentId, !isAdmin);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [existingId, setExistingId] = useState<number | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setExistingId(null);
    try {
      const approval = await requestApproval({ kind, payload });
      if (approval.status === 'failed') {
        setError(t('request.executedFailed', { reason: describeCode(i18n, approval.error_code) }));
        return;
      }
      toast.success(approval.status === 'approved' ? doneText : t('request.sent'));
      onDone(approval);
      onClose();
    } catch (err) {
      setError(describeError(i18n, err));
      setExistingId(existingRequestId(err));
      if (errorCode(err) === 'no_eligible_approver') void readiness.reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open onClose={onClose} title={title} busy={busy}
      footer={(
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant="primary" icon={isAdmin ? 'globe' : 'send'} busy={busy} onClick={submit} disabled={!isAdmin && !canSubmit(readiness)}>
            {isAdmin ? adminSubmitLabel : t('request.submit')}
          </Button>
        </>
      )}
    >
      <p>{body}</p>
      {isAdmin ? <Notice tone="accent">{adminNote}</Notice> : (
        <>
          <p className="ws-muted">{requestNote}</p>
          <ReadinessNotice readiness={readiness} noApprover={t('request.noApprover.admin')} />
        </>
      )}
      {error && <p className="ws-inline-error" role="alert">{error}</p>}
      {existingId !== null && <div><ButtonLink to={`/approvals/${existingId}`} size="sm" onClick={onClose}>{t('request.viewRequest')}</ButtonLink></div>}
    </Dialog>
  );
}
