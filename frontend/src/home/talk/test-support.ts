/* Tests only: reach the re-laid composer (PHASE_B_PLAN.md §5.3) by its hooks, not by legacy
   classes. Controls outside the composer's fixed set sit in its Attach and Options menus, so a test
   opens the menu first (the §8.3 "open Options/Attach" step); the controls keep their names. */
import { fireEvent } from '@testing-library/react';

/** The composer's field (`data-composer`, a textarea since the re-lay). */
export function composerField(root: ParentNode = document): HTMLTextAreaElement {
  const field = root.querySelector<HTMLTextAreaElement>('[data-composer]');
  if (!field) throw new Error('no composer field ([data-composer]) is rendered');
  return field;
}

/** The composer's Send button (`data-composer-send`). */
export function composerSend(root: ParentNode = document): HTMLButtonElement {
  const send = root.querySelector<HTMLButtonElement>('[data-composer-send]');
  if (!send) throw new Error('no composer Send ([data-composer-send]) is rendered');
  return send;
}

/** Open the composer's Attach or Options menu (a reply's More: 'more'); already open stays open. */
export function openComposerMenu(menu: 'attach' | 'options' | 'more', root: ParentNode = document): HTMLElement {
  const holder = root.querySelector<HTMLElement>(`[data-talk-menu="${menu}"]`);
  const button = holder?.firstElementChild as HTMLButtonElement | null;
  if (!holder || !button) throw new Error(`no "${menu}" menu is rendered`);
  if (button.getAttribute('aria-expanded') !== 'true') fireEvent.click(button);
  return holder;
}
