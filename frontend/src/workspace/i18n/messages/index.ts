/* All namespaces merged into one dictionary per language. A new area adds its namespace file
   and spreads it here in both languages; the English type is pinned to the Romanian keys, so
   a namespace missing from either side fails to compile. */
import { admin } from './admin';
import { approvals } from './approvals';
import { assistant } from './assistant';
import { auth } from './auth';
import { common } from './common';
import { documents } from './documents';
import { errors } from './errors';
import { profile } from './profile';
import { reports } from './reports';

export const RO = {
  ...common.ro, ...errors.ro, ...auth.ro, ...profile.ro, ...admin.ro,
  ...assistant.ro, ...documents.ro, ...reports.ro, ...approvals.ro,
};

export const EN: Record<keyof typeof RO, string> = {
  ...common.en, ...errors.en, ...auth.en, ...profile.en, ...admin.en,
  ...assistant.en, ...documents.en, ...reports.en, ...approvals.en,
};
