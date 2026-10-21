/* Department knowledge base (spec §7, S2 routers/workspace_documents.py).

   Uploads are a raw-body POST per file (the server takes no multipart, spec §6) sent through
   XMLHttpRequest rather than fetch: only XHR reports upload progress, so the progress bar
   reflects bytes actually sent. The server extracts and indexes before it answers, so once the
   last byte is out the caller is told (`onSent`) and can say "processing" truthfully. */
import { appUrl } from '../../base-path';
import { api, getCsrfToken, query, reportSessionFailure, toApiError, WorkspaceApiError } from './client';
import { unwrapOne } from './shape';
import type { DocumentDetail, DocumentStatus, DocumentsResponse, WorkspaceDocument } from './types';

/** Where an upload lands: a department id, or the company-wide collection (admins only). */
export type UploadTarget = number | 'company';

export interface DocumentFilters {
  /** A department's documents, or `company` for the company-wide ones; all readable when absent. */
  departmentId?: number | 'company';
  q?: string;
  status?: DocumentStatus;
}

export async function listDocuments(filters: DocumentFilters = {}): Promise<WorkspaceDocument[]> {
  const data = await api.get<DocumentsResponse>(appUrl(`/api/workspace/documents${query({ department_id: filters.departmentId, q: filters.q, status: filters.status })}`));
  return data?.documents ?? [];
}

export const getDocument = async (id: number): Promise<DocumentDetail> =>
  unwrapOne<DocumentDetail>(await api.get(appUrl(`/api/workspace/documents/${id}`)), ['document']);

/** A plain link: the browser downloads the attachment with the session cookie. */
export const documentFileUrl = (id: number): string => appUrl(`/api/workspace/documents/${id}/file`);

export const deleteDocument = (id: number) => api.del(appUrl(`/api/workspace/documents/${id}`));

export const reindexDocument = async (id: number): Promise<WorkspaceDocument> =>
  unwrapOne<WorkspaceDocument>(await api.post(appUrl(`/api/workspace/documents/${id}/reindex`), {}), ['document']);

/** The extensions the server accepts (spec §6); anything else is refused before upload. */
export const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.xlsx', '.csv', '.txt', '.md'] as const;

export function hasAcceptedExtension(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

export interface UploadOptions {
  onProgress?: (loaded: number, total: number) => void;
  /** Every byte has left the browser; the server is now extracting and indexing. */
  onSent?: () => void;
  signal?: AbortSignal;
}

function abortError(): DOMException {
  return new DOMException('The upload was aborted.', 'AbortError');
}

async function xhrError(xhr: XMLHttpRequest): Promise<WorkspaceApiError> {
  const type = xhr.getResponseHeader('Content-Type') || '';
  const error = await toApiError(new Response(xhr.responseText || null, { status: xhr.status, headers: { 'Content-Type': type } }));
  reportSessionFailure(error);
  return error;
}

function parseDocument(xhr: XMLHttpRequest): WorkspaceDocument {
  try {
    return unwrapOne<WorkspaceDocument>(JSON.parse(xhr.responseText), ['document']);
  } catch {
    throw new WorkspaceApiError('invalid_response', '', xhr.status);
  }
}

/** Uploads one file; resolves with the stored document (ready, or failed with its `error`). */
export function uploadDocument(file: File, target: UploadTarget, opts: UploadOptions = {}): Promise<WorkspaceDocument> {
  return new Promise((resolve, reject) => {
    if (opts.signal?.aborted) { reject(abortError()); return; }
    const xhr = new XMLHttpRequest();
    xhr.open('POST', appUrl(`/api/workspace/documents${query({ department_id: target, filename: file.name })}`));
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    const csrf = getCsrfToken();
    if (csrf) xhr.setRequestHeader('X-CSRF-Token', csrf);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) opts.onProgress?.(event.loaded, event.total); };
    xhr.upload.onload = () => opts.onSent?.();
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(parseDocument(xhr)); } catch (err) { reject(err); }
      } else {
        xhrError(xhr).then(reject, reject);
      }
    };
    xhr.onerror = () => reject(new WorkspaceApiError('upload_interrupted', '', 0));
    xhr.onabort = () => reject(abortError());
    opts.signal?.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(file);
  });
}
