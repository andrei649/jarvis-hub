/* One approval, read fresh from the server: who asked, for what, what approving will do, who
   may decide, and — once decided — the outcome (sent, failed with the reason, rejected with
   the note). Deciding asks for confirmation with an optional note for the requester; the
   requester can cancel their own pending request. */
import React, { useState } from 'react';
import { cancelApproval, decideApproval, getApproval } from '../../api/approvals';
import type { Approval } from '../../api/types';
import { describeCode, describeError, errorCode } from '../../app/errors';
import { useAsync } from '../../app/hooks';
import { useUser } from '../../app/session';
import { useI18n } from '../../i18n';
import { Avatar, Badge, Button, ConfirmDialog, Dialog, Drawer, EmptyState, LoadingBlock, Notice, TextArea, useToast } from '../../ui';
import { approvalKindLabel, APPROVAL_STATUS } from '../shared/labels';
import { approvedRecipients, PayloadPreview, sentTo } from './PayloadPreview';

const NOTE_MAX = 1000;

type Decision = 'approve' | 'reject';

function DecisionDialog({ approval, decision, onClose, onDecided }: {
  approval: Approval;
  decision: Decision;
  onClose: () => void;
  /** With the decided item, or without one when the server says someone decided first. */
  onDecided: (approval?: Approval) => void;
}) {
  const i18n = useI18n();
  const { t } = i18n;
  const toast = useToast();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approving = decision === 'approve';

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (note.length > NOTE_MAX) { setError(t('common.tooLong', { max: NOTE_MAX })); return; }
    setBusy(true);
    setError(null);
    try {
      const decided = await decideApproval(approval.id, { decision, note: note.trim() || undefined });
      if (decided.status === 'failed') toast.error(t('approvals.decide.failed', { reason: describeCode(i18n, decided.error_code) }));
      else toast.success(t(decided.status === 'rejected' ? 'approvals.decide.rejected' : 'approvals.decide.approved'));
      onDecided(decided);
      onClose();
    } catch (err) {
      setError(describeError(i18n, err));
      if (errorCode(err) === 'already_decided') onDecided();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open onClose={onClose} busy={busy} role="alertdialog"
      title={approving ? t('approvals.decide.approveTitle') : t('approvals.decide.rejectTitle')}
      description={approval.summary}
      footer={(
        <>
          <Button onClick={onClose} disabled={busy}>{t('common.cancel')}</Button>
          <Button variant={approving ? 'primary' : 'danger'} type="submit" form="ws-decision" busy={busy} icon={approving ? 'check' : 'xCircle'}>
            {approving ? t('approvals.approve') : t('approvals.reject')}
          </Button>
        </>
      )}
    >
      <p className="ws-muted">{approving ? t('approvals.decide.approveBody') : t('approvals.decide.rejectBody')}</p>
      <form id="ws-decision" className="ws-form" onSubmit={submit} noValidate>
        <TextArea
          label={t('approvals.decide.note')} optional value={note} rows={3} onChange={(e) => setNote(e.target.value)}
          aside={t('common.charCount', { count: note.length, max: NOTE_MAX })} data-autofocus="true"
        />
      </form>
      {error && <p className="ws-inline-error" role="alert">{error}</p>}
    </Dialog>
  );
}

function Outcome({ approval }: { approval: Approval }) {
  const i18n = useI18n();
  const { t } = i18n;
  const user = useUser();
  if (approval.status === 'approved') {
    const emails = sentTo(approval.result);
    const delivery = approvedRecipients(approval.result);
    return (
      <Notice tone="success" title={t('approvals.result.executed')}>
        {emails.length > 0 && <p>{t('approvals.result.sentTo', { emails: emails.join(', ') })}</p>}
        {delivery.length > 0 && <p>{t('approvals.result.deliveryTo', { emails: delivery.join(', ') })}</p>}
      </Notice>
    );
  }
  if (approval.status === 'failed') return <Notice tone="danger" title={t('approvals.result.failedTitle')}>{describeCode(i18n, approval.error_code)}</Notice>;
  if (approval.status === 'rejected') return <Notice tone="danger">{t('approvals.result.rejected')}</Notice>;
  if (approval.status === 'expired') return <Notice tone="warning">{t('approvals.result.expired')}</Notice>;
  if (approval.status === 'cancelled') return <Notice tone="accent">{t('approvals.result.cancelled')}</Notice>;
  if (approval.status === 'executing') return <Notice tone="accent">{t('approvals.result.executing')}</Notice>;
  if (approval.can_decide) return null;
  return <p className="ws-muted">{approval.requester?.id === user.id ? t('approvals.own') : t('approvals.waiting')}</p>;
}

export interface ApprovalDrawerProps {
  id: number | null;
  departmentName: (approval: Pick<Approval, 'department_id' | 'department_name'>) => string;
  onClose: () => void;
  /** After a decision or a cancel: the page refreshes its list and the pending badge. */
  onChanged: () => void;
}

