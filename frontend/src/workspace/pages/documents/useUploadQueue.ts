/* The upload queue: files go up one at a time, each with its own progress and outcome.

   One at a time because the server extracts and indexes each file before answering (and
   rate-limits uploads per user): parallel uploads would only make every bar crawl. Each file
   keeps the destination chosen when it was added, so switching department mid-queue never
   moves a file. A file with an extension the server refuses fails at once, without a request.
   A rotated CSRF token (a sign-in in another tab) is refreshed and the file re-sent once, as
   the JSON client does for its own requests. Leaving the page aborts what is still in flight. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { hasAcceptedExtension, uploadDocument, type UploadTarget } from '../../api/documents';
import { isAbort, WorkspaceApiError } from '../../api/client';
import type { WorkspaceDocument } from '../../api/types';

export type UploadState = 'waiting' | 'uploading' | 'processing' | 'ready' | 'failed';

export interface UploadItem {
  key: string;
  name: string;
  size: number;
  state: UploadState;
  /** 0–100, bytes sent; meaningful while `uploading`. */
  percent: number;
  document: WorkspaceDocument | null;
  /** Why it failed: a request error, or the document's extraction error code. */
  error: unknown;
}

interface Pending { key: string; file: File; target: UploadTarget }

export interface UploadQueue {
  items: UploadItem[];
  busy: boolean;
  add: (files: File[], target: UploadTarget) => void;
  cancel: (key: string) => void;
  clearFinished: () => void;
}

function isCsrfFailure(err: unknown): boolean {
  return err instanceof WorkspaceApiError && err.code === 'csrf_failed';
}

/** *refreshSession* re-reads the session (and with it the CSRF token); it answers null when signed out. */
export function useUploadQueue(onFinished: (item: UploadItem) => void, refreshSession: () => Promise<unknown>): UploadQueue {
  const [items, setItems] = useState<UploadItem[]>([]);
  const pending = useRef<Pending[]>([]);
  const running = useRef(false);
  const current = useRef<{ key: string; controller: AbortController } | null>(null);
  const seq = useRef(0);
  const alive = useRef(true);
  const finishedRef = useRef(onFinished);
  finishedRef.current = onFinished;
  const refreshRef = useRef(refreshSession);
  refreshRef.current = refreshSession;

  const update = useCallback((key: string, change: Partial<UploadItem>) => {
    if (!alive.current) return;
    setItems((list) => list.map((item) => (item.key === key ? { ...item, ...change } : item)));
  }, []);

  const finish = useCallback((item: UploadItem) => {
    update(item.key, item);
    if (alive.current) finishedRef.current(item);
  }, [update]);

  const pump = useCallback(async () => {
    if (running.current) return;
    running.current = true;
    while (alive.current && pending.current.length > 0) {
      const next = pending.current.shift() as Pending;
      const controller = new AbortController();
      current.current = { key: next.key, controller };
      const base = { key: next.key, name: next.file.name, size: next.file.size, percent: 100 };
      const send = () => {
        update(next.key, { state: 'uploading', percent: 0 });
        return uploadDocument(next.file, next.target, {
          signal: controller.signal,
          onProgress: (loaded, total) => update(next.key, { percent: total > 0 ? Math.min(100, Math.round((loaded / total) * 100)) : 0 }),
          onSent: () => update(next.key, { state: 'processing', percent: 100 }),
        });
      };
      try {
        let document: WorkspaceDocument;
        try {
          document = await send();
        } catch (err) {
          if (!isCsrfFailure(err) || !(await refreshRef.current())) throw err;
          document = await send();
        }
        const ok = document.status !== 'failed';
        finish({ ...base, state: ok ? 'ready' : 'failed', document, error: ok ? null : document.error });
      } catch (err) {
        if (isAbort(err)) {
          if (alive.current) setItems((list) => list.filter((item) => item.key !== next.key));
        } else {
          finish({ ...base, state: 'failed', document: null, error: err });
        }
      } finally {
        current.current = null;
      }
    }
    running.current = false;
  }, [finish, update]);

  const add = useCallback((files: File[], target: UploadTarget) => {
    const added: UploadItem[] = [];
    for (const file of files) {
      seq.current += 1;
      const key = `u${seq.current}`;
      if (!hasAcceptedExtension(file.name)) {
        added.push({ key, name: file.name, size: file.size, state: 'failed', percent: 0, document: null, error: 'unsupported_file_type' });
        continue;
      }
      added.push({ key, name: file.name, size: file.size, state: 'waiting', percent: 0, document: null, error: null });
      pending.current.push({ key, file, target });
    }
    setItems((list) => [...list, ...added]);
    void pump();
  }, [pump]);

  const cancel = useCallback((key: string) => {
    if (current.current?.key === key) {
      current.current.controller.abort();
      return;
    }
    pending.current = pending.current.filter((p) => p.key !== key);
    setItems((list) => list.filter((item) => item.key !== key));
  }, []);

  const clearFinished = useCallback(() => {
    setItems((list) => list.filter((item) => item.state !== 'ready' && item.state !== 'failed'));
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      pending.current = [];
      current.current?.controller.abort();
    };
  }, []);

  const busy = items.some((item) => item.state === 'waiting' || item.state === 'uploading' || item.state === 'processing');
  return { items, busy, add, cancel, clearFinished };
}
