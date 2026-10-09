import { beforeEach, describe, expect, it, jest } from '@jest/globals';

const mockValues = new Map<string, string>();
jest.mock('@react-native-async-storage/async-storage', () => ({
  getItem: async (key: string) => mockValues.get(key) ?? null,
  setItem: async (key: string, value: string) => { mockValues.set(key, value); },
  removeItem: async (key: string) => { mockValues.delete(key); },
}));

import { loadGeneratedImageTask, saveGeneratedImageTask } from '../generatedImageTask';

beforeEach(() => mockValues.clear());

describe('scoped latest generated image task', () => {
  it('preserves exact prompt and task across tab remount without credentials or bytes', async () => {
    const record = { kind: 'task' as const, taskId: 42, prompt: '  amber moon  ' };
    await saveGeneratedImageTask('scope-one', record);
    await expect(loadGeneratedImageTask('scope-one')).resolves.toEqual(record);
    await expect(loadGeneratedImageTask('scope-two')).resolves.toBeNull();
    const raw = [...mockValues.values()].join('');
    expect(raw).not.toContain('user-secret');
    expect(raw).not.toContain('iVBOR');
  });

  it('retains unknown submission delivery and refuses malformed records', async () => {
    await saveGeneratedImageTask('scope-one', { kind: 'unknown', prompt: 'moon' });
    await expect(loadGeneratedImageTask('scope-one')).resolves.toEqual({ kind: 'unknown', prompt: 'moon' });
    mockValues.set('jarvis.generated-image.scope-one', JSON.stringify({ kind: 'task', taskId: '42', prompt: 'moon', token: 'leak' }));
    await expect(loadGeneratedImageTask('scope-one')).resolves.toBeNull();
  });

  it('round trips a maximum length prompt with JSON escaping', async () => {
    const prompt = '\\"\n'.repeat(1000) + '\t'.repeat(1000);
    expect(prompt).toHaveLength(4000);
    await saveGeneratedImageTask('scope-one', { kind: 'unknown', prompt });
    await expect(loadGeneratedImageTask('scope-one')).resolves.toEqual({ kind: 'unknown', prompt });
  });
});
