import { expect, it } from 'vitest';
import { modelCalls } from '../model-call-provenance';

it('accepts only a bounded, distinct, fully attributed per-turn receipt', () => {
  const receipt = [{provider:'lm-studio',model:'qwen3/8b'}, {provider:'openai',model:'gpt-5.1'}];
  expect(modelCalls(receipt)).toEqual(receipt);
  for (const invalid of [undefined, [], [...receipt, ...Array(7).fill(receipt[0])],
    [receipt[0], receipt[0]], [{provider:'ollama',model:''}],
    [{provider:'openai',model:'x//y'}], [{provider:'openai',model:'bad name'}],
    [{provider:null,model:'known'}],
    [{provider:'ollama',model:'known',residency:'local'}]]) {
    expect(modelCalls(invalid)).toEqual([]);
  }
});
