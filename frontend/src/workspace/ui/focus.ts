/* Which elements can take keyboard focus inside a container — shared by the modal focus trap,
   the popover and the menu. Elements inside an inert subtree or hidden from assistive
   technology are skipped. */
import type React from 'react';
import { useEffect, useRef } from 'react';

const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])', 'select:not([disabled])',
  'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])', '[contenteditable="true"]',
].join(',');

export function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter((el) => !el.closest('[inert]') && el.getAttribute('aria-hidden') !== 'true');
}

/**
 * After a submit that failed validation (here or on the server), brings the first problem into
 * view and focus. Long forms in drawers and dialogs otherwise show the message below the fold,
 * and the person sees "nothing happened". A fieldset-level error (`.has-error`) focuses its
 * first control.
 */
export function focusFirstInvalid(root: HTMLElement | null): void {
  const target = root?.querySelector<HTMLElement>('[aria-invalid="true"], .has-error');
  if (!target) return;
  const control = target.matches('[aria-invalid="true"]') ? target : focusableWithin(target)[0];
  target.scrollIntoView?.({ block: 'center' });
  control?.focus({ preventScroll: true });
}

/** True for a non-empty error: a message string, or an object with at least one message. */
function hasErrors(errors: unknown): boolean {
  if (!errors) return false;
  if (typeof errors === 'string') return errors.length > 0;
  if (typeof errors === 'object') return Object.values(errors as Record<string, unknown>).some(Boolean);
  return false;
}

/**
 * A ref for a form whose failed submit moves focus to the first invalid field (WCAG 3.3.1 —
 * the error is then announced where the person is, instead of focus staying on the submit
 * button). Pass the form's error state (an object of messages or one message); every new
 * error state that has a message focuses the first `aria-invalid` control.
 */
export function useInvalidFocus<T extends HTMLElement = HTMLFormElement>(errors: unknown): React.RefObject<T | null> {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (hasErrors(errors)) focusFirstInvalid(ref.current);
  }, [errors]);
  return ref;
}
