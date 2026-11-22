import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { ChatMode } from '../modes3';

const scene = '[gd_scene load_steps=2 format=3]\n\n[node name="Main" type="Node2D"]\n';
const script = 'extends Node\r\n\r\nfunc _ready():\r\n    print("Hello")\r\n';
const reply = (text: string) => ({ role: 'agent', who: 'jarvis', text, _turnId: 7, _complete: true });
const downloads: { name: string; blob: Blob }[] = [];
let createObjectURL: typeof URL.createObjectURL;
let revokeObjectURL: typeof URL.revokeObjectURL;

beforeEach(() => {
  downloads.length = 0;
  createObjectURL = URL.createObjectURL;
  revokeObjectURL = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn((blob: Blob) => {
    downloads.push({ name: '', blob });
    return `blob:godot-${downloads.length}`;
  });
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
    downloads[downloads.length - 1].name = this.download;
  });
});
afterEach(() => {
  cleanup();
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = revokeObjectURL;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const read = (blob: Blob): Promise<string> => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result));
  reader.onerror = () => reject(reader.error);
  reader.readAsText(blob, 'utf-8');
});

describe('Godot code blocks in completed Chat and Cockpit replies', () => {
  it('downloads separate native scene and script files from the actual fenced blocks, preserving indentation', async () => {
    const text = `Scene:\n\n\`\`\`tscn\n${scene}\`\`\`\n\nScript:\n\n\`\`\`gdscript\n${script}\`\`\`\n\n\`\`\`gd\nvar answer = 42\n\`\`\``;
    const fetch = vi.fn();
    vi.stubGlobal('fetch', fetch);
    const view = render(<Conversation messages={[reply(text)]} thinking={null} exportAllowed lang="en" />);
    const bubble = view.container.querySelector('.msg.agent .bubble')!;
    expect(bubble.querySelectorAll('pre code')).toHaveLength(3);
    expect(bubble.querySelectorAll('pre code')[1].textContent).toBe(script.replace(/\r\n/g, '\n').trimEnd());
    const buttons = [...bubble.querySelectorAll('button')];
    expect(buttons).toHaveLength(3);
    expect(buttons.map(button => button.getAttribute('aria-label'))).toEqual([
      'Download Godot scene (scene-2.tscn)',
      'Download Godot script (script-4.gd)',
      'Download Godot script (script-5.gd)',
    ]);
    buttons.forEach(button => fireEvent.click(button));
    expect(downloads.map(item => item.name)).toEqual(['scene-2.tscn', 'script-4.gd', 'script-5.gd']);
    expect(await Promise.all(downloads.map(item => read(item.blob)))).toEqual([scene, script, 'var answer = 42\n']);
    expect(downloads.every(item => item.blob.type === 'text/plain;charset=utf-8')).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
    await new Promise(resolve => setTimeout(resolve, 1100));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:godot-1');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:godot-2');
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:godot-3');
  });

  it('shows Romanian actions in focused Chat and hides them when demo or no selected owner turn', () => {
    const props = { messages: [reply(`\`\`\`gdscene\n${scene}\`\`\``)], thinking: null, lang: 'ro',
      t: { directLine: 'Chat', focusHintChat: '', channel: 'Chat', transmit: 'Trimite', placeholder: 'Mesaj' },
      agent: 'jarvis', sessionId: 's1', onSubmit: () => {} };
    const view = render(<ChatMode {...props} selectedTurn />);
    expect(screen.getByRole('button', { name: 'Descarcă scena Godot (scene-1.tscn)' })).toBeTruthy();
    view.rerender(<ChatMode {...props} selectedTurn demo />);
    expect(screen.queryByRole('button', { name: /Descarcă scena Godot/ })).toBeNull();
    view.rerender(<ChatMode {...props} selectedTurn={false} demo={false} />);
    expect(screen.queryByRole('button', { name: /Descarcă scena Godot/ })).toBeNull();
  });

  it('keeps triple markers inside a longer backtick or tilde fence as source text', async () => {
    const backticks = 'extends Node\nvar marker = """\n```\n"""\n';
    const tildes = 'extends Node\nvar marker = """\n~~~\n"""\n';
    const text = `\`\`\`\`gdscript\n${backticks}\`\`\`\`\n\n~~~~gd\n${tildes}~~~~`;
    const view = render(<Conversation messages={[reply(text)]} thinking={null} exportAllowed lang="en" />);
    const bubble = view.container.querySelector('.msg.agent .bubble')!;
    expect([...bubble.querySelectorAll('pre code')].map(node => node.textContent)).toEqual([backticks.trimEnd(), tildes.trimEnd()]);
    const buttons = [...bubble.querySelectorAll('button')];
    expect(buttons).toHaveLength(2);
    buttons.forEach(button => fireEvent.click(button));
    expect(await Promise.all(downloads.map(item => read(item.blob)))).toEqual([backticks, tildes]);
  });

  it('excludes prose, unknown or unlabeled fences, invalid scenes, comment-only scripts and unfinished replies', () => {
    const text = [
      'A Godot example in prose: [gd_scene load_steps=2 format=3]',
      '```\n' + scene + '```',
      '```python\nprint(1)\n```',
      '```tscn\n[node name="NoHeader" type="Node"]\n```',
      '```gdscene\n[gd_scene broken]\n```',
      '```gdscript\n# only a comment\n```',
      '```gd\n\n```',
      '```tscn\n[gd_scene broken',
    ].join('\n\n');
    const view = render(<Conversation messages={[{ role: 'user', text: `\`\`\`gd\npass\n\`\`\`` }, reply(text)]} thinking={null} exportAllowed />);
    expect(view.container.querySelectorAll('.msg.agent pre code')).toHaveLength(7);
    expect(screen.queryByRole('button', { name: /Download Godot/ })).toBeNull();
    const valid = reply(`\`\`\`gd\npass\n\`\`\``);
    view.rerender(<Conversation messages={[{ ...valid, who: 'system' }, { ...valid, _complete: false }, { ...valid, _turnId: undefined }]}
      thinking={{ label: 'thinking' }} exportAllowed />);
    expect(screen.queryByRole('button', { name: /Download Godot/ })).toBeNull();
    view.rerender(<Conversation messages={[valid]} thinking={null} exportAllowed={false} />);
    expect(screen.queryByRole('button', { name: /Download Godot/ })).toBeNull();
  });
});
