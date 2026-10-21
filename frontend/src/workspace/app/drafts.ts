/* Unsent drafts that survive the session ending under the user (functional-F3).

   When the server ends a session (revoked from another tab, a role change, an expired cookie)
   the next request answers 401 and the app shows the sign-in screen, unmounting the page — and
   with it a long question in the composer or a half-written report. Drafts are therefore
   mirrored into sessionStorage (this tab only) under the user's id and a key naming the form,
   and read back when the same user's page mounts again after signing in.

   A draft is dropped when it is sent or saved, when the person cancels the form, and on a
   deliberate sign-out (a shared computer must not show the last person's text). Storage can be
   blocked: every access is guarded and a miss means "no draft".

   `useRestoredDraft` + `useDraftMirror` give any other dialog or form the same behaviour (F3,
   QA round 3): the email request, the admin's invite and edit-user dialogs, the department
   drawer, the organisation and SMTP forms. A form never mirrors a secret: the SMTP password
   is left out of its draft. */
import { useCallback, useEffect, useRef, useState } from 'react';

const PREFIX = 'nerva.workspace.draft.';

function storageKey(userId: number, key: string): string {
  return `${PREFIX}${userId}.${key}`;
}

export function readDraft<T>(userId: number, key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(storageKey(userId, key));
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

/** Stores *value*; an empty value (null, '' or an object of empty strings) removes the draft. */
export function writeDraft(userId: number, key: string, value: unknown): void {
  const empty = value === null || value === '' || (typeof value === 'object' && value !== null
    && Object.values(value as Record<string, unknown>).every((v) => v === '' || v === null || (Array.isArray(v) && v.length === 0)));
  try {
    if (empty) window.sessionStorage.removeItem(storageKey(userId, key));
    else window.sessionStorage.setItem(storageKey(userId, key), JSON.stringify(value));
  } catch {
    // Storage blocked or full: the draft just is not kept.
  }
}

export function clearDraft(userId: number, key: string): void {
  writeDraft(userId, key, null);
}

/** Every draft of every user in this tab (a deliberate sign-out). */
export function clearAllDrafts(): void {
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      if (key && key.startsWith(PREFIX)) keys.push(key);
    }
    for (const key of keys) window.sessionStorage.removeItem(key);
  } catch {
    // Nothing stored, or storage blocked.
  }
}

/** A restored draft's field, when it has the expected type (storage is the person's to edit). */
export function draftText(value: unknown, fallback: string): string {
  return typeof value === 'string' ? value : fallback;
}

/** A restored list of ids, kept only when every entry is a positive integer. */
export function draftIds(value: unknown, fallback: number[]): number[] {
  return Array.isArray(value) && value.every((v) => Number.isInteger(v) && v > 0) ? (value as number[]) : fallback;
}

/** The draft stored under *key* when the form mounted (read once), or null. Its values replace
    the ones the form would otherwise be prefilled with. */
export function useRestoredDraft<T>(userId: number, key: string): T | null {
  const [restored] = useState<T | null>(() => readDraft<T>(userId, key));
  return restored;
}

/** Mirrors *value* into the tab's draft store under *key* while the form differs from what it
    was prefilled with (*pristine* false); an unchanged form keeps no draft. Returns the function
    that drops the draft — call it when the form is sent, saved or cancelled. After that nothing
    is written again until the value changes, so a form still on screen after a save does not
    bring its draft back. */
export function useDraftMirror<T>(userId: number, key: string, value: T, pristine: boolean): () => void {
  const serialized = JSON.stringify(value);
  const clearedAt = useRef<string | null>(null);
  useEffect(() => {
    if (clearedAt.current !== null) {
      if (clearedAt.current === serialized) return;
      clearedAt.current = null;
    }
    if (pristine) clearDraft(userId, key);
    else writeDraft(userId, key, JSON.parse(serialized) as unknown);
  }, [userId, key, serialized, pristine]);
  return useCallback(() => {
    clearedAt.current = serialized;
    clearDraft(userId, key);
  }, [userId, key, serialized]);
}
