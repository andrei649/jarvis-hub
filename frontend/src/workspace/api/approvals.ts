/* Approvals (spec §7, S4 routers/workspace_approvals.py): the inbox and the caller's own
   requests, the eligibility probe screens run before they offer a request, and the decision
   and cancel actions. */
import { appUrl } from '../../base-path';
import { api, query } from './client';
import { unwrapOne } from './shape';
import type {
  Approval, ApprovalBox, ApprovalRequest, ApprovalsResponse, ApprovalStatus, DecisionRequest, EligibleResponse,
} from './types';

/** The approval kinds the screens request (spec §7 effect registry). */
export type ApprovalKind = 'email.send' | 'report.delivery' | 'report.share_company' | 'document.company_publish';

export const listApprovals = (box: ApprovalBox, status?: ApprovalStatus) =>
  api.get<ApprovalsResponse>(appUrl(`/api/workspace/approvals${query({ box, status })}`));

/** How many people other than the caller could decide such a request in that department. */
export const eligibleDeciders = (kind: ApprovalKind, departmentId: number | null) =>
  api.get<EligibleResponse>(appUrl(`/api/workspace/approvals/eligible${query({ kind, department_id: departmentId })}`));

export const requestApproval = async (body: ApprovalRequest): Promise<Approval> =>
  unwrapOne<Approval>(await api.post(appUrl('/api/workspace/approvals'), body), ['approval', 'item']);

export const getApproval = async (id: number): Promise<Approval> =>
  unwrapOne<Approval>(await api.get(appUrl(`/api/workspace/approvals/${id}`)), ['approval', 'item']);

export const decideApproval = async (id: number, body: DecisionRequest): Promise<Approval> =>
  unwrapOne<Approval>(await api.post(appUrl(`/api/workspace/approvals/${id}/decide`), body), ['approval', 'item']);

export const cancelApproval = async (id: number): Promise<Approval | undefined> =>
  unwrapOne<Approval | undefined>(await api.post(appUrl(`/api/workspace/approvals/${id}/cancel`), {}), ['approval', 'item']);
