/* Server enums of the feature screens → dictionary keys and badge tones, in one place so a
   document, a run or an approval reads the same on every screen that shows it. */
import type { ApprovalStatus, DeliveryStatus, DocumentStatus, RunStatus, ScheduleKind } from '../../api/types';
import type { I18n, MessageKey } from '../../i18n';
import type { Tone } from '../../ui';

interface StatusLabel { label: MessageKey; tone: Tone }

export const DOCUMENT_STATUS: Record<DocumentStatus, StatusLabel> = {
  ready: { label: 'documents.status.ready', tone: 'success' },
  processing: { label: 'documents.status.processing', tone: 'accent' },
  failed: { label: 'documents.status.failed', tone: 'danger' },
};

export const RUN_STATUS: Record<RunStatus, StatusLabel> = {
  queued: { label: 'run.status.queued', tone: 'neutral' },
  running: { label: 'run.status.running', tone: 'accent' },
  succeeded: { label: 'run.status.succeeded', tone: 'success' },
  failed: { label: 'run.status.failed', tone: 'danger' },
};

export const DELIVERY_STATUS: Record<DeliveryStatus, StatusLabel> = {
  none: { label: 'delivery.none', tone: 'neutral' },
  pending: { label: 'delivery.pending', tone: 'warning' },
  approved: { label: 'delivery.approved', tone: 'success' },
  rejected: { label: 'delivery.rejected', tone: 'danger' },
};

export const APPROVAL_STATUS: Record<ApprovalStatus, StatusLabel> = {
  pending: { label: 'approvals.status.pending', tone: 'warning' },
  executing: { label: 'approvals.status.executing', tone: 'accent' },
  approved: { label: 'approvals.status.approved', tone: 'success' },
  rejected: { label: 'approvals.status.rejected', tone: 'danger' },
  cancelled: { label: 'approvals.status.cancelled', tone: 'neutral' },
  expired: { label: 'approvals.status.expired', tone: 'neutral' },
  failed: { label: 'approvals.status.failed', tone: 'danger' },
};

export const APPROVAL_STATUSES = Object.keys(APPROVAL_STATUS) as ApprovalStatus[];

export const SCHEDULE_KINDS: ScheduleKind[] = ['manual', 'daily', 'weekly'];

/** The kind's name; a kind added server-side later still reads as a plain "request". */
export function approvalKindLabel(i18n: I18n, kind: string): string {
  const key = `approvals.kind.${kind}`;
  return i18n.has(key) ? i18n.t(key) : i18n.t('approvals.kind.unknown');
}
