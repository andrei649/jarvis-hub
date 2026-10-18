/* Where an answer or a report run was produced, in the words of the model popover — „Pe serverul
   companiei" / „La un furnizor cloud aprobat" — never the raw locality code (review UX-13). The
   model id itself is technical: the screens show it to admins only, next to this chip. */
import React from 'react';
import type { Locality } from '../../api/types';
import { useI18n } from '../../i18n';

export function LocalityChip({ locality }: { locality: Locality | null | undefined }) {
  const { t } = useI18n();
  if (!locality) return null;
  return <span className={`ws-locality ws-locality--${locality}`}>{t(`locality.${locality}`)}</span>;
}
