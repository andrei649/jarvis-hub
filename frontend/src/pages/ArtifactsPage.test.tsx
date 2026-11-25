// @ts-nocheck
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const panel = vi.fn();
vi.mock('../artifacts', () => ({
  ArtifactsPanel: (props) => { panel(props); return (
    <div data-testid="panel">
      <button onClick={() => props.onDiscussProject({ path: 'p.blend', title: 'Robot', view: 'robot' })}>Discuss in chat</button>
      <button onClick={() => props.onInspectBlend(new File([''], 'x.blend'))}>Inspect</button>
    </div>); },
}));
const navigateHud = vi.fn();
vi.mock('../hud-routing', async (orig) => ({ ...(await orig()), navigateHud: (...a) => navigateHud(...a) }));

import { ArtifactsPage } from './ArtifactsPage';

const base = () => ({ lang: 'en', demo: false, refreshKey: 3, onInspectBlend: vi.fn().mockReturnValue(false), onDiscussProject: vi.fn() });
beforeEach(() => { panel.mockClear(); navigateHud.mockClear(); });
afterEach(cleanup);

describe('ArtifactsPage', () => {
  it('wraps the Artifacts panel with its refresh key, language and the composer\'s blend inspector', () => {
    const props = base();
    render(<ArtifactsPage {...props} />);
    const seen = panel.mock.calls.at(-1)[0];
    expect(seen).toMatchObject({ refreshKey: 3, lang: 'en', exportAllowed: true });
    fireEvent.click(screen.getByText('Inspect'));
    expect(props.onInspectBlend).toHaveBeenCalledTimes(1);
  });

  it('stages the project and then goes to the conversation', () => {
    const props = base();
    render(<ArtifactsPage {...props} />);
    fireEvent.click(screen.getByText('Discuss in chat'));
    expect(props.onDiscussProject).toHaveBeenCalledWith({ path: 'p.blend', title: 'Robot', view: 'robot' });
    expect(navigateHud).toHaveBeenCalledWith('/v2/cockpit');
    expect(props.onDiscussProject.mock.invocationCallOrder[0]).toBeLessThan(navigateHud.mock.invocationCallOrder[0]);
  });

  it('reads nothing in demo, and says so', () => {
    render(<ArtifactsPage {...base()} demo />);
    expect(screen.queryByTestId('panel')).toBeNull();
    expect(document.querySelector('[data-demo-note]').textContent).toMatch(/Demo sample/);
  });

  it('says it in Romanian', () => {
    render(<ArtifactsPage {...base()} demo lang="ro" />);
    expect(document.querySelector('[data-demo-note]').textContent).toMatch(/Mostră demo/);
  });
});
