/* Why a document is not usable, in plain words. Extraction failures arrive as a stable code on
   the document (`invalid_file`, `encrypted_pdf`, `too_many_pages`, `no_text`, `timeout`,
   spec §6); request failures arrive as a server error. Both read the same in the upload list,
   the table and the preview drawer. */
import { describeError } from '../../app/errors';
import type { I18n } from '../../i18n';

export function documentErrorText(i18n: I18n, error: unknown): string {
  if (typeof error === 'string' && error) {
    const own = `documents.error.${error}`;
    if (i18n.has(own)) return i18n.t(own);
    const general = `error.${error}`;
    if (i18n.has(general)) return i18n.t(general);
    return i18n.t('documents.error.generic');
  }
  if (error === null || error === undefined) return i18n.t('documents.error.generic');
  return describeError(i18n, error);
}
