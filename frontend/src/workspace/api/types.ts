/* Wire types for every Nerva Workspace endpoint (docs/business/WORKSPACE_PILOT_SPEC.md §7).

   These mirror the server's JSON exactly: timestamps are UTC epoch seconds (numbers), ids are
   integers, and optional fields are optional because the server omits them, not because the UI
   guesses. Where the contract says only "+ counts" the count fields are optional. */

export type Locale = 'ro' | 'en';
export type Theme = 'light' | 'dark' | 'system';
export type Role = 'admin' | 'approver' | 'member';
export type UserStatus = 'invited' | 'active' | 'disabled';
export type ModelPolicy = 'local_only' | 'allow_cloud';
export type Locality = 'local' | 'cloud' | 'unknown';
export type EpochSeconds = number;

/** Error body every workspace route answers with on failure: `{error, message, ...extra}`. */
export interface ApiErrorBody {
  error: string;
  message?: string;
  [extra: string]: unknown;
}

// ---------------------------------------------------------------- identity

export interface WorkspaceUser {
  id: number;
  email: string;
  name: string;
  role: Role;
  status: UserStatus;
  locale: Locale;
  theme: Theme;
  department_ids: number[];
  permissions?: UserPermissions;
}

/** Capability flags the server derives from the role; `department_ids` = departments usable now. */
export interface UserPermissions {
  admin_console?: boolean;
  approve?: boolean;
  decide_admin_approvals?: boolean;
  upload_company?: boolean;
  department_ids?: number[];
}

/** Admin listing rows add login and invite bookkeeping to the user. */
export interface AdminUser extends WorkspaceUser {
  last_login_at: EpochSeconds | null;
  created_at?: EpochSeconds;
  pending_invite?: boolean | PendingInvite | null;
}

export interface PendingInvite {
  purpose?: InvitePurpose;
  expires_at?: EpochSeconds;
  created_at?: EpochSeconds;
}

export interface Org {
  id?: number;
  name: string;
  default_locale: Locale;
  model_policy: ModelPolicy;
  created_at?: EpochSeconds;
  settings?: Record<string, unknown>;
}

export interface Department {
  id: number;
  slug: string;
  name: string;
  description: string;
  member_count?: number;
  document_count?: number;
  /** Documents the assistant can cite (status ready); failed or processing ones are not counted. */
  ready_document_count?: number;
}

/** Admin listing rows include archived departments, the assistant brief and report counts. */
export interface AdminDepartment extends Department {
  assistant_instructions: string;
  archived: boolean | 0 | 1;
  created_at?: EpochSeconds;
  report_count?: number;
  conversation_count?: number;
}

// ---------------------------------------------------------------- auth

export interface SessionInfo {
  enabled: true;
  setup_required: boolean;
  sso_available: boolean;
  authenticated: boolean;
  user?: WorkspaceUser;
  org?: Org;
  csrf_token?: string;
  departments?: Department[];
}

/** What /setup, /login, /login/sso and /invites/accept answer. */
export interface AuthResult {
  user: WorkspaceUser;
  org: Org;
  csrf_token: string;
}

