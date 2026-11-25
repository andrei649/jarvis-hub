import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { COMMON_STRINGS } from './common';
import { RECORD_TABLE_STRINGS } from './RecordTable';
import { TRUST_STRINGS } from './TrustOverview';
import { WORK_STRINGS } from './WorkOverview';
import { TIMELINE_STRINGS } from './Timeline';
import { GLANCE_STRINGS } from './Glance';
import { AGENTS_RECORD_STRINGS } from './AgentsRecordRegister';
import { ARTIFACTS_STRINGS } from './ArtifactsPage';

const TABLES = { COMMON_STRINGS, RECORD_TABLE_STRINGS, TRUST_STRINGS, WORK_STRINGS, TIMELINE_STRINGS, GLANCE_STRINGS, AGENTS_RECORD_STRINGS, ARTIFACTS_STRINGS };

describe('the pages\' strings are complete in English and Romanian', () => {
  it.each(Object.entries(TABLES))('%s', (_name, table) => {
    expect(stringProblems(table as any)).toEqual([]);
  });

  it('writes Romanian with the comma-below letters, in every table', () => {
    for (const table of Object.values(TABLES)) {
      expect(JSON.stringify((table as any).ro)).not.toMatch(/[ŞşŢţ]/);
    }
  });
});
