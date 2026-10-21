/* Reports, their runs and the company-shared feed (spec §7 and §9, S4 routers/workspace_reports.py).
   A run is queued (202) and executed in the background, so callers poll the run until it
   finishes; exports are plain links the browser downloads with the session cookie. */
import { appUrl } from '../../base-path';
import { api, query } from './client';
import { unwrapList, unwrapOne } from './shape';
import type { Report, ReportRequest, ReportRun, ReportRunDetail, ReportsResponse, RunsResponse, RunStartResponse } from './types';

export type ExportFormat = 'md' | 'html';

export async function listReports(departmentId: number): Promise<Report[]> {
  const data = await api.get<ReportsResponse>(appUrl(`/api/workspace/reports${query({ department_id: departmentId })}`));
  return data?.reports ?? [];
}

export const getReport = async (id: number): Promise<Report> =>
  unwrapOne<Report>(await api.get(appUrl(`/api/workspace/reports/${id}`)), ['report']);

export const createReport = async (body: ReportRequest): Promise<Report> =>
  unwrapOne<Report>(await api.post(appUrl('/api/workspace/reports'), body), ['report']);

export const updateReport = async (id: number, body: Partial<ReportRequest>): Promise<Report> =>
  unwrapOne<Report>(await api.patch(appUrl(`/api/workspace/reports/${id}`), body), ['report']);

export const deleteReport = (id: number) => api.del(appUrl(`/api/workspace/reports/${id}`));

export async function runReport(id: number): Promise<ReportRun> {
  const data = await api.post<RunStartResponse>(appUrl(`/api/workspace/reports/${id}/run`), {});
  return unwrapOne<ReportRun>(data, ['run']);
}

export async function listRuns(reportId: number): Promise<ReportRun[]> {
  const data = await api.get<RunsResponse>(appUrl(`/api/workspace/reports/${reportId}/runs`));
  return data?.runs ?? [];
}

export const getRun = async (runId: number): Promise<ReportRunDetail> =>
  unwrapOne<ReportRunDetail>(await api.get(appUrl(`/api/workspace/report-runs/${runId}`)), ['run']);

export function runExportUrl(runId: number, format: ExportFormat): string {
  return appUrl(`/api/workspace/report-runs/${runId}/export${query({ format })}`);
}

export async function listSharedReports(): Promise<ReportRunDetail[]> {
  return unwrapList<ReportRunDetail>(await api.get(appUrl('/api/workspace/shared-reports')), ['runs', 'items', 'reports']);
}
