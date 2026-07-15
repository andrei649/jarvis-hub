import type { ApprovalTask } from '../api/client';

export type ApprovalPolicy = {
  showPayload: boolean;
  canApprove: boolean;
  canReject: boolean;
  canDefer: boolean;
};

export function approvalPolicy(task: Pick<ApprovalTask, 'kind'>): ApprovalPolicy {
  if (task.kind === 'toolrpc.desktop_run') {
    return { showPayload: false, canApprove: false, canReject: true, canDefer: true };
  }
  return { showPayload: true, canApprove: true, canReject: true, canDefer: true };
}