export interface SetupRequest {
  setup_code: string;
  org_name: string;
  name: string;
  email: string;
  password: string;
  locale: Locale;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export type InvitePurpose = 'invite' | 'reset';

export interface InviteLookup {
  email: string;
  name: string;
  org_name: string;
  purpose: InvitePurpose;
  expires_at: EpochSeconds;
}

export interface InviteAcceptRequest {
  token: string;
  password: string;
  name?: string;
}

export interface MeResponse {
  user: WorkspaceUser;
  org: Org;
  departments: Department[];
}

export interface MePatch {
  name?: string;
  locale?: Locale;
  theme?: Theme;
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export type SessionVia = 'password' | 'invite' | 'setup' | 'sso';

export interface ActiveSession {
  id: string;
  current: boolean;
  created_at: EpochSeconds;
  last_seen_at: EpochSeconds;
  ip: string;
  user_agent: string;
  via: SessionVia;
}

export interface SessionsResponse { sessions: ActiveSession[] }
export interface RevokeOthersResponse { revoked: number }

// ---------------------------------------------------------------- notifications

export interface Notification {
  id: number;
  kind: string;
  title: string;
  body: string;
  link: string;
  created_at: EpochSeconds;
  read_at: EpochSeconds | null;
}

export interface NotificationsResponse { items: Notification[]; unread_count: number }
export interface NotificationsReadRequest { ids?: number[]; all?: boolean }
export interface UnreadCountResponse { unread_count: number }

// ---------------------------------------------------------------- admin

export interface AdminUsersResponse { users: AdminUser[] }

export interface CreateUserRequest {
  email: string;
  name: string;
  role: Role;
  department_ids: number[];
  send_email?: boolean;
}

export interface CreateUserResponse {
  user: AdminUser;
  invite_url: string;
  emailed: boolean;
  email_error?: string;
}

export interface UpdateUserRequest {
  name?: string;
  role?: Role;
  department_ids?: number[];
  status?: 'active' | 'disabled';
}

export interface IssueInviteResponse {
  invite_url: string;
  purpose: InvitePurpose;
  emailed: boolean;
  /** An error code (e.g. `smtp_not_configured`, `smtp_failed`) when the email was not sent. */
  email_error?: string;
  expires_at?: EpochSeconds;
}

export interface DepartmentRequest {
  name?: string;
  description?: string;
  assistant_instructions?: string;
  archived?: boolean;
}

export interface OrgPatch {
  name?: string;
  default_locale?: Locale;
  model_policy?: ModelPolicy;
}

export interface AuditEntry {
  id: number;
  ts: EpochSeconds;
  actor_user_id: number | null;
  actor_email: string;
  actor_name?: string | null;
  action: string;
  target_type: string;
  target_id: string;
  department_id: number | null;
  ip: string;
  details?: Record<string, unknown>;
  hash?: string;
}

export interface AuditPage { items: AuditEntry[]; next_before_id: number | null }

export interface AuditFilters {
  actor_id?: number;
  action?: string;
  since?: EpochSeconds;
  until?: EpochSeconds;
  limit?: number;
  before_id?: number;
}

export interface AuditVerifyResult {
  ok: boolean;
  checked: number;
  broken_at: number | null;
  keyed: boolean;
  key_mismatch: boolean;
  /** Rows before the re-key in effect that a retired key signed: pinned, but not checkable
      (optional so an older server's answer still reads). */
  unverified?: number;
  /** The `audit.rekeyed` row in effect, or null when the trail was never re-keyed. */
  rekeyed_at?: number | null;
}

export interface UsageTotals {
  users: number;
  active_users_7d: number;
  documents: number;
  conversations: number;
  questions: number;
  reports: number;
  report_runs: number;
  approvals_pending: number;
  feedback_up: number;
  feedback_down: number;
}

/** Per-department usage rows; the department is named by id and/or name and/or slug. */
export interface UsageDepartmentRow {
  department_id?: number;
  id?: number;
  name?: string;
  slug?: string;
  [metric: string]: unknown;
}

export interface UsageDay { date: string; questions: number; report_runs: number }

export interface UsageStats {
  days?: number;
  since?: EpochSeconds;
  /** The IANA zone whose calendar days `daily` counts (the `tz` asked for, else Europe/Bucharest). */
  timezone?: string;
  totals: UsageTotals;
  per_department: UsageDepartmentRow[];
  daily: UsageDay[];
}

// ---------------------------------------------------------------- model

export interface ModelPosture {
  available: boolean;
  backend: string | null;
  model: string | null;
  route: string | null;
  locality: Locality | null;
  policy: ModelPolicy;
  reason: string | null;
  guardrails_mode: string | null;
}

export interface ModelTestResult {
  ok: boolean;
  latency_ms: number | null;
  model: string | null;
  locality: Locality | null;
  route: string | null;
  /** A failure code (model_unavailable, model_timeout, …) with the model `reason` when known. */
  error?: string;
  reason?: string;
}

// ---------------------------------------------------------------- email (SMTP)

export type SmtpSecurity = 'starttls' | 'ssl' | 'none';

export interface SmtpSettings {
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string;
  from_address: string;
  from_name: string;
  allowed_domains: string[];
  has_password: boolean;
  configured?: boolean;
}

/** `password: null` keeps the stored secret, `""` clears it, any other string replaces it. */
export interface SmtpUpdate {
  host: string;
  port: number;
  security: SmtpSecurity;
  username: string;
  password: string | null;
  from_address: string;
  from_name: string;
  allowed_domains: string[];
}

/** `error` is a code (smtp_failed, smtp_not_configured, …); `reason` the mail server's cause. */
export interface SmtpTestResult { ok: boolean; error?: string; reason?: string }

// ---------------------------------------------------------------- documents (S2)

export type DocumentStatus = 'processing' | 'ready' | 'failed';
export type DocumentVisibility = 'department' | 'company';

export interface WorkspaceDocument {
  id: number;
  title: string;
  filename: string;
  mime: string;
  size_bytes: number;
  department_id: number | null;
  visibility: DocumentVisibility;
  status: DocumentStatus;
  error: string | null;
  page_count: number | null;
  chunk_count: number;
  uploader: { id: number; name: string } | null;
  created_at: EpochSeconds;
  can_delete: boolean;
  can_reindex: boolean;
  can_publish: boolean;
  /** The department's name (null for company-wide documents stored without one). */
  department_name?: string | null;
  /** A request to publish it company-wide is waiting for an admin. */
  publish_pending?: boolean;
}

export interface DocumentDetail extends WorkspaceDocument { preview: string }
export interface DocumentsResponse { documents: WorkspaceDocument[] }

// ---------------------------------------------------------------- assistant (S3)

export interface Citation {
  n: number;
  document_id: number;
  title: string;
  chunk_id: number;
  page: number | null;
  excerpt: string;
  /** Whether the reader may open the document itself, judged when the run or the conversation
      is read (false for another department's document in a company-shared run, or one deleted
      or moved since). Absent on the live `sources` event, whose passages were just retrieved
      in the reader's own scope. */
  can_open?: boolean;
}

export interface ConversationSummary {
  id: number;
  title: string;
  department_id: number;
  updated_at: EpochSeconds;
  message_count: number;
}

export interface Conversation {
  id: number;
  title: string;
  department_id: number;
  created_at?: EpochSeconds;
  updated_at: EpochSeconds;
}

export type MessageStatus = 'pending' | 'complete' | 'error';

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  status: MessageStatus;
  error_code: string | null;
  model: string | null;
  locality: Locality | null;
  latency_ms: number | null;
  feedback: number | null;
  created_at: EpochSeconds;
}

export interface ConversationsResponse { conversations: ConversationSummary[] }
export interface ConversationDetail { conversation: Conversation; messages: ChatMessage[] }
export interface SendMessageResponse { user_message: ChatMessage; assistant_message: ChatMessage }
export interface FeedbackRequest { value: 1 | -1 | 0; note?: string }

/** Server-sent events of POST /conversations/{id}/messages (spec §8). */
export interface ChatStreamEvents {
  start: { user_message: ChatMessage; assistant_message_id: number };
  sources: { citations: Citation[] };
  token: { t: string };
  done: { assistant_message: ChatMessage };
  /** `reason` names the model problem for model_unavailable / model_policy_blocked. */
  error: { error: string; message?: string; reason?: string };
}

// ---------------------------------------------------------------- reports (S4)

export type ScheduleKind = 'manual' | 'daily' | 'weekly';
export type DeliveryStatus = 'none' | 'pending' | 'approved' | 'rejected';
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface ReportSchedule {
  kind: ScheduleKind;
  time?: string | null;
  weekday?: number | null;
  timezone?: string;
}

export interface Report {
  id: number;
  department_id: number;
  name: string;
  instructions: string;
  document_ids: number[];
  schedule_kind: ScheduleKind;
  schedule_time: string | null;
  schedule_weekday: number | null;
  timezone: string;
  delivery_emails: string[];
  delivery_status: DeliveryStatus;
  delivery_approved?: string[];
  owner_id: number | null;
  active: boolean | 0 | 1;
  next_run_at: EpochSeconds | null;
  last_run_at: EpochSeconds | null;
  created_at: EpochSeconds;
  updated_at: EpochSeconds;
  last_run?: { id: number; status: RunStatus; finished_at: EpochSeconds | null } | null;
  can_edit?: boolean;
  can_run?: boolean;
}

export interface ReportRequest {
  department_id: number;
  name: string;
  instructions: string;
  document_ids?: number[];
  schedule: ReportSchedule;
  delivery_emails?: string[];
}

export interface ReportRun {
  id: number;
  report_id: number;
  status: RunStatus;
  trigger: 'manual' | 'schedule';
  triggered_by: number | null;
  model: string | null;
  route: string | null;
  locality: Locality | null;
  error_code: string | null;
  error: string | null;
  shared_company: boolean | 0 | 1;
  delivered_to: string[];
  started_at: EpochSeconds | null;
  finished_at: EpochSeconds | null;
  created_at: EpochSeconds;
}

export interface ReportRunDetail extends ReportRun {
  content_md: string | null;
  citations: Citation[];
  can_share: boolean;
  /** A request to share this run company-wide is waiting for its decision. */
  share_pending?: boolean;
  can_email: boolean;
  report?: Pick<Report, 'id' | 'name' | 'department_id'>;
  /** Flat alternatives to `report` that list rows (shared reports) may carry instead. */
  report_name?: string;
  department_id?: number;
  /** The report's department by name, sent for every run: a company-shared run is read by
      people outside that department, whose own department list cannot name it. */
  department_name?: string | null;
}

export interface ReportsResponse { reports: Report[] }
export interface RunsResponse { runs: ReportRun[] }
export interface RunStartResponse { run: ReportRun }
export interface SharedReportsResponse { runs?: ReportRunDetail[]; items?: ReportRunDetail[] }

// ---------------------------------------------------------------- approvals (S4)

export type ApprovalStatus = 'pending' | 'executing' | 'approved' | 'rejected' | 'cancelled' | 'expired' | 'failed';
export type ApprovalBox = 'inbox' | 'mine' | 'all';

export interface ApprovalPerson { id: number; name: string; email?: string }

export interface Approval {
  id: number;
  kind: string;
  department_id: number | null;
  /** The server's name for the department (also for one the viewer does not belong to). */
  department_name?: string | null;
  summary: string;
  payload: Record<string, unknown>;
  status: ApprovalStatus;
  requester: ApprovalPerson;
  decider?: ApprovalPerson | null;
  decided_at: EpochSeconds | null;
  decision_note: string | null;
  result?: Record<string, unknown> | null;
  error_code: string | null;
  created_at: EpochSeconds;
  expires_at: EpochSeconds;
  can_decide: boolean;
  can_cancel: boolean;
  eligible_deciders?: ApprovalPerson[];
}

export interface ApprovalsResponse { items: Approval[]; pending_inbox_count: number }
/**
 * `smtp_configured` lets a non-admin screen hide an email action that could not be delivered;
 * `immediate`: the caller is an admin and the kind is admin-decided, so it executes at once.
 */
export interface EligibleResponse { count: number; immediate?: boolean; smtp_configured?: boolean }
export interface ApprovalRequest { kind: string; payload: Record<string, unknown> }
export interface DecisionRequest { decision: 'approve' | 'reject'; note?: string }
