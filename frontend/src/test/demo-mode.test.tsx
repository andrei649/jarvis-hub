import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DemoBanner } from '../app';
import { readDemoMode, replaceDemoMode, useDemoMode } from '../demo-mode';

function DemoHarness() {
  const [demo, setDemo] = useDemoMode();
  return (
    <div>
      <output data-testid="mode">{demo ? 'demo' : 'live'}</output>
      <button onClick={() => setDemo(!demo)}>toggle demo</button>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/v2/');
});

describe('readDemoMode', () => {
  it('enables demo only for an exact demo=1 query value', () => {
    expect(readDemoMode('?demo=1')).toBe(true);
    expect(readDemoMode('?demo=10&notdemo=1')).toBe(false);
  });

  it('accepts one exact value among duplicate demo parameters', () => {
    expect(readDemoMode('?demo=0&demo=1')).toBe(true);
    expect(readDemoMode('?demo=0&demo=10')).toBe(false);
  });
});

describe('replaceDemoMode', () => {
  it('canonicalizes all demo parameters while preserving unrelated query and hash state', () => {
    const next = replaceDemoMode(true, 'http://jarvis/v2/?theme=dark&demo=0&demo=10#mesh');

    expect(next).toBe('/v2/?theme=dark&demo=1#mesh');
  });

  it('removes all demo parameters when returning to live mode', () => {
    const next = replaceDemoMode(false, 'http://jarvis/v2/?demo=1&theme=dark&demo=0#mesh');

    expect(next).toBe('/v2/?theme=dark#mesh');
  });
});

describe('useDemoMode', () => {
  it('ignores stale local storage when the address is live', () => {
    localStorage.setItem('hud.demo', '1');

    render(<DemoHarness />);

    expect(screen.getByTestId('mode').textContent).toBe('live');
  });

  it('uses replaceState instead of creating a new history entry', () => {
    window.history.replaceState({}, '', '/v2/?theme=dark#mesh');
    const replace = vi.spyOn(window.history, 'replaceState');
    const push = vi.spyOn(window.history, 'pushState');
    render(<DemoHarness />);

    fireEvent.click(screen.getByRole('button', { name: 'toggle demo' }));

    expect(replace).toHaveBeenCalledWith(window.history.state, '', '/v2/?theme=dark&demo=1#mesh');
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByTestId('mode').textContent).toBe('demo');
  });

  it('tracks back and forward navigation through popstate', () => {
    render(<DemoHarness />);
    expect(screen.getByTestId('mode').textContent).toBe('live');

    act(() => {
      window.history.pushState({}, '', '/v2/?demo=1');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    expect(screen.getByTestId('mode').textContent).toBe('demo');
  });
});

describe('DemoBanner', () => {
  it('shows the canonical share address beside the demo provenance', () => {
    render(<DemoBanner onExit={() => {}} />);

    expect(screen.getByText(/DEMO DATA/).textContent).toContain('/v2/?demo=1');
  });
});
