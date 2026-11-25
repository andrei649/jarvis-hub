import { describe, expect, it } from 'vitest';
import { FRAME_STRING_TABLES } from './frame-strings';
import { stringProblems } from './strings';

describe('the frame\'s words', () => {
  it.each(Object.entries(FRAME_STRING_TABLES))('%s are complete in English and Romanian', (_name, table) => {
    expect(stringProblems(table)).toEqual([]);
  });

  it('never say "idle", "Sealed" or "All nominal"', () => {
    const all = JSON.stringify(Object.values(FRAME_STRING_TABLES));
    expect(all).not.toMatch(/\bidle\b|Sealed|nothing can leave|all nominal/i);
  });
});
