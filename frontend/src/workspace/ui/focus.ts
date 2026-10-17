/* Which elements can take keyboard focus inside a container — shared by the modal focus trap,
   the popover and the menu. Elements inside an inert subtree or hidden from assistive
   technology are skipped. */
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