export function ApprovalDrawer({ id, departmentName, onClose, onChanged }: ApprovalDrawerProps) {
  const i18n = useI18n();
  const { t, fmt } = i18n;
  const toast = useToast();
  const detail = useAsync<Approval | null>(() => (id !== null && id > 0 ? getApproval(id) : Promise.resolve(null)), [id]);
  const [deciding, setDeciding] = useState<Decision | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const approval = detail.data && detail.data.id === id ? detail.data : null;
  const notFound = id === -1 || errorCode(detail.error) === 'not_found';
  // Nobody decides their own request, except an admin whose admin-rule request ran at once; the
  // server marks that with a fixed English note, so the UI says it in the reader's language.
  const selfDecided = Boolean(approval?.decider && approval.decider.id === approval.requester?.id);

  /** Shows the decided item at once (or re-reads it), then lets the page refresh. */
  const changed = (updated?: Approval) => {
    if (updated && updated.id === id) detail.setData(updated);
    else void detail.reload();
    onChanged();
  };

  return (
    <Drawer
      open={id !== null} onClose={onClose} size="lg"
      title={approval ? t('approvals.drawer.title', { id: String(approval.id) }) : t('nav.approvals')}
      footer={approval && (approval.can_decide || approval.can_cancel) && (
        <>
          {approval.can_cancel && <Button variant="danger-ghost" icon="ban" onClick={() => setCancelling(true)}>{t('approvals.cancel')}</Button>}
          <span className="ws-footer-spacer" />
          {approval.can_decide && (
            <>
              <Button variant="danger" icon="xCircle" onClick={() => setDeciding('reject')}>{t('approvals.reject')}</Button>
              <Button variant="primary" icon="check" onClick={() => setDeciding('approve')}>{t('approvals.approve')}</Button>
            </>
          )}
        </>
      )}
    >
      {notFound && <EmptyState icon="approvals" title={t('error.not_found')} />}
      {!notFound && detail.error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={() => void detail.reload()}>{t('common.retry')}</Button>}>
          {describeError(i18n, detail.error)}
        </Notice>
      ) : null}
      {!notFound && !detail.error && !approval && <LoadingBlock label={t('common.loading')} lines={6} />}
      {approval && (
        <>
          <div className="ws-approval-head">
            <Badge tone={APPROVAL_STATUS[approval.status].tone} dot>{t(APPROVAL_STATUS[approval.status].label)}</Badge>
            <span className="ws-muted">{approvalKindLabel(i18n, approval.kind)}</span>
          </div>
          <p className="ws-approval-summary">{approval.summary}</p>
          <dl className="ws-dl">
            <dt>{t('approvals.field.requester')}</dt>
            <dd><span className="ws-person"><Avatar name={approval.requester?.name ?? '?'} size={24} />{approval.requester?.name}</span></dd>
            <dt>{t('approvals.field.department')}</dt><dd>{departmentName(approval)}</dd>
            <dt>{t('approvals.field.created')}</dt><dd>{fmt.dateTime(approval.created_at)}</dd>
            {approval.status === 'pending' && <><dt>{t('approvals.field.expires')}</dt><dd>{fmt.relative(approval.expires_at)}</dd></>}
            {approval.decider && <><dt>{t('approvals.field.decider')}</dt><dd>{approval.decider.name}</dd></>}
            {approval.decided_at && <><dt>{t('approvals.field.decided')}</dt><dd>{fmt.dateTime(approval.decided_at)}</dd></>}
            {selfDecided
              ? <><dt>{t('approvals.field.note')}</dt><dd>{t('approvals.adminAction')}</dd></>
              : approval.decision_note && <><dt>{t('approvals.field.note')}</dt><dd className="ws-prewrap">{approval.decision_note}</dd></>}
            {approval.status === 'pending' && approval.eligible_deciders && approval.eligible_deciders.length > 0 && (
              <><dt>{t('approvals.field.deciders')}</dt><dd>{approval.eligible_deciders.map((p) => p.name).join(', ')}</dd></>
            )}
          </dl>
          <Outcome approval={approval} />
          <section className="ws-stack" aria-labelledby="ws-approval-preview">
            <h3 id="ws-approval-preview" className="ws-subtitle">{t('approvals.preview')}</h3>
            <PayloadPreview approval={approval} />
          </section>
        </>
      )}
      {approval && deciding && (
        <DecisionDialog approval={approval} decision={deciding} onClose={() => setDeciding(null)} onDecided={changed} />
      )}
      <ConfirmDialog
        open={cancelling} onClose={() => setCancelling(false)}
        title={t('approvals.cancel.title')} body={approval ? t('approvals.cancel.body', { summary: approval.summary }) : ''}
        confirmLabel={t('approvals.cancel')}
        onConfirm={async () => {
          if (!approval) return;
          const cancelled = await cancelApproval(approval.id);
          toast.success(t('approvals.cancel.done'));
          changed(cancelled && typeof cancelled === 'object' && 'status' in cancelled ? cancelled : undefined);
        }}
      />
    </Drawer>
  );
}
