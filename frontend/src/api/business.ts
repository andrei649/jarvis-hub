import { apiDelete, apiGet, apiPost, apiPut } from './client';

export type Workspace = { name: string; industry: string; currency: string; local_only: boolean };
export type Template = { id: string; name: string; description: string; departments: string[] };
export type Connector = { id: string; name: string; description: string; category: string; auth_fields: { key: string; label: string; secret: boolean }[]; base_url_required: boolean };
export type Workflow = { id: string; name: string; description: string; requires: string };
export type Connection = { id: string; provider: string; name: string; base_url: string; status: string; last_sync_at: string | null; error: string | null; record_count: number | Record<string, number> | null };
export type ReportCoverage = { source: string; synced_at: string | null; description: string; complete: boolean };
export type Report = { id: string; workflow_id: string; title: string; summary: string; metrics: Record<string, unknown>; rows: Record<string, unknown>[]; coverage: ReportCoverage[]; warnings: string[]; created_at: string; filters?: { start_date: string | null; end_date: string | null }; source_selection?: { connection_id: string | null } };
export type Activity = { id?: string; action?: string; label?: string; message?: string; created_at?: string; at?: string };
export type BusinessCatalog = { enabled: boolean; templates: Template[]; connectors: Connector[]; workflows: Workflow[] };
export type BusinessState = { enabled: boolean; workspace: Workspace; connections: Connection[]; reports: Report[]; activity: Activity[] };
export type Answer = { answer: string; model: string; route: string };

export const getBusinessCatalog = () => apiGet<BusinessCatalog>(`/api/business/catalog`);
export const getBusinessWorkspace = () => apiGet<BusinessState>(`/api/business/workspace`);
export const saveBusinessWorkspace = (workspace: Workspace) => apiPut<{ workspace: Workspace }>(`/api/business/workspace`, workspace, { admin: true });
export const addBusinessConnection = (body: { provider: string; name: string; base_url: string; credentials: Record<string, string> }) =>
  apiPost<{ connection: Connection }>(`/api/business/connections`, body, { admin: true });
export const syncBusinessConnection = (id: string) =>
  apiPost<{ connection: Connection }>(`/api/business/connections/${encodeURIComponent(id)}/sync`, {}, { admin: true });
export const deleteBusinessConnection = (id: string) =>
  apiDelete<{ ok: boolean }>(`/api/business/connections/${encodeURIComponent(id)}`, { admin: true });
export const importBusinessCsv = (body: { name: string; kind: string; csv_text: string }) =>
  apiPost<{ connection: Connection }>(`/api/business/import`, body, { admin: true });
export const runBusinessReport = (workflowId: string, filters: { connection_id?: string; start_date?: string; end_date?: string } = {}) =>
  apiPost<{ report: Report }>(`/api/business/reports/${encodeURIComponent(workflowId)}/run`, filters);
export const askBusiness = (question: string, reportId?: string) => apiPost<Answer>(`/api/business/ask`, { question, ...(reportId ? { report_id: reportId } : {}) });
