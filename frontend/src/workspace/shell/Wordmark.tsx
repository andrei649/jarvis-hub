/* The "Nerva Workspace" wordmark; the public screens add the "by Digitaholic" line. */
import React from 'react';
import { useI18n } from '../i18n';
import { BrandMark } from '../ui';

export function Wordmark({ subline = false }: { subline?: boolean }) {
  const { t } = useI18n();
  return (
    <span className="ws-wordmark">
      <BrandMark size={28} />
      <span className="ws-wordmark__text">
        <span className="ws-wordmark__name">Nerva <span className="ws-wordmark__product">Workspace</span></span>
        {subline && <span className="ws-wordmark__sub">{t('brand.byline')}</span>}
      </span>
    </span>
  );
}
