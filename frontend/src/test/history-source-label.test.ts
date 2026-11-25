import { expect, it } from 'vitest';
import { visibleTurns } from '../app';

it('shows only a valid native user history source on restored chat turns', () => {
  const base = { role: 'user', content: 'What now?', timestamp: '2026-11-22T10:00:00Z' };
  const history_source = { session_id: 'source-7', turn: 4, revision: 'a'.repeat(64), role: 'assistant' };
  const rows = visibleTurns([
    { ...base, history_source },
    { ...base, history_source: { ...history_source, revision: 'invalid' } },
    { ...base, history_source, foreign_origin: 'import' },
    { ...base, history_source: { ...history_source, role: 'system' } },
  ]);
  expect(rows[0].attachmentNames).toEqual(['Chat source: source-7 · message 5 · assistant']);
  expect(rows.slice(1).every(row => !('attachmentNames' in row))).toBe(true);
  expect(rows.every(row => row.text === 'What now?')).toBe(true);
});
