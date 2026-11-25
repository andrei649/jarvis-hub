import { expect, test } from '@jest/globals';
import { modelCalls } from '../modelCallProvenance';

test('projects only bounded, distinct, exact provider and model receipts', () => {
  const valid = [{ provider: 'lm-studio', model: 'qwen3/8b' }, { provider: 'openai', model: 'gpt-5.1' }];
  expect(modelCalls(valid)).toEqual(valid);
  expect(modelCalls(valid)).not.toBe(valid);
  for (const invalid of [undefined, [], Array(9).fill(valid[0]), [valid[0], valid[0]],
    [{ provider: 'openai', model: 'bad name' }], [{ provider: 'openai', model: 'x//y' }],
    [{ provider: 'ollama', model: '' }], [{ provider: null, model: 'known' }],
    [{ provider: 'ollama', model: 'known', residency: 'local' }]]) {
    expect(modelCalls(invalid)).toEqual([]);
  }
});
