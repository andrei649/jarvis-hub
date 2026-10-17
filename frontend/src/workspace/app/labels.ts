/* Server enums → dictionary keys, in one place so every screen names roles, statuses and audit
   actions the same way. AUDIT_ACTIONS is the closed list of audit actions from spec §6; the
   audit filter offers exactly these. */
import type { MessageKey } from '../i18n';
import type { Role, UserStatus } from '../api/types';

export const ROLE_LABEL: Record<Role, MessageKey> = { admin: 'role.admin', approver: 'role.approver', member: 'role.member' };
export const ROLE_HINT: Record<Role, MessageKey> = { admin: 'role.admin.desc', approver: 'role.approver.desc', member: 'role.member.desc' };
export const ROLES: Role[] = ['member', 'approver', 'admin'];

export const STATUS_LABEL: Record<UserStatus, MessageKey> = { active: 'status.active', invited: 'status.invited', disabled: 'status.disabled' };

export const AUDIT_ACTIONS = [
  'auth.setup', 'auth.login', 'auth.login_failed', 'auth.throttled', 'auth.logout', 'auth.sso_login',
  'auth.invite_accepted', 'auth.password_changed', 'auth.reset_link_issued', 'session.revoked',
  'user.created', 'user.updated', 'user.disabled', 'user.enabled', 'user.promoted', 'user.invite_issued',
  'department.created', 'department.updated', 'department.archived', 'department.deleted',
  'org.updated', 'smtp.updated', 'smtp.tested', 'model.tested',
  'document.uploaded', 'document.deleted', 'document.reindexed', 'document.published',
  'conversation.deleted', 'chat.asked', 'message.feedback',
  'report.created', 'report.updated', 'report.deleted', 'report.run_started', 'report.run_succeeded',
  'report.run_failed', 'report.delivered',
  'approval.requested', 'approval.approved', 'approval.rejected', 'approval.cancelled', 'approval.expired',
  'approval.executed', 'approval.failed', 'email.sent', 'email.failed',
] as const;
