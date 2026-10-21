/* Where an answer or a report run was produced, in the words of the model popover — „Pe serverul
   companiei" / „La un furnizor cloud aprobat" — never the raw locality code (review UX-13). The
   model id itself is technical: the screens show it to admins only, next to this chip.

   The chip never wraps (UX-22). A table cell is narrow, so there it shows the short form — the
   top bar's own words, „Local" / „Cloud" — while the full words stay its accessible name (read
   instead of the short form, which is hidden from screen readers) and its tooltip; when the
   table stacks into cards on a phone, the card line has room and shows the full words again
   (features.css → .ws-locality__full). */
import React from 'react';
import type { Locality } from '../../api/types';
import { useI18n } from '../../i18n';

export function LocalityChip({ locality, short = false }: { locality: Locality | null | undefined; short?: boolean }) {
  const { t } = useI18n();
  if (!locality) return null;
  const words = t(`locality.${locality}`);
  return (
    <span className={`ws-locality ws-locality--${locality}`} title={words}>
      {short
        ? <><span className="ws-locality__text ws-locality__short" aria-hidden="true">{t(`locality.short.${locality}`)}</span><span className="ws-locality__full">{words}</span></>
        : <span className="ws-locality__text">{words}</span>}
    </span>
  );
}
