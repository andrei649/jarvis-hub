// Remaining components.js building blocks: badges, system rows/meters, the
// input bar, ambient cards, messages and the top bar.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components'],
    expose: ['Badge', 'SysRow', 'SysMeter', 'InputBar', 'WeatherCard', 'CalendarCard', 'Message', 'ThinkingBubble', 'TopBar'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('Badge', () => {
  it('renders label, value and a kind class', () => {
    const { container } = env.render(h(env.hud.Badge, { label: 'Voice', value: 'IDLE', kind: 'dim' }));
    expect(container.querySelector('.badge').className).toContain('badge-dim');
    expect(container.querySelector('.badge-label').textContent).toBe('Voice');
    expect(container.querySelector('.badge-value').textContent).toBe('IDLE');
  });
});

describe('SysRow', () => {
  it('renders a key/value pair and toggles the mono class', () => {
    const { container } = env.render(h(env.hud.SysRow, { label: 'HOST', value: 'bonobo', mono: true }));
    expect(container.querySelector('.sys-key').textContent).toBe('HOST');
    expect(container.querySelector('.sys-val').className).toContain('is-mono');
  });
});

describe('SysMeter', () => {
  it('computes percentage from used/total', () => {
    const { container } = env.render(h(env.hud.SysMeter, { label: 'RAM', used: 48, total: 192, unit: 'GB' }));
    expect(container.querySelector('.sys-bar-fill').style.width).toBe('25%');
    expect(container.querySelector('.sys-meter-head').textContent).toContain('48/192 GB');
  });
  it('uses raw values directly when raw=true', () => {
    const { container } = env.render(h(env.hud.SysMeter, { label: 'GPU', used: 70, total: 100, unit: '%', raw: true }));
    expect(container.querySelector('.sys-bar-fill').style.width).toBe('70%');
    expect(container.querySelector('.sys-meter-head').textContent).toContain('70%');
  });
});

describe('InputBar', () => {
  const base = { value: '', onChange: () => {}, onSubmit: () => {}, mic: false, onMicToggle: () => {}, activeAgent: 'jarvis', disabled: false };

  it('reports typing through onChange', () => {
    const onChange = vi.fn();
    const { container } = env.render(h(env.hud.InputBar, { ...base, onChange }));
    env.type(container.querySelector('.input-field'), 'hi');
    expect(onChange).toHaveBeenCalledWith('hi');
  });

  it('submits on Enter and on the send button', () => {
    const onSubmit = vi.fn();
    const { container } = env.render(h(env.hud.InputBar, { ...base, onSubmit }));
    env.keyDown(container.querySelector('.input-field'), 'Enter');
    env.click(container.querySelector('.input-send'));
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it('disables the field and buttons when disabled', () => {
    const { container } = env.render(h(env.hud.InputBar, { ...base, disabled: true }));
    expect(container.querySelector('.input-field').disabled).toBe(true);
    expect(container.querySelector('.input-send').disabled).toBe(true);
  });

  it('shows the active channel for the agent', () => {
    const { container } = env.render(h(env.hud.InputBar, { ...base, activeAgent: 'gecko' }));
    expect(container.querySelector('.input-channel').textContent).toContain('GECKO');
  });
});

describe('WeatherCard', () => {
  const data = {
    city: 'cluj', temp: 21, desc: 'Senin', wind: '5km/h', humidity: '40%', feels: 20, updated: '12:00',
    forecast: [{ hr: '13', t: 22, code: 'cloud' }, { hr: '14', t: 23, code: 'rain' }],
  };
  it('renders temperature, description and forecast cells', () => {
    const { container } = env.render(h(env.hud.WeatherCard, { data }));
    expect(container.querySelector('.weather-deg').textContent).toBe('21');
    expect(container.querySelector('.weather-desc').textContent).toBe('Senin');
    expect(container.querySelectorAll('.fc-cell')).toHaveLength(2);
  });
});

describe('CalendarCard', () => {
  it('marks the next event and renders all rows', () => {
    const items = [
      { ts: '09:00', title: 'Standup', owner: 'pepper', state: 'past' },
      { ts: '11:00', title: 'Review', owner: 'pepper', state: 'next' },
    ];
    const { container } = env.render(h(env.hud.CalendarCard, { items }));
    expect(container.querySelectorAll('.cal-row')).toHaveLength(2);
    expect(container.querySelector('.cal-next')).not.toBeNull();
    expect(container.textContent).toContain('Review');
  });
});

describe('Message', () => {
  it('renders a user message with its text', () => {
    const { container } = env.render(h(env.hud.Message, { m: { role: 'user', text: 'hello', ts: '12:00' }, agentMap: {} }));
    expect(container.querySelector('.msg-user')).not.toBeNull();
    expect(container.querySelector('.msg-body').textContent).toBe('hello');
  });

  it('renders an agent message with an uppercased tag', () => {
    const agentMap = { gecko: { name: 'Gecko', role: 'Markets' } };
    const { container } = env.render(
      h(env.hud.Message, { m: { role: 'agent', agent: 'gecko', text: 'done', ts: '12:01' }, agentMap }),
    );
    expect(container.querySelector('.msg-agent')).not.toBeNull();
    expect(container.querySelector('.msg-tag-agent').textContent).toBe('[GECKO]');
  });
});

describe('ThinkingBubble', () => {
  it('lists routed agents as pills', () => {
    const agentMap = { gecko: { name: 'Gecko' }, stark: { name: 'Stark' } };
    const { container } = env.render(
      h(env.hud.ThinkingBubble, { agent: { name: 'Jarvis' }, routedAgents: ['gecko', 'stark'], agentMap }),
    );
    const pills = [...container.querySelectorAll('.trace-pill')].map((p) => p.textContent.replace('→', ''));
    expect(pills).toEqual(['Gecko', 'Stark']);
  });
});

describe('TopBar', () => {
  const base = {
    activeAgent: 'jarvis', voiceState: 'idle', agentsOnline: 3, agentsTotal: 16, lmOnline: true,
  };

  it('renders agent count and LM Studio port when online', () => {
    const { container } = env.render(h(env.hud.TopBar, base));
    expect(container.textContent).toContain('3/16');
    expect(container.textContent).toContain('1234');
  });

  it('wires the Console open button', () => {
    // The decluttered TopBar (HUD redesign #123) replaced the COG/SYS toggles
    // with a single ▦ Console button that opens the feature console.
    const onOpenConsole = vi.fn();
    const { container } = env.render(h(env.hud.TopBar, { ...base, onOpenConsole }));
    const consoleBtn = [...container.querySelectorAll('button')].find((b) => b.textContent.includes('Console'));
    expect(consoleBtn, 'Console open button').toBeTruthy();
    env.click(consoleBtn);
    expect(onOpenConsole).toHaveBeenCalledTimes(1);
  });

  it('flags LM Studio offline', () => {
    const { container } = env.render(h(env.hud.TopBar, { ...base, lmOnline: false }));
    const lm = container.querySelector('.badge-alert');
    expect(lm).not.toBeNull();
  });
});
