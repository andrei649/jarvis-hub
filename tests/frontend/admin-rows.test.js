// Admin settings form rows (admin.js). Prop-driven controls with onChange
// callbacks — the building blocks of the Admin HUD settings panel.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  // i18n first (TagInputRow uses _t for its placeholder), then components, then admin.
  env = loadHud({
    files: ['i18n', 'data', 'components', 'admin'],
    expose: ['ToggleRow', 'InputRow', 'SelectRow', 'SliderRow', 'TagInputRow', 'ButtonRow', 'InfoRow', 'Group'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('ToggleRow', () => {
  it('reflects the value on the checkbox and fires onChange', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.ToggleRow, { label: 'Recall', value: false, onChange }));
    const box = container.querySelector('input[type=checkbox]');
    expect(box.checked).toBe(false);
    expect(container.querySelector('.admin-row-label').textContent).toBe('Recall');
    env.toggle(box);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe('InputRow', () => {
  it('passes text values through unchanged', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.InputRow, { label: 'Name', value: '', onChange }));
    env.type(container.querySelector('input'), 'hello');
    expect(onChange).toHaveBeenCalledWith('hello');
  });

  it('coerces number inputs to Number', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.InputRow, { label: 'Port', value: 0, kind: 'number', onChange }));
    const input = container.querySelector('input');
    expect(input.type).toBe('number');
    env.type(input, '8080');
    expect(onChange).toHaveBeenCalledWith(8080);
  });
});

describe('SelectRow', () => {
  it('renders all options and reports the picked value', () => {
    const onChange = vi.fn();
    const { container } = env.render(
      h(env.hud.SelectRow, { label: 'Mode', value: 'a', opts: ['a', 'b', 'c'], onChange }),
    );
    expect(container.querySelectorAll('option')).toHaveLength(3);
    env.selectOption(container.querySelector('select'), 'b');
    expect(onChange).toHaveBeenCalledWith('b');
  });
});

describe('SliderRow', () => {
  it('shows the current value and emits a numeric change', () => {
    const onChange = vi.fn();
    const { container } = env.render(
      h(env.hud.SliderRow, { label: 'Temp', value: 0.5, min: 0, max: 1, step: 0.1, onChange }),
    );
    expect(container.querySelector('.admin-slider-value').textContent).toBe('0.5');
    env.type(container.querySelector('input[type=range]'), '0.8');
    expect(onChange).toHaveBeenCalledWith(0.8);
  });
});

describe('TagInputRow', () => {
  it('renders existing tags', () => {
    const { container } = env.render(
      h(env.hud.TagInputRow, { label: 'Local', value: ['pepper', 'frigga'], onChange: vi.fn() }),
    );
    const tags = [...container.querySelectorAll('.admin-tag')].map((t) => t.textContent.replace('×', ''));
    expect(tags).toEqual(['pepper', 'frigga']);
  });

  it('adds a normalized tag on Enter', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.TagInputRow, { label: 'Local', value: ['a'], onChange }));
    const input = container.querySelector('.admin-tag-input');
    env.type(input, '  Beta  ');
    env.keyDown(input, 'Enter');
    expect(onChange).toHaveBeenCalledWith(['a', 'beta']);
  });

  it('does not add duplicate tags', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.TagInputRow, { label: 'Local', value: ['a'], onChange }));
    const input = container.querySelector('.admin-tag-input');
    env.type(input, 'a');
    env.keyDown(input, 'Enter');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('removes the last tag on Backspace with an empty draft', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.TagInputRow, { label: 'Local', value: ['a', 'b'], onChange }));
    env.keyDown(container.querySelector('.admin-tag-input'), 'Backspace');
    expect(onChange).toHaveBeenCalledWith(['a']);
  });
});

describe('ButtonRow', () => {
  it('fires onClick and applies the variant class', () => {
    const onClick = vi.fn();
    const { container } = env.render(
      h(env.hud.ButtonRow, { label: 'Danger', buttonLabel: 'Wipe', variant: 'danger', onClick }),
    );
    const btn = container.querySelector('button');
    expect(btn.className).toContain('is-danger');
    expect(btn.textContent).toBe('Wipe');
    env.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('InfoRow', () => {
  it('stringifies the value', () => {
    const { container } = env.render(h(env.hud.InfoRow, { label: 'Build', value: 123 }));
    expect(container.querySelector('.admin-row-control').textContent).toBe('123');
  });
});

describe('Group', () => {
  it('renders a titled group with children', () => {
    const { container } = env.render(h(env.hud.Group, { title: 'CORE' }, h('div', { className: 'kid' }, 'x')));
    expect(container.querySelector('.admin-group-header').textContent).toBe('CORE');
    expect(container.querySelector('.kid')).not.toBeNull();
  });

  it('renders nothing when all children are falsy', () => {
    const { container } = env.render(h(env.hud.Group, { title: 'EMPTY' }, [null, false, undefined]));
    expect(container.querySelector('.admin-group')).toBeNull();
  });
});
