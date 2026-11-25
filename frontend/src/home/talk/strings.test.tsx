/* The conversation register's words are complete in both languages (frame/strings.ts), and the
   helpers that place them do not concatenate translated pieces. */
import React from 'react';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { stringProblems } from '../../frame/strings';
import { TALK_STRINGS, fill, lowerFirst, policyWord, talkStrings } from './strings';

describe('TALK_STRINGS', () => {
  it('is complete in English and Romanian', () => {
    expect(stringProblems(TALK_STRINGS)).toEqual([]);
  });

  it('writes Romanian with comma-below letters and real diacritics', () => {
    const ro = Object.values(TALK_STRINGS.ro).flatMap((value) => typeof value === 'string' ? [value] : [value.one, value.few, value.other]).join(' ');
    expect(ro).not.toMatch(/[şţŞŢ]/);
    expect(ro).toMatch(/ș/);
    expect(ro).toMatch(/ț/);
    expect(ro).toMatch(/ă/);
  });

  it('reads English for anything but ro', () => {
    expect(talkStrings('de').send).toBe('Send');
    expect(talkStrings('ro').send).toBe('Trimite');
  });

  it('says "checking the selected agent" in one sentence per language, the head starting it in lower case', () => {
    expect(talkStrings('en').recipientChecking).toBe('Checking the selected agent…');
    expect(talkStrings('ro').recipientChecking).toBe('Se verifică agentul selectat…');
    expect(lowerFirst(talkStrings('en').recipientChecking, 'en')).toBe('checking the selected agent…');
    expect(lowerFirst(talkStrings('ro').recipientChecking, 'ro')).toBe('se verifică agentul selectat…');
    expect(lowerFirst('Își', 'ro')).toBe('își');
    expect(lowerFirst('', 'en')).toBe('');
  });
});

describe('fill', () => {
  it('fills a whole sentence with nodes, so a name can be set in bold', () => {
    const { container } = render(<p>{fill('with {agent} today', { agent: <b>Jarvis</b> })}</p>);
    expect(container.innerHTML).toBe('<p>with <b>Jarvis</b> today</p>');
  });

  it('leaves a placeholder with no value visible', () => {
    const { container } = render(<p>{fill('asked {time} · {elapsed}', { time: '10:48' })}</p>);
    expect(container.textContent).toBe('asked 10:48 · {elapsed}');
  });
});

describe('policyWord', () => {
  it('words every declared routing policy and says when it is unknown', () => {
    const s = talkStrings('en');
    expect(['orchestrated', 'local', 'cloud_only', 'cloud_preferred', 'claude_preferred', 'auto', null, 'odd'].map((p) => policyWord(p, s)))
      .toEqual(['Orchestrated', 'Local', 'Cloud only', 'Cloud preferred', 'Claude preferred', 'Auto', 'Routing policy unknown', 'Routing policy unknown']);
    expect(policyWord('cloud_preferred', talkStrings('ro'))).toBe('Preferă cloud');
  });
});
