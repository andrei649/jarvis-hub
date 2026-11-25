// @ts-nocheck
/* The five mode wrappers are one PageSection now (PHASE_B_PLAN.md §2.3): every mode draws a
   register, with none of the HUD v2 panel markup (the classic frame that kept it went in stage 5),
   and keeps the contracts that lived on the wrapper (the roster's focusable, named body) and the
   strings the parity guard pins in source. */
import { describe, expect, it, vi } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { AgentsMode, MemoryMode } from '../modes';
import { FinanceMode, HealthMode, KnowledgeMode, FamilyMode } from '../modes4';
import { V2 } from '../data';

// the conversation components are not drawn by these modes; stubbing them keeps this test off the composer's own work
vi.mock('../cockpit', () => ({ Conversation: () => null, InputBar: () => null, Bubble: () => null }));
vi.mock('../api/client', async (orig) => ({ ...(await orig()), apiGet: vi.fn().mockRejectedValue(Object.assign(new Error('offline'), { status: 503 })) }));

const t = V2.I18N.en;
const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active', role: 'Prime' },
  { id: 'frigga', name: 'Frigga', tier: 'FND', status: 'idle', role: 'Memory' },
];
const MODES = {
  Agents: () => <AgentsMode agents={AGENTS} onOpen={() => {}} t={t} />,
  Memory: () => <MemoryMode t={t} demo />,
  Finance: () => <FinanceMode t={t} />,
  Health: () => <HealthMode t={t} />,
  Knowledge: () => <KnowledgeMode t={t} />,
  Family: () => <FamilyMode t={t} />,
};

describe.each(Object.entries(MODES))('%s mode', (_name, Mode) => {
  it('draws a register, with no legacy wrapper', () => {
    const { container } = render(<Mode />);
    expect(container.firstElementChild?.classList.contains('n-pagesection')).toBe(true);
    expect(container.querySelector('.n-pagesection > .n-register')).not.toBeNull();
    expect(container.querySelector('.n-register__title')?.textContent?.length).toBeGreaterThan(0);
    expect(container.querySelector(':scope > .panel, .panel-head, .bk')).toBeNull();
  });
});

describe('what lived on the wrapper survives the move', () => {
  it('keeps the roster\'s scrollable body focusable and named', () => {
    const { container } = render(<AgentsMode agents={AGENTS} onOpen={() => {}} t={t} />);
    const body = container.querySelector('.n-register__body') as HTMLElement;
    expect(body.getAttribute('tabindex')).toBe('0');
    expect(body.getAttribute('role')).toBe('group');
    expect(body.getAttribute('aria-label')).toBe(t.roster);
    expect(container.querySelectorAll('.acard').length).toBe(2);
  });

  it('keeps the roster\'s "+ New agent" button in the section head', () => {
    const { container } = render(<AgentsMode agents={AGENTS} onOpen={() => {}} t={t} />);
    expect(container.querySelector('.n-register__meta button')?.textContent).toBe('+ New agent');
  });
});

describe('the strings the parity guard pins stay in their files', () => {
  const read = (file) => readFileSync(join(process.cwd(), 'src', file), 'utf8');
  it('keeps <SavedFacts in modes.tsx and <HermesRuntimePanel/> inside AdminMode in modes3.tsx', () => {
    expect(read('modes.tsx')).toContain('<SavedFacts');
    const modes3 = read('modes3.tsx');
    const admin = modes3.slice(modes3.indexOf('function AdminMode'));
    expect(admin).toContain('<HermesRuntimePanel/>');
  });

  it('leaves no hand-written panel or per-mode wrapper behind (ChatMode aside)', () => {
    for (const file of ['modes.tsx', 'modes2.tsx', 'modes3.tsx', 'modes4.tsx']) {
      const source = read(file);
      expect(source, file).not.toMatch(/function (ModePanel|MP|Panel)\b/);
      expect(source, file).not.toContain('className="bk tl"');
    }
  });
});

// the rest of the modes: each draws a register too
import { CommsMode, AdminMode } from '../modes3';
import { AutonomyMode, BuildMode, ObserveMode, InteropMode } from '../modes2';

const MORE = {
  Comms: () => <CommsMode t={t} />,
  Autonomy: () => <AutonomyMode t={t} />,
  Build: () => <BuildMode t={t} />,
  Observe: () => <ObserveMode t={t} />,
  Interop: () => <InteropMode t={t} />,
  Admin: () => <AdminMode t={t} />,
};

describe.each(Object.entries(MORE))('%s mode wrapper', (_name, Mode) => {
  it('draws a register', () => {
    const { container } = render(<Mode />);
    expect(container.querySelector('.n-pagesection .n-register')).not.toBeNull();
    expect(container.querySelector(':scope > .panel, .n-pagesection > .panel')).toBeNull();
  });
});

describe('Comms keeps its two-column inbox', () => {
  it('the list and the reader sit in one comms-body grid inside the section body', () => {
    const { container } = render(<CommsMode t={t} />);
    const grid = container.querySelector('.n-register__body > .comms-body');
    expect(grid).not.toBeNull();
    expect(grid.querySelector(':scope > .comms-list')).not.toBeNull();
    expect(grid.querySelector(':scope > .comms-read')).not.toBeNull();
    expect(container.querySelectorAll('.comms-body').length).toBe(1);
  });
});
