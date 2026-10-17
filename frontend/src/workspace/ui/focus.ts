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
