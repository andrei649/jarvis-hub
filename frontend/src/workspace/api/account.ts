/* Session, sign-in and per-user endpoints (spec §7, S1 routers/workspace_auth.py), plus the two
   read-only feeds the app shell polls: the model posture and the approvals inbox count. */
import { appUrl } from '../../base-path';
import { api, query } from './client';
import type {
  ApprovalsResponse, AuthResult, Department, InviteAcceptRequest, InviteLookup, LoginRequest, MePatch,
  MeResponse, ModelPosture, NotificationsReadRequest, NotificationsResponse, PasswordChangeRequest,
  RevokeOthersResponse, SessionInfo, SessionsResponse, SetupRequest, UnreadCountResponse, WorkspaceUser,
} from './types';

/** Auth screens answer their own 401/403s (wrong password is not an expired session). */
const PUBLIC = { skipAuthRedirect: true } as const;

export const getSession = () => api.get<SessionInfo>(appUrl('/api/workspace/session'), PUBLIC);
export const setup = (body: SetupRequest) => api.post<AuthResult>(appUrl('/api/workspace/setup'), body, PUBLIC);
export const login = (body: LoginRequest) => api.post<AuthResult>(appUrl('/api/workspace/login'), body, PUBLIC);
export const loginSso = () => api.post<AuthResult>(appUrl('/api/workspace/login/sso'), {}, PUBLIC);
export const lookupInvite = (token: string) => api.post<InviteLookup>(appUrl('/api/workspace/invites/lookup'), { token }, PUBLIC);
export const acceptInvite = (body: InviteAcceptRequest) => api.post<AuthResult>(appUrl('/api/workspace/invites/accept'), body, PUBLIC);
export const logout = () => api.post<void>(appUrl('/api/workspace/logout'), {}, PUBLIC);

export const getMe = () => api.get<MeResponse>(appUrl('/api/workspace/me'));
export const updateMe = (body: MePatch) => api.patch<{ user: WorkspaceUser }>(appUrl('/api/workspace/me'), body);
export const changePassword = (body: PasswordChangeRequest) => api.post<void>(appUrl('/api/workspace/me/password'), body);
export const listMySessions = () => api.get<SessionsResponse>(appUrl('/api/workspace/me/sessions'));
export const revokeMySession = (id: string) => api.del(appUrl(`/api/workspace/me/sessions/${encodeURIComponent(id)}`));
export const revokeOtherSessions = () => api.post<RevokeOthersResponse>(appUrl('/api/workspace/me/sessions/revoke-others'), {});

/** The departments the caller may work in, with member and document counts. */
export async function listDepartments(): Promise<Department[]> {
  const data = await api.get<Department[] | { departments: Department[] }>(appUrl('/api/workspace/departments'));
  return Array.isArray(data) ? data : data?.departments ?? [];
}

export const listNotifications = (opts: { unread?: boolean; limit?: number } = {}) =>
  api.get<NotificationsResponse>(appUrl(`/api/workspace/notifications${query({ unread: opts.unread || undefined, limit: opts.limit })}`));
export const markNotificationsRead = (body: NotificationsReadRequest) => api.post<UnreadCountResponse>(appUrl('/api/workspace/notifications/read'), body);

export const getModelPosture = () => api.get<ModelPosture>(appUrl('/api/workspace/model'));

/** Only the inbox counter is used by the shell; the list itself belongs to the Approvals page. */
export async function pendingApprovalsCount(): Promise<number> {
  const data = await api.get<ApprovalsResponse>(appUrl('/api/workspace/approvals?box=inbox&status=pending'));
  return Number(data?.pending_inbox_count) || 0;
}
