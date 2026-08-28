import { describe, expect, it } from '@jest/globals';
import { wallState } from '../wallState';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const vectorsPath = join(__dirname, '..', '..', '..', '..', 'tests', '_fixtures', 'wall_state_vectors.json');
const { cases } = JSON.parse(readFileSync(vectorsPath, 'utf8'));

describe('H18.25 — native wallState matches the browser contract', () => {
  it('reproduces every shared vector exactly', () => {
    for (const c of cases) {
      expect({ input: c.input, out: wallState(c.input) })
        .toEqual({ input: c.input, out: c.expected });
    }
  });

  it('an explicit voice error outranks every other signal', () => {
    expect(wallState({ voice: { status: 'listening', error: 'x' }, serverUp: true }))
      .toEqual({ word: 'voice error', tone: 'bad' });
  });

  it('never reports offline while work is actually running', () => {
    expect(wallState({ tasks: [{ state: 'running' }], serverUp: false }).word).toBe('working');
  });
});
