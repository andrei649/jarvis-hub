import {
  ApiError, decideApproval, decideApprovalConsent, validatedConsentOffer,
  type ApprovalAction, type ApprovalConsentChoice, type ApprovalTask,
} from '../api/client';
import type { ServerConfig } from '../storage/settings';
import { approvalPolicy } from './approvalPolicy';

export type ApprovalSelection = { action: ApprovalAction } | { choice: ApprovalConsentChoice };
export type ApprovalBusy = { id: number; action: ApprovalAction | ApprovalConsentChoice } | null;

type Submission = {
  config: ServerConfig;
  task: ApprovalTask;
  selection: ApprovalSelection;
  reason?: string;
  isCurrent?: () => boolean;
  onApplied?: () => Promise<void>;
  onBusy?: (busy: ApprovalBusy) => void;
};

/** Owns one in-flight decision synchronously, including its success-only refresh. */
export class ApprovalDecisionController {
  private active: ApprovalBusy = null;
  get busy(): ApprovalBusy { return this.active; }

  async submit(input: Submission): Promise<boolean> {
    if (this.active || input.isCurrent?.() === false) return false;
    const { config, task, selection, reason } = input;
    if (!Number.isSafeInteger(task.id) || task.id <= 0) throw new ApiError('Invalid approval task');
    if (reason !== undefined && (typeof reason !== 'string' || Array.from(reason).length > 280)) {
      throw new ApiError('Reason must be at most 280 characters');
    }
    const policy = approvalPolicy(task);
    const offer = validatedConsentOffer(task.consent_offer);
    if ('choice' in selection) {
      if (!policy.canApprove) throw new ApiError('Reusable approval unavailable in mobile app');
      if (!offer || !offer.choices.includes(selection.choice)) throw new ApiError('Consent offer is unavailable');
      if (selection.choice === 'always' && !offer.categories.every(category => category.permanent)) {
        throw new ApiError('Permanent consent is unavailable for this category');
      }
    } else if ((selection.action === 'accept' && !policy.canApprove)
      || (selection.action === 'reject' && !policy.canReject)
      || (selection.action === 'defer' && !policy.canDefer)
      || !['accept', 'reject', 'defer'].includes(selection.action)) {
      throw new ApiError('Approval unavailable in mobile app');
    }

    this.active = { id: task.id, action: 'choice' in selection ? selection.choice : selection.action };
    try {
      input.onBusy?.(this.active);
      if ('choice' in selection) {
        await decideApprovalConsent(config, task.id, selection.choice, offer!.revision, reason);
      } else {
        const reply = await decideApproval(config, task.id, selection.action, reason);
        if (reply?.ok !== true || reply.task?.id !== task.id
          || typeof reply.task.status !== 'string' || !reply.task.status) {
          throw new ApiError('Decision was not confirmed by the server');
        }
      }
      if (input.isCurrent?.() === false) return false;
      await input.onApplied?.();
      return true;
    } finally {
      this.active = null;
      input.onBusy?.(null);
    }
  }
}
