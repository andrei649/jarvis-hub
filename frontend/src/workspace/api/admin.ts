/* Admin console endpoints (spec §7: S1 routers/workspace_admin.py, the S3 model test and the S4
   SMTP routes). Every route here requires an admin session; the server answers 403 otherwise. */
import { appUrl } from '../../base-path';
import { api, query } from './client';
import type {
  AdminDepartment, AdminUser, AdminUsersResponse, AuditFilters, AuditPage, AuditVerifyResult,
  CreateUserRequest, CreateUserResponse, DepartmentRequest, IssueInviteResponse, ModelTestResult, Org,
  OrgPatch, SmtpSettings, SmtpTestResult, SmtpUpdate, UpdateUserRequest, UsageStats,
} from './types';

/** Several admin routes answer either the bare object or `{<key>: object}`; accept both. */
function unwrap<T>(data: unknown, key: string): T {
  if (data && typeof data === 'object' && key in (data as Record<string, unknown>)) {
    return (data as Record<string, unknown>)[key] as T;
  }
  return data as T;
}

export const listUsers = async (): Promise<AdminUser[]> =>
  (await api.get<AdminUsersResponse>(appUrl('/api/workspace/admin/users')))?.users ?? [];
export const createUser = (body: CreateUserRequest) => api.post<CreateUserResponse>(appUrl('/api/workspace/admin/users'), body);
export const updateUser = async (id: number, body: UpdateUserRequest): Promise<AdminUser> =>
  unwrap<AdminUser>(await api.patch(appUrl(`/api/workspace/admin/users/${id}`), body), 'user');
export const issueInvite = (id: number, sendEmail: boolean) =>
  api.post<IssueInviteResponse>(appUrl(`/api/workspace/admin/users/${id}/invite`), { send_email: sendEmail });

export async function listAdminDepartments(): Promise<AdminDepartment[]> {
  const data = await api.get<AdminDepartment[] | { departments: AdminDepartment[] }>(appUrl('/api/workspace/admin/departments'));
  return Array.isArray(data) ? data : data?.departments ?? [];
}
export const createDepartment = async (body: DepartmentRequest): Promise<AdminDepartment> =>
  unwrap<AdminDepartment>(await api.post(appUrl('/api/workspace/admin/departments'), body), 'department');
export const updateDepartment = async (id: number, body: DepartmentRequest): Promise<AdminDepartment> =>
  unwrap<AdminDepartment>(await api.patch(appUrl(`/api/workspace/admin/departments/${id}`), body), 'department');
export const deleteDepartment = (id: number) => api.del(appUrl(`/api/workspace/admin/departments/${id}`));

export const getOrg = async (): Promise<Org> => unwrap<Org>(await api.get(appUrl('/api/workspace/admin/org')), 'org');
export const updateOrg = async (body: OrgPatch): Promise<Org> =>
  unwrap<Org>(await api.patch(appUrl('/api/workspace/admin/org'), body), 'org');

export const testModel = () => api.post<ModelTestResult>(appUrl('/api/workspace/admin/model/test'), {});

export const getSmtp = async (): Promise<SmtpSettings> => unwrap<SmtpSettings>(await api.get(appUrl('/api/workspace/admin/smtp')), 'smtp');
export const saveSmtp = async (body: SmtpUpdate): Promise<SmtpSettings> =>
  unwrap<SmtpSettings>(await api.put(appUrl('/api/workspace/admin/smtp'), body), 'smtp');
export const testSmtp = (to: string) => api.post<SmtpTestResult>(appUrl('/api/workspace/admin/smtp/test'), { to });

function auditQuery(filters: AuditFilters): string {
  return query({
    actor_id: filters.actor_id, action: filters.action, since: filters.since, until: filters.until,
    limit: filters.limit, before_id: filters.before_id,
  });
}
export const listAudit = (filters: AuditFilters) => api.get<AuditPage>(appUrl(`/api/workspace/admin/audit${auditQuery(filters)}`));
/** A plain link (the browser downloads the attachment with the session cookie). */
export const auditExportUrl = (filters: AuditFilters) =>
  appUrl(`/api/workspace/admin/audit/export${auditQuery({ ...filters, limit: undefined, before_id: undefined })}`);
export const verifyAudit = () => api.get<AuditVerifyResult>(appUrl('/api/workspace/admin/audit/verify'));

export const getUsage = (days: number) => api.get<UsageStats>(appUrl(`/api/workspace/admin/stats${query({ days })}`));
